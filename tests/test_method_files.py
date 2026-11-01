import json

import pytest
import yaml

from robert.contracts import (
    check_claim,
    check_expressions,
    check_intervention,
    check_partitions,
    check_test_spec,
    expression_partitions,
)
from robert.project import MARKER, MethodError, Project


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".robert").mkdir()
    (tmp_path / MARKER).write_text("name: t\n")
    return Project(tmp_path)


def test_find_walks_up(project):
    deep = project.root / "a/b"
    deep.mkdir(parents=True)
    assert Project.find(deep).root == project.root


def test_find_outside_a_project(tmp_path):
    with pytest.raises(MethodError, match="robert init"):
        Project.find(tmp_path)


def test_ledger_is_chained_and_tamper_evident(project):
    a = project.append_ledger("warrants", {"statement": "first"})
    b = project.append_ledger("warrants", {"statement": "second"})
    assert b["prev"] == a["hash"]
    assert project.verify_ledger("warrants") == []

    path = project.path("ledger/warrants.jsonl")
    lines = path.read_text().splitlines()
    edited = json.loads(lines[0])
    edited["statement"] = "rewritten after the fact"
    path.write_text(json.dumps(edited, sort_keys=True) + "\n" + lines[1] + "\n")
    assert any("edited" in p for p in project.verify_ledger("warrants"))


def test_append_yaml_list_keeps_earlier_entries_verbatim(project):
    project.path("interventions.yaml").write_text("[]\n")
    project.append_yaml_list("interventions.yaml", {"step": "test", "reason": "one"})
    before = project.path("interventions.yaml").read_text()
    project.append_yaml_list("interventions.yaml", {"step": "test", "reason": "two"})
    after = project.path("interventions.yaml").read_text()
    assert after.startswith(before)
    assert [e["reason"] for e in yaml.safe_load(after)] == ["one", "two"]


def test_claim_contract():
    assert check_claim({"question": "q", "claim": "c", "intended_use": "forecast",
                        "conditions": ["x"], "observables": ["p"]}) == []
    problems = check_claim({"question": "q", "intended_use": "predict"})
    assert any("`claim`" in p for p in problems)
    assert any("intended_use" in p for p in problems)


def test_partitions_sidecar_matches_sim_exactly():
    side = {"partitions": {"a": {"role": "structural", "hypothesis": "h"},
                           "ghost": {"role": "nuisance", "hypothesis": "h"}}}
    problems = check_partitions(side, ["a", "b"])
    assert any("`b` is in sim.yaml" in p for p in problems)
    assert any("`ghost` is not a partition" in p for p in problems)


SIM = {"main": {
    "partitions": [{"name": "rate", "params": {"base": [1.0]}},
                   {"name": "ratio", "iteration": {"type": "expression", "outputs": ["1"]}},
                   {"name": "arrivals", "iteration": {"type": "poisson_process"}}],
    "expressions": [{"partition": "rate", "fields": [{"name": "r"}], "outputs": ["base"]}]}}
BUILTINS = {"poisson_process", "cox_process", "periodic", "expression"}


def test_expression_partitions_are_found_both_ways():
    assert expression_partitions(SIM) == ["rate", "ratio"]


def test_every_expression_says_why_no_builtin_fits():
    why = {"considered": ["cox_process", "periodic"], "reason": "a sinusoid in t"}
    side = {"partitions": {"rate": {"why_expression": why},
                           "ratio": {"why_expression": {"considered": ["poisson_process"]}}}}
    problems = check_expressions(side, SIM, BUILTINS)
    assert len(problems) == 1 and "`ratio` is an expression" in problems[0]
    assert check_expressions(side, SIM, BUILTINS, only=["rate", "arrivals"]) == []


def test_considered_names_must_be_registered_builtins():
    side = {"partitions": {n: {"why_expression": {"considered": c, "reason": "r"}}
                           for n, c in (("rate", ["sine_wave"]), ("ratio", ["expression"]))}}
    problems = check_expressions(side, SIM, BUILTINS)
    assert "`sine_wave`" in problems[0] and "`expression`" in problems[1]


def test_a_stochadex_suggestion_fails_whatever_the_reason():
    why = {"considered": ["cox_process"], "reason": "r"}
    side = {"partitions": {"rate": {"why_expression": why}, "ratio": {"why_expression": why}}}
    problems = check_expressions(side, SIM, BUILTINS, suggestions={"rate": "cox_process"})
    assert problems == ["`rate`: stochadex says this expression reimplements `cox_process`; "
                        "use the built-in"]


def test_backtest_must_not_leak():
    spec = {"id": "bt", "partitions": ["p"], "kind": "backtest", "script": "s.py",
            "train_end": 30, "test_start": 25}
    assert any("leakage" in p for p in check_test_spec(spec))


def test_intervention_contract():
    assert check_intervention({"step": "test", "actor": "user", "agent_proposal": "a",
                               "decision": "redirect", "reason": "r"}) == []
    assert check_intervention({"step": "test", "actor": "boss", "agent_proposal": "a",
                               "decision": "redirect", "reason": "r"})
