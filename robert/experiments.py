"""Experiments: the unit the user works with.

The user asks a question; robert answers it with its assumptions stated and its
evidence cited, then suggests follow-ups. Each question and answer is an
experiment, kept in `experiments/E###.yaml`. Experiments link to the experiment
they follow from, and that chain is the context robert loads before taking on a
deeper question. The discovery-and-warrant loop (pose, conjecture, confront,
test, ...) is the machinery robert runs underneath to earn an answer.

Build choices (rates, tolerances, inference method, reference data) are robert's
to make. They are recorded as assumptions on the experiment, owned by robert, and
brought to the user only when a sensitivity check shows the answer depends on one.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .project import MethodError, Project, now

STATUSES = ["open", "answered", "superseded"]
ASKERS = ["user", "robert"]
OWNERS = ["user", "robert"]
SENSITIVITY = ["untested", "insensitive", "sensitive"]
EVIDENCE_KINDS = ["output", "ledger", "test", "query", "figure", "file"]
FOLLOW_UP_KINDS = ["deepen", "test-assumption", "broaden", "alternative"]


def _dir(project: Project) -> Path:
    return project.path("experiments")


def _path(project: Project, eid: str) -> Path:
    return _dir(project) / f"{eid}.yaml"


def all_experiments(project: Project) -> list[dict[str, Any]]:
    d = _dir(project)
    if not d.is_dir():
        return []
    return [project.read_yaml(f"experiments/{p.name}") for p in sorted(d.glob("E*.yaml"))]


def get(project: Project, eid: str) -> dict[str, Any]:
    if not _path(project, eid).exists():
        raise MethodError(f"no experiment `{eid}`")
    return project.read_yaml(f"experiments/{eid}.yaml")


def _save(project: Project, exp: dict[str, Any]) -> str:
    rel = f"experiments/{exp['id']}.yaml"
    project.write_yaml(rel, exp)
    return rel


def _next_id(project: Project) -> str:
    nums = [int(e["id"][1:]) for e in all_experiments(project)]
    return f"E{(max(nums) + 1) if nums else 1:03d}"


def chain(project: Project, eid: str) -> list[dict[str, Any]]:
    """The experiment and every experiment it follows from, oldest first."""
    out = []
    seen = set()
    cur: str | None = eid
    while cur and cur not in seen:
        seen.add(cur)
        exp = get(project, cur)
        out.append(exp)
        cur = exp.get("parent")
    return list(reversed(out))


# --- ask -------------------------------------------------------------------------------


def ask(project: Project, question: str = "", asked_by: str = "user",
        parent: str | None = None, from_follow_up: str | None = None) -> dict[str, Any]:
    """Open an experiment for a question, and return the context to answer it with.

    `from_follow_up` takes `E002.1` (the first follow-up E002 suggested): the new
    experiment then follows from E002 and records which suggestion it took up.
    """
    if asked_by not in ASKERS:
        raise MethodError(f"asked_by must be one of {', '.join(ASKERS)}")
    origin = None
    if from_follow_up:
        m = re.fullmatch(r"(E\d+)\.(\d+)", from_follow_up)
        if not m:
            raise MethodError("from_follow_up looks like E002.1")
        src = get(project, m.group(1))
        ups = src.get("follow_ups") or []
        k = int(m.group(2))
        if not 1 <= k <= len(ups):
            raise MethodError(f"{m.group(1)} has {len(ups)} follow-ups")
        parent = parent or src["id"]
        origin = from_follow_up
        question = question or ups[k - 1]["question"]
    if not question:
        raise MethodError("a question is needed")
    if parent:
        get(project, parent)
    exp = {
        "id": _next_id(project),
        "question": question,
        "asked_by": asked_by,
        "parent": parent,
        "from_follow_up": origin,
        "status": "open",
        "asked_at": now(),
        "answer": None,
        "assumptions": [],
        "evidence": [],
        "follow_ups": [],
    }
    rel = _save(project, exp)
    return {"experiment": exp["id"], "written": [rel],
            "context": context(project, focus=exp["id"])}


# --- answer ----------------------------------------------------------------------------


def _check_evidence(project: Project, ev: dict[str, Any]) -> str | None:
    kind, ref = ev.get("kind"), str(ev.get("ref", ""))
    if kind not in EVIDENCE_KINDS:
        return f"evidence kind must be one of {', '.join(EVIDENCE_KINDS)}"
    if not ref:
        return "evidence needs a ref"
    if kind == "output":
        if not ref.startswith("out/") or not project.exists(ref):
            return f"`{ref}` is not a run output in out/"
        if not project.exists(ref + ".provenance.json"):
            return f"`{ref}` has no provenance sidecar; produce it with `robert run`"
    elif kind == "ledger":
        hashes = {e["hash"] for n in ("beliefs", "warrants") for e in project.ledger_entries(n)}
        if ref not in hashes:
            return f"no ledger entry with hash `{ref}`"
    elif kind == "test":
        results = (project.read_yaml("tests.yaml", {}) or {}).get("results") or {}
        if ref not in results:
            return f"no test result `{ref}` in tests.yaml"
    elif kind == "query":
        if not project.exists(f"queries/{ref}.yaml"):
            return f"no query `{ref}`"
    elif not project.exists(ref):
        return f"`{ref}` does not exist"
    return None


def answer(project: Project, experiment: str, answer: str,
           assumptions: list[dict[str, Any]], evidence: list[dict[str, Any]],
           follow_ups: list[dict[str, Any]], supersedes: str | None = None
           ) -> dict[str, Any]:
    """Record robert's answer. The gate: every assumption is stated and owned,
    every number rests on cited evidence that exists, and the answer suggests
    where to go next."""
    from .checks import Gate

    exp = get(project, experiment)
    gate = Gate("answer")
    gate.check("the answer is stated", bool(answer and answer.strip()))
    gate.check("its assumptions are stated", bool(assumptions),
               "state what the answer assumes, including robert's own build choices")
    bad_a = [a for a in assumptions if not a.get("assumption")
             or a.get("owner") not in OWNERS
             or a.get("sensitivity", "untested") not in SENSITIVITY]
    gate.check("each assumption has an owner and a sensitivity", not bad_a,
               f"owner in {OWNERS}, sensitivity in {SENSITIVITY}" if bad_a else "")
    problems = [p for p in (_check_evidence(project, e) for e in evidence) if p]
    gate.all("every piece of evidence exists", problems)
    has_numbers = bool(re.search(r"\d", answer or ""))
    gate.check("numbers rest on evidence", not has_numbers or bool(evidence),
               "an answer with numbers must cite the outputs, tests or ledger entries "
               "they come from")
    gate.check("follow-ups are suggested", bool(follow_ups),
               "suggest at least one question to ask next")
    bad_f = [f for f in follow_ups if not f.get("question")
             or f.get("kind", "deepen") not in FOLLOW_UP_KINDS]
    gate.check("each follow-up is a question with a kind", not bad_f,
               f"kind in {FOLLOW_UP_KINDS}" if bad_f else "")
    sensitive_robert = [a["assumption"] for a in assumptions
                        if a.get("owner") == "robert" and a.get("sensitivity") == "sensitive"]
    if sensitive_robert:
        gate.note("the answer depends on choices robert made; ask the user what they "
                  "believe about: " + "; ".join(sensitive_robert))

    written: list[str] = []
    if gate.passed:
        if supersedes:
            old = get(project, supersedes)
            old["status"] = "superseded"
            old["superseded_by"] = experiment
            written.append(_save(project, old))
        lin = (project.read_yaml("model/lineage.yaml", {}) or {})
        warrants = project.ledger_entries("warrants")
        exp.update({
            "status": "answered",
            "answered_at": now(),
            "answer": answer.strip(),
            "assumptions": [{"assumption": a["assumption"], "owner": a["owner"],
                             "sensitivity": a.get("sensitivity", "untested"),
                             **({"why": a["why"]} if a.get("why") else {})}
                            for a in assumptions],
            "evidence": evidence,
            "follow_ups": [{"question": f["question"], "kind": f.get("kind", "deepen"),
                            **({"why": f["why"]} if f.get("why") else {})}
                           for f in follow_ups],
            "model_variant": lin.get("current"),
            "warrant": warrants[-1]["hash"] if warrants else None,
            **({"supersedes": supersedes} if supersedes else {}),
        })
        written.insert(0, _save(project, exp))
    result = gate.result("ask", "answer")
    return {"experiment": experiment, "written": written,
            "follow_ups": [f"{experiment}.{i}: {f['question']}"
                           for i, f in enumerate(follow_ups, 1)] if gate.passed else [],
            "gate": result}


# --- context -----------------------------------------------------------------------------


def _brief(exp: dict[str, Any], full: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"id": exp["id"], "question": exp["question"],
                           "status": exp["status"]}
    if exp.get("parent"):
        out["follows"] = exp["parent"]
    if exp.get("answer"):
        out["answer"] = exp["answer"] if full else exp["answer"][:280]
    if full:
        out["assumptions"] = exp.get("assumptions", [])
        out["evidence"] = exp.get("evidence", [])
    else:
        live = [a["assumption"] for a in exp.get("assumptions", [])
                if a.get("sensitivity") != "insensitive"]
        if live:
            out["live_assumptions"] = live
    return out


def context(project: Project, focus: str | None = None) -> dict[str, Any]:
    """What robert knows so far, compressed: answered questions and their live
    assumptions, open questions, and suggestions not yet taken up. With `focus`,
    the chain that experiment follows from is given in full."""
    exps = all_experiments(project)
    taken = {e.get("from_follow_up") for e in exps if e.get("from_follow_up")}
    focus_chain = {e["id"] for e in chain(project, focus)} if focus else set()
    claim = project.read_yaml("claim.yaml", {}) or {}
    warrants = project.ledger_entries("warrants")
    return {
        "claim": claim.get("claim"),
        "warranted": warrants[-1]["statement"] if warrants else None,
        "focus_chain": [_brief(e, True) for e in exps if e["id"] in focus_chain],
        "answered": [_brief(e, False) for e in exps
                     if e["status"] == "answered" and e["id"] not in focus_chain],
        "open": [e["id"] + ": " + e["question"] for e in exps
                 if e["status"] == "open" and e["id"] != focus],
        "suggested": [f"{e['id']}.{i}: {f['question']}"
                      for e in exps if e["status"] == "answered"
                      for i, f in enumerate(e.get("follow_ups") or [], 1)
                      if f"{e['id']}.{i}" not in taken],
    }
