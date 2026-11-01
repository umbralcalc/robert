"""Experiments: questions, answers with stated assumptions and evidence, follow-ups."""

import pytest

from robert import experiments as ex
from robert.project import MARKER, MethodError, Project

ROBERT_OWNS = {"assumption": "goals arrive as a Poisson process", "owner": "robert",
               "kind": "implementation", "sensitivity": "untested",
               "why": "simplest count process"}
FOLLOW = [{"question": "Does a red card change the scoring rate?", "kind": "test-assumption",
           "value": "high", "discriminates": ["random goals", "red cards matter"]},
          {"question": "When in the match do goals come?", "kind": "deepen", "value": "low"}]
AGAINST = [{"point": "totals alone cannot tell when goals happen"}]
NOTHING = [{"standing": f"S{i}", "report": "nothing to report"} for i in range(1, 5)]


def ans(project, eid, text, assumptions, evidence, follow_ups=FOLLOW, **kw):
    kw.setdefault("against", AGAINST)
    kw.setdefault("reports", NOTHING)
    return ex.answer(project, eid, text, assumptions, evidence, follow_ups=follow_ups, **kw)


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".robert").mkdir()
    (tmp_path / MARKER).write_text("name: t\n")
    (tmp_path / "out").mkdir()
    (tmp_path / "out/match.log").write_text("{}\n")
    (tmp_path / "out/match.log.provenance.json").write_text('{"key": "k"}')
    p = Project(tmp_path)
    ex.write_default_standing(p)
    return p


def test_ask_opens_numbered_experiments_with_context(project):
    a = ex.ask(project, "Can a mock match reproduce a 2-1 scoreline?")
    b = ex.ask(project, "And the cards?", parent=a["experiment"])
    assert (a["experiment"], b["experiment"]) == ("E001", "E002")
    assert ex.get(project, "E002")["parent"] == "E001"
    assert a["context"]["open"] == []


def test_answer_gate_wants_assumptions_evidence_and_follow_ups(project):
    eid = ex.ask(project, "How many goals per match?")["experiment"]
    out = ex.answer(project, eid, "About 3 goals per match", [], [], [], [])
    failed = {c["check"] for c in out["gate"]["failed"]}
    assert {"its assumptions are stated", "numbers rest on evidence",
            "follow-ups are suggested", "the strongest case against is stated",
            "every standing question has a report",
            "a follow-up names the explanations it would tell apart"} <= failed
    assert ex.get(project, eid)["status"] == "open"


def test_evidence_must_exist(project):
    eid = ex.ask(project, "q")["experiment"]
    out = ans(project, eid, "3 goals", [ROBERT_OWNS],
              [{"kind": "output", "ref": "out/missing.log"},
               {"kind": "test", "ref": "no-such-test"}])
    detail = next(c for c in out["gate"]["failed"]
                  if c["check"] == "every piece of evidence exists")["detail"]
    assert "out/missing.log" in detail and "no-such-test" in detail


def test_answered_experiment_records_everything(project):
    eid = ex.ask(project, "How many goals per match?")["experiment"]
    out = ans(project, eid, "About 3 goals per match, 2 home and 1 away",
              [ROBERT_OWNS], [{"kind": "output", "ref": "out/match.log"}],
              follow_ups=list(reversed(FOLLOW)),
              tried=[{"analysis": "posterior_estimation", "outcome": "NaN: negative rates"}],
              hypotheses=["random goals", "red cards matter"])
    assert out["gate"]["passed"], out["gate"]["failed"]
    assert out["follow_ups"][0].startswith("E001.1: Does a red card")  # ranked by value
    rec = ex.get(project, eid)
    assert rec["status"] == "answered" and rec["assumptions"][0]["kind"] == "implementation"
    assert rec["against"] == AGAINST and rec["tried"][0]["outcome"].startswith("NaN")


def test_choice_kinds_reach_the_user_the_right_way(project):
    eid = ex.ask(project, "q")["experiment"]
    belief = {**ROBERT_OWNS, "kind": "belief", "sensitivity": "sensitive",
              "assumption": "half of penalties are scored"}
    oper = {**ROBERT_OWNS, "kind": "operationalisation",
            "assumption": "reproduces means within 10%"}
    out = ans(project, eid, "It depends on the timing", [ROBERT_OWNS, belief, oper], [])
    notes = " ".join(out["gate"]["for_your_judgment"])
    assert "ask the user what they believe" in notes and "within 10%" in notes
    assert "Poisson" not in notes  # implementation choices are never surfaced


