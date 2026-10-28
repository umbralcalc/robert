"""Contracts for the method files.

Each method file has one job and a validator that says, in plain words, what is
missing. Nothing here describes the model itself: structure and wiring live only in
model/sim.yaml, which stochadex validates. These files hold what stochadex does not
encode: the claim, the user's domain terms, and the role, hypothesis and evidence
behind each partition.
"""

from __future__ import annotations

from typing import Any

# Query modes, in order of the warrant they need (Pearl's ladder, plus deployment).
MODES = ["explain", "forecast", "decide", "automate", "design", "counterfactual"]
INTERVENTION_MODES = {"decide", "automate", "design", "counterfactual"}

ROLES = ["structural", "nuisance", "surrogate"]
STATUSES = ["untested", "passed", "failed", "benched"]
TEST_KINDS = ["backtest", "process", "swap", "generalisation", "outcome"]
LINEAGE_STEPS = ["conjecture", "discover", "compress", "swap"]
ACTORS = ["user", "standin"]
DECISIONS = ["accept", "override", "redirect", "bench"]

# iteration types that make a partition "learned" rather than mechanistic.
LEARNED_TYPES = {"onnx_inference"}


def _missing(d: dict[str, Any], keys: list[str], where: str) -> list[str]:
    out = []
    for k in keys:
        v = d.get(k)
        if v is None or (isinstance(v, (str, list, dict)) and not v):
            out.append(f"{where}: `{k}` is not named")
    return out


def check_domain(d: dict[str, Any]) -> list[str]:
    problems = _missing(d, ["description", "user_knows"], "domain.yaml")
    if d.get("level") not in ("novice", "practitioner", "expert"):
        problems.append("domain.yaml: `level` must be novice, practitioner or expert")
    return problems


def check_claim(c: dict[str, Any]) -> list[str]:
    problems = _missing(
        c, ["question", "claim", "intended_use", "conditions", "observables"], "claim.yaml"
    )
    if c.get("intended_use") and c["intended_use"] not in MODES:
        problems.append(f"claim.yaml: `intended_use` must be one of {', '.join(MODES)}")
    tol = c.get("compress_tolerance")
    if tol is not None and not (isinstance(tol, (int, float)) and tol >= 0):
        problems.append("claim.yaml: `compress_tolerance` must be a non-negative number")
    return problems


def check_partitions(sidecar: dict[str, Any], sim_names: list[str]) -> list[str]:
    """One entry per partition in sim.yaml, and no others."""
    entries = sidecar.get("partitions", {}) or {}
    problems = []
    for name in sim_names:
        if name not in entries:
            problems.append(f"partitions.yaml: `{name}` is in sim.yaml but has no entry")
            continue
        e = entries[name] or {}
        if e.get("role") not in ROLES:
            problems.append(f"partitions.yaml: `{name}` needs a role ({', '.join(ROLES)})")
        if not e.get("hypothesis"):
            problems.append(f"partitions.yaml: `{name}` needs a one-line hypothesis")
        if e.get("status", "untested") not in STATUSES:
            problems.append(f"partitions.yaml: `{name}` status must be one of {STATUSES}")
    for name in entries:
        if name not in sim_names:
            problems.append(f"partitions.yaml: `{name}` is not a partition in sim.yaml")
    return problems


def check_test_spec(t: dict[str, Any]) -> list[str]:
    where = f"tests.yaml check `{t.get('id', '?')}`"
    problems = _missing(t, ["id", "partitions", "kind", "script"], where)
    if t.get("kind") and t["kind"] not in TEST_KINDS:
        problems.append(f"{where}: kind must be one of {', '.join(TEST_KINDS)}")
    if t.get("kind") == "backtest":
        te, ts = t.get("train_end"), t.get("test_start")
        if te is None or ts is None:
            problems.append(f"{where}: a backtest names train_end and test_start")
        elif not ts > te:
            problems.append(f"{where}: test_start must come after train_end (leakage)")
    return problems


def check_intervention(e: dict[str, Any]) -> list[str]:
    problems = _missing(e, ["step", "actor", "agent_proposal", "decision", "reason"],
                        "intervention")
    if e.get("actor") and e["actor"] not in ACTORS:
        problems.append(f"intervention: actor must be one of {', '.join(ACTORS)}")
    if e.get("decision") and e["decision"] not in DECISIONS:
        problems.append(f"intervention: decision must be one of {', '.join(DECISIONS)}")
    return problems


def sim_partitions(sim: dict[str, Any]) -> list[dict[str, Any]]:
    return list(((sim or {}).get("main") or {}).get("partitions") or [])


def is_learned(partition: dict[str, Any]) -> bool:
    it = partition.get("iteration") or {}
    return isinstance(it, dict) and it.get("type") in LEARNED_TYPES
