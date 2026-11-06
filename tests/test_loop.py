"""The whole loop against a real stochadex binary, through the CLI an agent would call."""

import json
import subprocess

import pytest
import yaml

from robert import loop
from robert.checks import Gate
from robert.engine import Engine, _json_tail
from robert.project import MethodError, Project

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


def _expression_project(target, cli_env):
    subprocess.run(["robert", "init", "--path", str(target), "--name", "x", "--no-git",
                    "--description", "d", "--level", "expert", "--user-knows", "k"],
                   check=True, capture_output=True, env=cli_env)
    (target / "model/sim.yaml").write_text(yaml.safe_dump({"main": {
        "partitions": [
            {"name": "rate", "params": {"base": [2.0]}, "init_state_values": [2.0],
             "state_history_depth": 1, "seed": 1},
            {"name": "arrivals", "iteration": {"type": "poisson_process"},
             "params": {"rates": [2.0]}, "params_from_upstream": {"rates": {"upstream": "rate"}},
             "init_state_values": [0.0], "state_history_depth": 1, "seed": 2}],
        "expressions": [{"partition": "rate", "fields": [{"name": "r"}],
                         "outputs": ["base * (1 + 0.5 * sin(2 * pi * t / 12))"]}],
        "simulation": {"termination_condition": {"type": "number_of_steps", "max_steps": 3},
                       "timestep_function": {"type": "constant", "stepsize": 1.0},
                       "init_time_value": 0.0}}}))


def _conjecture(target, cli_env, partitions):
    proc = subprocess.run(["robert", "--json", "conjecture", "--rationale", "r",
                           "--partitions", json.dumps(partitions)],
                          cwd=target, capture_output=True, text=True, env=cli_env)
    return proc.returncode, json.loads(proc.stdout)


@needs_stochadex
def test_an_expression_without_a_reason_fails_conjecture(tmp_path, cli_env):
    """Built-ins first: an expression partition records why no built-in fits."""
    target = tmp_path / "p"
    _expression_project(target, cli_env)
    arrivals = {"role": "structural", "hypothesis": "counts at the rate"}
    rate = {"role": "structural", "hypothesis": "a yearly cycle"}
    code, out = _conjecture(target, cli_env, {"rate": rate, "arrivals": arrivals})
    assert code == 1
    failed = {c["check"]: c["detail"] for c in out["gate"]["failed"]}
    assert "`rate` is an expression" in failed["every expression partition says why no "
                                               "built-in fits"]
    assert out["expressions"] == {"expression_partitions": ["rate"], "partitions": 2}

    rate["why_expression"] = {"considered": ["cox_process", "periodic"],
                              "reason": "a deterministic sinusoid in t"}
    code, out = _conjecture(target, cli_env, {"rate": rate, "arrivals": arrivals})
    assert code == 0, out["gate"]["failed"]
    p = Project(target)
    assert loop.lineage(p)["variants"][0]["expression_partitions"] == ["rate"]
    assert p.read_yaml("model/partitions.yaml")["partitions"]["rate"]["why_expression"]
    status = json.loads(subprocess.run(["robert", "--json", "status"], cwd=target,
                                       capture_output=True, text=True, env=cli_env).stdout)
    assert status["expression_partitions"] == {"count": 1, "of": 2}


@needs_stochadex
def test_catalogue_search_finds_the_builtin(tmp_path, cli_env):
    proc = subprocess.run(["robert", "--json", "catalogue", "--search", "poisson",
                           "--search", "count", "--kinds", "iterations"],
                          cwd=tmp_path, capture_output=True, text=True, env=cli_env)
    out = json.loads(proc.stdout)
    assert out["catalogue_version"] >= 2
    top = out["matches"][0]
    assert top["name"] == "poisson_process" and top["params"] == [{"name": "rates"}]
    assert "expression" not in {m["name"] for m in out["matches"]}