def test_standing_questions_need_reports_and_surface_in_context(project):
    added = ex.standing(project, add=["Did any card total exceed 8?"], retire=["S4"])
    assert "S5: Did any card total exceed 8?" in added["standing"]
    assert not any(s.startswith("S4") for s in added["standing"])
    eid = ex.ask(project, "q")["experiment"]
    out = ans(project, eid, "an answer", [ROBERT_OWNS], [])
    assert any("S5" in c.get("detail", "") for c in out["gate"]["failed"])
    reports = NOTHING[:3] + [{"standing": "S5", "report": "one match had 9 cards"}]
    assert ans(project, eid, "an answer", [ROBERT_OWNS], [], reports=reports)["gate"]["passed"]
    assert ex.context(project)["answered"][0]["reports"] == ["S5: one match had 9 cards"]


def test_follow_ups_chain_and_context(project):
    e1 = ex.ask(project, "How many goals?")["experiment"]
    ans(project, e1, "About 3", [ROBERT_OWNS], [{"kind": "file", "ref": "out/match.log"}])
    e2 = ex.ask(project, "", from_follow_up="E001.1")
    rec = ex.get(project, e2["experiment"])
    assert rec["parent"] == "E001" and rec["question"] == FOLLOW[0]["question"]
    ctx = ex.context(project, focus=e2["experiment"])
    assert [e["id"] for e in ctx["focus_chain"]] == ["E001", "E002"]
    assert ctx["suggested"] == ["E001.2: When in the match do goals come?"]
    with pytest.raises(MethodError, match="follow-ups"):
        ex.ask(project, "", from_follow_up="E001.9")


def test_superseding_an_answer(project):
    e1 = ex.ask(project, "q1")["experiment"]
    ans(project, e1, "first view", [ROBERT_OWNS], [])
    e2 = ex.ask(project, "q1 again, with cards", parent=e1)["experiment"]
    ans(project, e2, "revised view", [ROBERT_OWNS], [], supersedes=e1)
    assert ex.get(project, e1)["status"] == "superseded"
    assert ex.context(project)["answered"][0]["id"] == "E002"


def _belief(project, tolerance, converged=True):
    return project.append_ledger("beliefs", {
        "kind": "parameters", "variant": None, "config": "model/confront.yaml",
        "posterior": {"rate": {"mean": [1.0], "sd": [0.1]}},
        "convergence": {"tolerance": tolerance, "default_tolerance": 0.05,
                        "converged": converged, "drift": {"rate": 0.066}}})["hash"]


@pytest.mark.parametrize("tolerance,converged,owed", [
    (0.07, True, "looser than the default"),
    (0.05, False, "did not converge"),
])
def test_loosened_or_unconverged_beliefs_must_be_stated(project, tolerance, converged, owed):
    h = _belief(project, tolerance, converged)
    eid = ex.ask(project, "How many goals per match?")["experiment"]
    evidence = [{"kind": "ledger", "ref": h}]
    out = ans(project, eid, "About 3 goals per match", [ROBERT_OWNS], evidence)
    failed = {c["check"]: c["detail"] for c in out["gate"]["failed"]}
    assert owed in failed["loosened or unconverged beliefs are stated as assumptions"]

    stated = {"assumption": "the goal-trend slope drifts within its standard error",
              "owner": "robert", "kind": "operationalisation", "ref": h}
    out = ans(project, eid, "About 3 goals per match", [ROBERT_OWNS, stated], evidence)
    assert out["gate"]["passed"], out["gate"]["failed"]
    assert ex.get(project, eid)["assumptions"][1]["ref"] == h


def test_the_beliefs_the_model_runs_with_count_even_uncited(project):
    """The latest beliefs for the current variant are owed even when not cited."""
    _belief(project, 0.07)
    eid = ex.ask(project, "q")["experiment"]
    out = ans(project, eid, "3 goals", [ROBERT_OWNS], [{"kind": "output", "ref": "out/match.log"}])
    assert not out["gate"]["passed"]


def test_default_tolerance_beliefs_owe_nothing(project):
    h = _belief(project, 0.05)
    eid = ex.ask(project, "q")["experiment"]
    out = ans(project, eid, "3 goals", [ROBERT_OWNS], [{"kind": "ledger", "ref": h}])
    assert out["gate"]["passed"], out["gate"]["failed"]
