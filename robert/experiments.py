"""Experiments: the unit the user works with.

The user asks a question; robert answers it with its assumptions stated and its
evidence cited, then suggests follow-ups. Each question and answer is an
experiment, kept in `experiments/E###.yaml`. Experiments link to the experiment
they follow from, and that chain is the context robert loads before taking on a
deeper question. The discovery-and-warrant loop (pose, conjecture, confront,
test, ...) is the machinery robert runs underneath to earn an answer.

Every assumption has a kind. Implementation choices (step sizes, inference
method, seeds) are robert's and only recorded. Operationalisation choices (which
metric defines the claim, what tolerance counts, what data is excluded) change what
a result means: robert makes a provisional one and states it in the answer, where
the user can contest it. Beliefs about the world are the user's to hold; robert asks
about one only when an answer depends on it.

Two things guard against confirmation bias, the main risk when the user's questions
steer the search. Every answer states the strongest evidence or argument against
itself, and lists every analysis tried, not just the one reported. And the project's
standing questions (`standing.yaml`), posed once and answered in every answer, are
the channel for what nobody thought to ask about: contradictions, surprises,
operationalisation choices, anything that would flip a warranted claim.
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
CHOICE_KINDS = ["implementation", "operationalisation", "belief"]
EVIDENCE_KINDS = ["output", "ledger", "test", "query", "figure", "file"]
FOLLOW_UP_KINDS = ["deepen", "test-assumption", "broaden", "alternative"]
VALUES = ["high", "medium", "low"]
NOTHING = "nothing to report"

# Posed once at init; the user can add their own with `standing`.
DEFAULT_STANDING = [
    "What contradicts or weakens any current answer?",
    "What behaved differently from what the model or the user expected?",
    "Which operationalisation choice did you make that changes what a result means?",
    "What would flip a warranted claim, or the answer to an earlier experiment?",
]


# --- standing questions -------------------------------------------------------------------


def standing_questions(project: Project) -> list[dict[str, Any]]:
    return (project.read_yaml("standing.yaml", {}) or {}).get("questions") or []


def write_default_standing(project: Project) -> str:
    project.write_yaml("standing.yaml", {"questions": [
        {"id": f"S{i}", "question": q, "set_by": "default"}
        for i, q in enumerate(DEFAULT_STANDING, 1)]})
    return "standing.yaml"


def standing(project: Project, add: list[str] | None = None,
             retire: list[str] | None = None) -> dict[str, Any]:
    """List the standing questions, add the user's own, or retire one. Every answer
    must report against each live standing question."""
    qs = standing_questions(project)
    written: list[str] = []
    if add or retire:
        known = {q["id"] for q in qs}
        unknown = sorted(set(retire or []) - known)
        if unknown:
            raise MethodError(f"no standing question {', '.join(unknown)}")
        for q in qs:
            if q["id"] in (retire or []):
                q["retired"] = now()
        n = max([int(q["id"][1:]) for q in qs] or [0])
        for i, text in enumerate(add or [], 1):
            qs.append({"id": f"S{n + i}", "question": text, "set_by": "user", "at": now()})
        project.write_yaml("standing.yaml", {"questions": qs})
        written.append("standing.yaml")
    return {"written": written,
            "standing": [f"{q['id']}: {q['question']}" for q in qs if not q.get("retired")]}


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


def _convergence_owed(project: Project, evidence: list[dict[str, Any]]) -> dict[str, str]:
    """Beliefs the answer rests on that were judged loosely or never converged.

    These are the beliefs cited as evidence plus the latest for the current variant,
    which is what the model runs with. Returns ledger hash -> what is owed.
    """
    entries = project.ledger_entries("beliefs")
    cited = {e.get("ref") for e in evidence if e.get("kind") == "ledger"}
    current = (project.read_yaml("model/lineage.yaml", {}) or {}).get("current")
    latest = [e for e in entries if e.get("variant") == current][-1:]
    owed = {}
    for e in [x for x in entries if x["hash"] in cited] + latest:
        c = e.get("convergence") or {}
        if c.get("converged") is False:
            owed[e["hash"]] = "these beliefs did not converge"
        elif c.get("tolerance", 0) > c.get("default_tolerance", float("inf")):
            owed[e["hash"]] = (f"convergence was judged at tolerance {c['tolerance']}, "
                               f"looser than the default {c['default_tolerance']}")
    return owed


def answer(project: Project, experiment: str, answer: str,
           assumptions: list[dict[str, Any]], evidence: list[dict[str, Any]],
           against: list[dict[str, Any]], follow_ups: list[dict[str, Any]],
           reports: list[dict[str, Any]] | None = None,
           tried: list[dict[str, Any]] | None = None,
           hypotheses: list[str] | None = None,
           supersedes: str | None = None) -> dict[str, Any]:
    """Record robert's answer. The gate: every assumption is stated, owned and of a
    kind; every number rests on cited evidence that exists; the strongest case
    against the answer is stated; every standing question gets a report; and the
    follow-ups say which explanations they would tell apart."""
    from .checks import Gate

    exp = get(project, experiment)
    tried, reports, hypotheses = tried or [], reports or [], hypotheses or []
    gate = Gate("answer")
    gate.check("the answer is stated", bool(answer and answer.strip()))

    gate.check("its assumptions are stated", bool(assumptions),
               "state what the answer assumes, including robert's own choices")
    bad_a = [a for a in assumptions if not a.get("assumption")
             or a.get("owner") not in OWNERS
             or a.get("kind") not in CHOICE_KINDS
             or a.get("sensitivity", "untested") not in SENSITIVITY]
    gate.check("each assumption has an owner, a kind and a sensitivity", not bad_a,
               f"owner in {OWNERS}, kind in {CHOICE_KINDS}, sensitivity in {SENSITIVITY}"
               if bad_a else "")

    problems = [p for p in (_check_evidence(project, e) for e in evidence) if p]
    problems += [p for p in (_check_evidence(project, a) for a in against if a.get("ref"))
                 if p]
    gate.all("every piece of evidence exists", problems)
    has_numbers = bool(re.search(r"\d", answer or ""))
    gate.check("numbers rest on evidence", not has_numbers or bool(evidence),
               "an answer with numbers must cite the outputs, tests or ledger entries "
               "they come from")

    owed = _convergence_owed(project, evidence)
    stated = {a.get("ref") for a in assumptions if a.get("assumption")}
    unstated = [f"{h[:12]}: {why}" for h, why in owed.items() if h not in stated]
    gate.check("loosened or unconverged beliefs are stated as assumptions", not unstated,
               "add an assumption with `ref` set to each ledger hash, saying why the answer "
               "can rest on it: " + "; ".join(unstated) if unstated else "")

    gate.check("the strongest case against is stated",
               bool(against) and all(a.get("point") for a in against),
               "state the strongest evidence or argument against the answer, or what "
               "result would refute it")
    bad_t = [x for x in tried if not x.get("analysis") or not x.get("outcome")]
    gate.check("each analysis tried says what happened", not bad_t,
               "every analysis tried, kept or not, with its outcome" if bad_t else "")

    live = [q for q in standing_questions(project) if not q.get("retired")]
    answered = {r.get("standing") for r in reports if r.get("report")}
    missing = [q["id"] for q in live if q["id"] not in answered]
    gate.check("every standing question has a report", not missing,
               f"report on {', '.join(missing)} (\"{NOTHING}\" is a report)"
               if missing else "")

    gate.check("follow-ups are suggested", bool(follow_ups),
               "suggest at least one question to ask next")
    bad_f = [f for f in follow_ups if not f.get("question")
             or f.get("kind", "deepen") not in FOLLOW_UP_KINDS
             or f.get("value", "medium") not in VALUES]
    gate.check("each follow-up is a question with a kind and a value", not bad_f,
               f"kind in {FOLLOW_UP_KINDS}, value in {VALUES}" if bad_f else "")
    gate.check("a follow-up names the explanations it would tell apart",
               any(len(f.get("discriminates") or []) >= 2 for f in follow_ups),
               "give at least one follow-up `discriminates`: two or more competing "
               "explanations its result would separate")

    contestable = [a["assumption"] for a in assumptions
                   if a.get("owner") == "robert" and a.get("kind") == "operationalisation"]
    if contestable:
        gate.note("state these operationalisation choices in the reply, where the user "
                  "can contest them: " + "; ".join(contestable))
    beliefs = [a["assumption"] for a in assumptions
               if a.get("owner") == "robert" and a.get("kind") == "belief"
               and a.get("sensitivity") == "sensitive"]
    if beliefs:
        gate.note("the answer depends on beliefs robert assumed; ask the user what they "
                  "believe about: " + "; ".join(beliefs))

    written: list[str] = []
    ranked = sorted(follow_ups, key=lambda f: VALUES.index(f.get("value", "medium")))
    if gate.passed:
        if supersedes:
            old = get(project, supersedes)
            old["status"] = "superseded"
            old["superseded_by"] = experiment
            written.append(_save(project, old))
        lin = (project.read_yaml("model/lineage.yaml", {}) or {})
        warrants = project.ledger_entries("warrants")
        keep = lambda d, keys: {k: d[k] for k in keys if d.get(k) not in (None, "", [])}
        exp.update({
            "status": "answered",
            "answered_at": now(),
            "answer": answer.strip(),
            "hypotheses": hypotheses,
            "assumptions": [{**keep(a, ["assumption", "owner", "kind", "why", "ref"]),
                             "sensitivity": a.get("sensitivity", "untested")}
                            for a in assumptions],
            "evidence": evidence,
            "against": [keep(a, ["point", "kind", "ref"]) for a in against],
            "tried": [keep(x, ["analysis", "outcome", "ref"]) for x in tried],
            "reports": [keep(r, ["standing", "report"]) for r in reports],
            "follow_ups": [{**keep(f, ["question", "why", "discriminates"]),
                            "kind": f.get("kind", "deepen"),
                            "value": f.get("value", "medium")} for f in ranked],
            "model_variant": lin.get("current"),
            "warrant": warrants[-1]["hash"] if warrants else None,
            **({"supersedes": supersedes} if supersedes else {}),
        })
        written.insert(0, _save(project, exp))
    result = gate.result("ask", "answer")
    return {"experiment": experiment, "written": written,
            "follow_ups": [f"{experiment}.{i}: {f['question']}"
                           for i, f in enumerate(ranked, 1)] if gate.passed else [],
            "gate": result}


def reported(exp: dict[str, Any]) -> list[str]:
    """The standing-question reports that say something."""
    return [f"{r['standing']}: {r['report']}" for r in exp.get("reports") or []
            if r.get("report", "").strip().lower().rstrip(".") != NOTHING]


# --- context -----------------------------------------------------------------------------


def _brief(exp: dict[str, Any], full: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"id": exp["id"], "question": exp["question"],
                           "status": exp["status"]}
    if exp.get("parent"):
        out["follows"] = exp["parent"]
    if exp.get("answer"):
        out["answer"] = exp["answer"] if full else exp["answer"][:280]
    if exp.get("hypotheses"):
        out["hypotheses"] = exp["hypotheses"]
    if reported(exp):
        out["reports"] = reported(exp)
    if full:
        for key in ("assumptions", "evidence", "against", "tried"):
            out[key] = exp.get(key, [])
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
        "standing": [f"{q['id']}: {q['question']}" for q in standing_questions(project)
                     if not q.get("retired")],
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