WIENER = "w + sqrt(variances * dt) * shared(normal(0, 1))"
WHY = {"considered": ["wiener_process"], "reason": "it needs its own form"}
CLOCK = {"termination_condition": {"type": "number_of_steps", "max_steps": 20},
         "timestep_function": {"type": "constant", "stepsize": 0.5}, "init_time_value": 0.0}


def _walk_sim(update=WIENER):
    return {"main": {
        "partitions": [{"name": "walk", "params": {"variances": [2.0]},
                        "init_state_values": [0.0], "state_history_depth": 1, "seed": 1}],
        "expressions": [{"partition": "walk", "fields": [{"name": "w"}], "outputs": [update]}],
        "simulation": CLOCK}}


def _project_with(target, cli_env, sim):
    subprocess.run(["robert", "init", "--path", str(target), "--name", "x", "--no-git",
                    "--description", "d", "--level", "expert", "--user-knows", "k"],
                   check=True, capture_output=True, env=cli_env)
    (target / "model/sim.yaml").write_text(yaml.safe_dump(sim))


@needs_stochadex
def test_an_expression_restating_a_builtin_fails_with_its_replacement(tmp_path, cli_env):
    """A reason doesn't excuse it, and the YAML in the failure is what passes the gate."""
    target = tmp_path / "p"
    _project_with(target, cli_env, _walk_sim())
    walk = {"role": "structural", "hypothesis": "a random walk", "why_expression": WHY}
    code, out = _conjecture(target, cli_env, {"walk": walk})
    assert code == 1
    detail = {c["check"]: c["detail"] for c in out["gate"]["failed"]}[
        "every expression partition says why no built-in fits"]
    assert "`wiener_process`" in detail
    replacement = yaml.safe_load(detail.split("replace the partition with:\n")[1])
    assert replacement[0]["iteration"] == {"type": "wiener_process"}
    assert replacement[0]["params"] == {"variances": [2]}

    sim = _walk_sim()
    sim["main"]["partitions"] = replacement
    del sim["main"]["expressions"]
    (target / "model/sim.yaml").write_text(yaml.safe_dump(sim))
    code, out = _conjecture(target, cli_env, {"walk": walk})
    assert code == 0, out["gate"]["failed"]
    assert out["expressions"]["expression_partitions"] == []


@needs_stochadex
def test_a_replacement_factors_out_what_the_builtin_cannot_take(tmp_path, cli_env):
    """A rate written into the draw becomes a rate partition feeding the built-in."""
    target = tmp_path / "p"
    update = "w + where(shared(uniform(0, 1)) * (2 + sin(t) + 1 / dt) < 2 + sin(t), 1, 0)"
    _project_with(target, cli_env, _walk_sim(update))
    walk = {"role": "structural", "hypothesis": "arrivals", "why_expression": WHY}
    code, out = _conjecture(target, cli_env, {"walk": walk})
    assert code == 1
    detail = out["gate"]["failed"][0]["detail"]
    replacement = yaml.safe_load(detail.split("replace the partition with:\n")[1])
    assert [p["name"] for p in replacement] == ["walk_rates", "walk"]
    assert replacement[1]["iteration"] == {"type": "poisson_process"}
    assert replacement[1]["params_from_upstream"] == {"rates": {"upstream": "walk_rates"}}


