"""Experiments: questions, answers with stated assumptions and evidence, follow-ups."""

import pytest

from robert import experiments as ex
from robert.project import MARKER, MethodError, Project

ROBERT_OWNS = {"assumption": "goals arrive as a Poisson process", "owner": "robert",
               "sensitivity": "untested", "why": "simplest count process"}
FOLLOW = [{"question": "Does a red card change the scoring rate?", "kind": "test-assumption"},
          {"question": "When in the match do goals come?", "kind": "deepen"}]


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".robert").mkdir()
    (tmp_path / MARKER).write_text("name: t\n")
    (tmp_path / "out").mkdir()
    (tmp_path / "out/match.log").write_text("{}\n")
    (tmp_path / "out/match.log.provenance.json").write_text('{"key": "k"}')
    return Project(tmp_path)


def test_ask_opens_numbered_experiments_with_context(project):
    a = ex.ask(project, "Can a mock match reproduce a 2-1 scoreline?")
    b = ex.ask(project, "And the cards?", parent=a["experiment"])
    assert (a["experiment"], b["experiment"]) == ("E001", "E002")
    assert ex.get(project, "E002")["parent"] == "E001"
    assert a["context"]["open"] == []


def test_answer_gate_wants_assumptions_evidence_and_follow_ups(project):
    eid = ex.ask(project, "How many goals per match?")["experiment"]
    out = ex.answer(project, eid, "About 3 goals per match", [], [], [])
    failed = {c["check"] for c in out["gate"]["failed"]}
    assert {"its assumptions are stated", "numbers rest on evidence",
            "follow-ups are suggested"} <= failed
    assert ex.get(project, eid)["status"] == "open"


def test_evidence_must_exist(project):
    eid = ex.ask(project, "q")["experiment"]
    out = ex.answer(project, eid, "3 goals", [ROBERT_OWNS],
                    [{"kind": "output", "ref": "out/missing.log"},
                     {"kind": "test", "ref": "no-such-test"}], FOLLOW)
    detail = next(c for c in out["gate"]["failed"]
                  if c["check"] == "every piece of evidence exists")["detail"]
    assert "out/missing.log" in detail and "no-such-test" in detail


def test_answered_experiment_records_everything(project):
    eid = ex.ask(project, "How many goals per match?")["experiment"]
    out = ex.answer(project, eid, "About 3 goals per match, 2 home and 1 away",
                    [ROBERT_OWNS], [{"kind": "output", "ref": "out/match.log"}], FOLLOW)
    assert out["gate"]["passed"]
    assert out["follow_ups"][0].startswith("E001.1: Does a red card")
    rec = ex.get(project, eid)
    assert rec["status"] == "answered" and rec["assumptions"][0]["owner"] == "robert"


def test_sensitive_robert_assumptions_are_flagged_for_the_user(project):
    eid = ex.ask(project, "q")["experiment"]
    sensitive = {**ROBERT_OWNS, "sensitivity": "sensitive"}
    out = ex.answer(project, eid, "It depends on the timing", [sensitive], [], FOLLOW)
    assert any("ask the user" in n for n in out["gate"]["for_your_judgment"])


def test_follow_ups_chain_and_context(project):
    e1 = ex.ask(project, "How many goals?")["experiment"]
    ex.answer(project, e1, "About 3", [ROBERT_OWNS],
              [{"kind": "file", "ref": "out/match.log"}], FOLLOW)
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
    ex.answer(project, e1, "first view", [ROBERT_OWNS], [], FOLLOW)
    e2 = ex.ask(project, "q1 again, with cards", parent=e1)["experiment"]
    ex.answer(project, e2, "revised view", [ROBERT_OWNS], [], FOLLOW, supersedes=e1)
    assert ex.get(project, e1)["status"] == "superseded"
    assert ex.context(project)["answered"][0]["id"] == "E002"
