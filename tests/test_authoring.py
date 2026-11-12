"""The authoring log: what each stochadex call on a config records, and its summary."""

import json
import subprocess

from robert import authoring, loop, support
from robert.engine import Engine
from robert.tools import BY_NAME

from .conftest import needs_stochadex

PARTITION = ("- {name: w, iteration: {type: wiener_process}, params: {variances: [1.0]}, "
             "init_state_values: [0.0], state_history_depth: 1, seed: 1}\n")
SIMULATION = ("simulation:\n"
              "  termination_condition: {type: number_of_steps, max_steps: 3}\n"
              "  timestep_function: {type: constant, stepsize: 1.0}\n"
              "  init_time_value: 0.0\n")


def call(config, sha, exit_code, error=""):
    return {"config": config, "sha": sha, "exit_code": exit_code, "error": error}


def test_summary_counts_attempts_failures_and_retries():
    calls = [
        call("model/sim.yaml", "a", 78, "stochadex: unknown type"),  # failed, then fixed
        call("model/sim.yaml", "a", 78, "stochadex: unknown type"),  # same text: same attempt
        call("model/sim.yaml", "b", 0),
        call("model/sim.yaml", "b", 0),                              # check then inspect
        call("model/sim.yaml", "b", 70, "stochadex: simulation failed"),  # then failed running
        call("model/sim.yaml", "c", 78, "stochadex: deadlock"),      # another error, fixed
        call("model/sim.yaml", "d", 70, "stochadex: simulation failed"),  # not authoring
        call("model/v1.yaml", "e", 78, "stochadex: unknown type"),   # never retried
    ]
    assert authoring.summary(calls) == {
        "attempts": 5, "failed": 3, "retried": 2,
        "errors": {"stochadex: unknown type": 2, "stochadex: deadlock": 1},
    }
    assert list(authoring.summary(calls)["errors"]) == [
        "stochadex: unknown type", "stochadex: deadlock"]


def test_summary_of_nothing():
    assert authoring.summary([]) == {"attempts": 0, "failed": 0, "retried": 0, "errors": {}}


def test_record_logs_only_config_calls_in_a_project(tmp_path):
    assert authoring.record(tmp_path, ["--config", "sim.yaml", "--check"], 0, "") is None
    (tmp_path / ".robert").mkdir()
    (tmp_path / ".robert/project.yaml").write_text("name: p\n")
    assert authoring.record(tmp_path, ["catalogue"], 0, "") is None
    (tmp_path / "sim.yaml").write_text("a: 1\n")
    entry = authoring.record(tmp_path, ["--config", "sim.yaml", "--check"], 78,
                             "stochadex-run version=v\nstochadex: api: bad\nmore\n")
    assert entry["command"] == "check" and entry["config"] == "sim.yaml" and not entry["ok"]
    assert entry["error"] == "stochadex: api: bad"
    inspected = authoring.record(tmp_path, ["inspect", "--io", "-c", "sim.yaml"], 0,
                                 "stochadex: sim.yaml is valid\n")
    ran = authoring.record(tmp_path, ["--config", "gone.yaml"], 0, "")
    assert inspected["command"] == "inspect" and inspected["error"] == ""
    assert inspected["sha"] == entry["sha"]
    assert ran["command"] == "run" and ran["sha"] != entry["sha"]
    assert authoring.entries(tmp_path) == [entry, inspected, ran]
    assert authoring.record(tmp_path, ["--config"], 0, "") is None
    long = authoring.record(tmp_path, ["--config", "sim.yaml"], 78, "stochadex: " + "x" * 400)
    assert long["error"] == ("stochadex: " + "x" * 400)[:300]


@needs_stochadex
def test_a_failed_config_is_logged_through_every_route(tmp_path, cli_env):
    roots = []
    for name in ("first", "second"):
        root = tmp_path / name
        loop.init(str(root), name, "a walk", "expert", [], git=False)
        roots.append(root)
    root = roots[0]
    sim = root / "model/sim.yaml"
    sim.parent.mkdir(parents=True, exist_ok=True)
    engine = Engine(root)
    good = "main:\n  partitions:\n  " + PARTITION + "".join(
        "  " + line + "\n" for line in SIMULATION.splitlines())
    bad = good.replace("wiener_process", "weiner_process")

    sim.write_text(bad)
    assert engine.check("model/sim.yaml").exit_code == 78
    sim.write_text(good)
    assert engine.check("model/sim.yaml").ok
    engine.inspect_io("model/sim.yaml")

    calls = authoring.entries(root)
    assert [(c["command"], c["ok"], bool(c["error"])) for c in calls] == [
        ("check", False, True), ("check", True, False), ("inspect", True, False)]
    error = calls[0]["error"]
    assert "weiner_process" in error
    want = {"attempts": 2, "failed": 1, "retried": 1, "errors": {error: 1}}
    assert support.status(loop.Project(root))["authoring"] == want
    assert BY_NAME["authoring"].call({"project": str(root)}) == want

    # The second project fails the same text of the same config path: still its own attempt.
    other = roots[1] / "model/sim.yaml"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text(bad)
    assert Engine(roots[1]).check("model/sim.yaml").exit_code == 78

    out = subprocess.run(["robert", "--json", "authoring", "--projects", str(roots[0]),
                          "--projects", str(roots[1])],
                         capture_output=True, text=True, env=cli_env, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout)
    assert report["projects"][str(roots[0])] == want
    assert report["projects"][str(roots[1])] == {
        "attempts": 1, "failed": 1, "retried": 0, "errors": {error: 1}}
    assert report["total"] == {"attempts": 3, "failed": 2, "retried": 1, "errors": {error: 2}}
