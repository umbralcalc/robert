"""The whole loop against a real stochadex binary, through the CLI an agent would call."""

import json
import subprocess

import yaml

from robert import loop
from robert.project import Project

from .conftest import EXAMPLE, needs_stochadex


@needs_stochadex
def test_walkthrough_runs_the_whole_loop(tmp_path, cli_env):
    target = tmp_path / "project"
    proc = subprocess.run(["bash", str(EXAMPLE / "walkthrough.sh"), str(target)],
                          capture_output=True, text=True, env=cli_env)
    assert proc.returncode == 0, proc.stderr
    p = Project(target)

    lin = loop.lineage(p)
    assert [(v["id"], v["step"]) for v in lin["variants"]] == [
        ("v0", "conjecture"), ("v1", "discover"), ("v2", "compress")]
    assert lin["current"] == "v2"
    assert lin["variants"][1]["evidence"]["verdict"] == "accepted"
    assert lin["variants"][2]["evidence"]["relative_change"] <= 0.05

    beliefs = p.ledger_entries("beliefs")[0]["posterior"]["ols"]["mean"]
    r, slope = beliefs
    assert 0.25 < r < 0.35 and 80 < -r / slope < 120  # growth rate and capacity

    warrant = p.ledger_entries("warrants")[-1]
    assert warrant["variant"] == "v2" and p.verify_ledger("warrants") == []
    assert len(warrant["provenance_key"]) == 64

    assert p.read_yaml("queries/fc-1.yaml")["mode"] == "forecast"
    assert not p.exists("queries/dec-1.yaml")  # refused: no model-part swap
    assert p.read_yaml("interventions.yaml")[0]["decision"] == "redirect"
    assert (target / "figures/model-population.svg").read_text().startswith("<svg")
    assert "-.->" not in (target / "figures/graph-tests.mmd").read_text()

    e1, e2 = p.read_yaml("experiments/E001.yaml"), p.read_yaml("experiments/E002.yaml")
    assert e1["status"] == "answered" and e1["model_variant"] == "v2"
    assert {a["owner"] for a in e1["assumptions"]} == {"user", "robert"}
    assert e1["against"] and len(e1["tried"]) == 2 and len(e1["reports"]) == 4
    assert e2["parent"] == "E001" and e2["from_follow_up"] == "E001.1"


@needs_stochadex
def test_first_conjecture_fails_its_tests(tmp_path, cli_env):
    """Unconstrained growth must fail both the backtest and the process check."""
    target = tmp_path / "project"
    subprocess.run(["bash", str(EXAMPLE / "walkthrough.sh"), str(target)],
                   capture_output=True, text=True, env=cli_env, check=True)
    p = Project(target)
    results = p.read_yaml("tests.yaml")["results"]
    # Results hold the latest run per check; the v0 failures are in the lineage
    # (discover's parent score) and the redirect the user logged.
    assert all(r["variant"] == "v2" and r["passed"] for r in results.values())
    v1 = loop.lineage(p)["variants"][1]["evidence"]
    assert v1["score"] > v1["parent_score"]


@needs_stochadex
def test_learned_structural_partition_is_refused_at_conjecture(tmp_path, cli_env):
    target = tmp_path / "p"
    subprocess.run(["robert", "init", "--path", str(target), "--name", "x", "--no-git",
                    "--description", "d", "--level", "expert", "--user-knows", "k"],
                   check=True, capture_output=True, env=cli_env)
    (target / "model/sim.yaml").write_text(yaml.safe_dump({"main": {
        "partitions": [{"name": "growth", "iteration": {"type": "onnx_inference"},
                        "init_state_values": [0.0], "state_history_depth": 1, "seed": 1}],
        "simulation": {"termination_condition": {"type": "number_of_steps", "max_steps": 3},
                       "timestep_function": {"type": "constant", "stepsize": 1.0},
                       "init_time_value": 0.0}}}))
    proc = subprocess.run(
        ["robert", "--json", "conjecture", "--rationale", "learn it",
         "--partitions", json.dumps({"growth": {"role": "structural", "hypothesis": "h"}})],
        cwd=target, capture_output=True, text=True, env=cli_env)
    assert proc.returncode == 1
    failed = {c["check"] for c in json.loads(proc.stdout)["gate"]["failed"]}
    assert "no learned structural partition before discover" in failed