@needs_stochadex
def test_discover_asks_about_the_variant_as_it_will_run(tmp_path, cli_env):
    """The suggestion comes from the variant's config with its sets applied."""
    target = tmp_path / "p"
    _expression_project(target, cli_env)
    why = {"considered": ["cox_process"], "reason": "a sinusoid in t"}
    code, out = _conjecture(target, cli_env, {
        "rate": {"role": "structural", "hypothesis": "h", "why_expression": why},
        "arrivals": {"role": "structural", "hypothesis": "h"}})
    assert code == 0, out["gate"]["failed"]

    sim = yaml.safe_load((target / "model/sim.yaml").read_text())
    sim["main"]["partitions"] += _walk_sim()["main"]["partitions"]
    sim["main"]["expressions"] += _walk_sim()["main"]["expressions"]
    (target / "model/variant.yaml").write_text(yaml.safe_dump(sim))
    (target / "score.py").write_text('print(\'{"score": 1}\')\n')
    out = loop.discover(Project(target), "walk", "r", "score.py", ["walk"],
                        config="model/variant.yaml",
                        sets=["main.partitions[name=walk].params.variances=[9.0]"],
                        partitions={"walk": {"role": "structural", "hypothesis": "h",
                                             "why_expression": WHY}})
    detail = {c["check"]: c["detail"] for c in out["gate"]["failed"]}[
        "every expression partition says why no built-in fits"]
    assert "`wiener_process`" in detail and "variances: [9]" in detail

    # `rate` isn't what this variant changes, so only the walk is held to account.
    gate = Gate("discover")
    side = {"rate": {"why_expression": why}, "walk": {"why_expression": WHY}}
    loop._expressions_gate(gate, Engine(target), side, sim, "model/variant.yaml", only=["rate"])
    assert gate.passed


@needs_stochadex
def test_a_config_stochadex_cannot_run_gets_a_note_not_a_failure(tmp_path):
    """--check reads no inputs, so a missing one first shows when suggesting runs the config."""
    sim = _walk_sim()
    sim["inputs"] = {"obs": {"source": {"csv": {"path": "absent.csv", "time_column": 0,
                                                "state_columns": {"flow": [1]}}}}}
    sim["main"]["partitions"].append({"name": "flow", "iteration": {"type": "from_input", "input": "obs"},
                                      "init_state_values": [0.0], "state_history_depth": 1, "seed": 0})
    (tmp_path / "sim.yaml").write_text(yaml.safe_dump(sim))
    engine = Engine(tmp_path)
    with pytest.raises(MethodError, match="inspect --suggest failed"):
        engine.inspect_suggest("sim.yaml")

    gate = Gate("conjecture")
    loop._expressions_gate(gate, engine, {"walk": {"why_expression": WHY}}, sim, "sim.yaml")
    assert gate.passed
    assert len(gate.notes) == 1 and "could not check whether an expression" in gate.notes[0]


@needs_stochadex
def test_a_config_failing_check_is_not_asked_for_suggestions(tmp_path, cli_env):
    target = tmp_path / "p"
    sim = _walk_sim()
    sim["main"]["simulation"] = {**CLOCK, "typo": 1}
    _project_with(target, cli_env, sim)
    walk = {"role": "structural", "hypothesis": "h", "why_expression": WHY}
    code, out = _conjecture(target, cli_env, {"walk": walk})
    assert code == 1
    assert "stochadex --check" in {c["check"] for c in out["gate"]["failed"]}
    assert "for_your_judgment" not in out["gate"]


@needs_stochadex
def test_no_suggestion_is_asked_for_without_an_expression_to_check(tmp_path):
    """Suggesting runs the config, so a config with nothing to judge isn't run for it."""
    sim = _walk_sim()
    (tmp_path / "sim.yaml").write_text("not: a config\n")
    gate = Gate("discover")
    loop._expressions_gate(gate, Engine(tmp_path), {}, sim, "sim.yaml", only=["other"])
    assert gate.passed and gate.notes == []


def test_json_tail_finds_an_object_or_a_list_after_a_banner():
    assert _json_tail('banner a={b} c=[d]\n{"a": 1}\n') == {"a": 1}
    assert _json_tail('[\n  {"yaml": "- {type: x}\\n"}\n]\n') == [{"yaml": "- {type: x}\n"}]
    assert _json_tail("[]\n") == []
    with pytest.raises(MethodError, match="printed no JSON"):
        _json_tail("banner a={b}\n")
