"""The discovery-and-warrant loop, one function per step.

Pose → Conjecture → Confront → Test → (Discover ↺ | Compress) → Warrant → Query → Revise

Each step writes its method files, runs its gate and returns a compact result: what
was written, which checks failed, what needs the user's judgment, and the step the
method suggests next. Every number comes from a stochadex run.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import __version__, deps
from . import graph as graphs
from .checks import Gate, harness_twice, run_script
from .contracts import (
    INTERVENTION_MODES,
    MODES,
    check_claim,
    check_domain,
    check_partitions,
    check_test_spec,
    is_learned,
    sim_partitions,
)
from .engine import Engine
from .outputs import mean_sd, read
from .project import MethodError, Project, now, sha256_file
from .scaffold import (
    AGENTS_MD,
    GITIGNORE,
    LICENCES_YAML,
    TESTS_YAML,
    devcontainer_json,
    mcp_json,
)

# --- variants -------------------------------------------------------------


def lineage(project: Project) -> dict[str, Any]:
    return project.read_yaml("model/lineage.yaml", {}) or {"current": None, "variants": []}


def variant(project: Project, vid: str | None = None) -> dict[str, Any]:
    lin = lineage(project)
    vid = vid or lin.get("current")
    for v in lin.get("variants", []):
        if v["id"] == vid:
            return v
    raise MethodError(
        f"no variant `{vid}` in model/lineage.yaml" if vid
        else "no model yet: write model/sim.yaml and run `conjecture`"
    )


def _add_variant(project: Project, v: dict[str, Any], make_current: bool) -> None:
    lin = lineage(project)
    if any(x["id"] == v["id"] for x in lin["variants"]):
        raise MethodError(f"variant `{v['id']}` already exists; choose a new id")
    lin["variants"].append(v)
    if make_current:
        lin["current"] = v["id"]
    project.write_yaml("model/lineage.yaml", lin)


def _sim_names(project: Project, config: str) -> list[str]:
    return [p["name"] for p in sim_partitions(project.read_yaml(config, {}))]


def _known_partitions(project: Project) -> set[str]:
    names: set[str] = set()
    for v in lineage(project).get("variants", []):
        if project.exists(v["config"]):
            names |= set(_sim_names(project, v["config"]))
    return names


def _sidecar(project: Project) -> dict[str, Any]:
    return (project.read_yaml("model/partitions.yaml", {}) or {}).get("partitions", {}) or {}


def _done(project: Project, gate: Gate, written: list[str], next_ok: str, next_fail: str,
          **extra: Any) -> dict[str, Any]:
    result = gate.result(next_ok, next_fail)
    project.record_step(gate.step, gate.passed, result["next"])
    return {"step": gate.step, "written": written, **extra, "gate": result}


def _update_sidecar(project: Project, partitions: dict[str, dict[str, Any]] | None) -> None:
    """Revise roles and hypotheses when a step changes what a partition claims."""
    if not partitions:
        return
    side = _sidecar(project)
    for name, entry in partitions.items():
        side[name] = {**side.get(name, {}), **entry, "status": "untested"}
    project.write_yaml("model/partitions.yaml", {"partitions": side})


# --- init -------------------------------------------------------------------


def init(path: str, name: str, description: str, level: str,
         user_knows: list[str], terms: dict[str, str] | None = None,
         git: bool = True) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    if (root / ".robert/project.yaml").exists():
        raise MethodError(f"{root} is already a robert project")
    root.mkdir(parents=True, exist_ok=True)
    project = Project(root)
    engine = Engine(root)
    found = engine.version()
    project.write_yaml(".robert/project.yaml", {
        "name": name,
        "created": now(),
        "robert_version": __version__,
        "skills_version": __version__,
        # The version the project is created against; later runs resolve it first.
        "stochadex_version": found or deps.lock()["version"],
        "steps": {},
    })
    project.write_yaml("domain.yaml", {
        "description": description,
        "level": level,
        "user_knows": user_knows,
        "terms": terms or {},
    })
    files = {
        "AGENTS.md": AGENTS_MD.format(name=name),
        ".mcp.json": mcp_json(),
        ".cursor/mcp.json": mcp_json(),
        ".devcontainer/devcontainer.json": devcontainer_json(),
        ".gitignore": GITIGNORE,
        "tests.yaml": TESTS_YAML,
        "data/licences.yaml": LICENCES_YAML,
        "interventions.yaml": "[]\n",
    }
    for rel, text in files.items():
        p = project.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for d in ("model", "analysis", "learned", "out", "figures", "ledger", "experiments"):
        project.path(d).mkdir(exist_ok=True)
        (project.path(d) / ".gitkeep").touch()
    from .experiments import write_default_standing
    standing_file = write_default_standing(project)
    if git and shutil.which("git") and not (root / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=root, check=False)

    gate = Gate("init")
    gate.all("domain interview complete", check_domain(project.read_yaml("domain.yaml")))
    gate.check("stochadex found", found is not None,
               found or engine.resolved.problem or "")
    if found and found != deps.lock()["version"]:
        gate.note(f"stochadex {found} found; this robert release locks "
                  f"{deps.lock()['version']}")
    return _done(project, gate, [".robert/project.yaml", "domain.yaml", standing_file, *files],
                 "pose", "init", root=str(root))


# --- pose -------------------------------------------------------------------


def pose(project: Project, question: str, claim: str, intended_use: str,
         conditions: list[str], observables: list[str],
         compress_tolerance: float = 0.05, metric_script: str | None = None
         ) -> dict[str, Any]:
    data = {
        "question": question,
        "claim": claim,
        "intended_use": intended_use,
        "conditions": conditions,
        "observables": observables,
        "compress_tolerance": compress_tolerance,
    }
    if metric_script:
        data["metric_script"] = metric_script
    project.write_yaml("claim.yaml", data)
    gate = Gate("pose")
    gate.all("question, claim, intended use and conditions all named", check_claim(data))
    if intended_use in INTERVENTION_MODES:
        gate.note(f"`{intended_use}` is an intervention rung: the model will need process "
                  "validity on every edge from action to outcome before it can be queried")
    return _done(project, gate, ["claim.yaml"], "conjecture", "pose")


# --- conjecture ---------------------------------------------------------------


def conjecture(project: Project, partitions: dict[str, dict[str, Any]],
               rationale: str, config: str = "model/sim.yaml") -> dict[str, Any]:
    """Register the structure the agent wrote in sim.yaml, and gate it."""
    gate = Gate("conjecture")
    if not project.exists(config):
        raise MethodError(f"{config} does not exist; write it with the stochadex-model skill first")
    engine = Engine(project.root)

    side = _sidecar(project)
    for name, entry in partitions.items():
        merged = {**side.get(name, {}), **entry}
        merged.setdefault("status", "untested")
        side[name] = merged
    project.write_yaml("model/partitions.yaml", {"partitions": side})

    checked = engine.check(config)
    gate.check("stochadex --check", checked.ok, "" if checked.ok else checked.summary()["error"])
    if checked.ok:
        ok, detail = harness_twice(project, config)
        gate.check("harness: two runs byte-identical", ok, detail)

    sim = project.read_yaml(config, {})
    names = _sim_names(project, config)
    problems = check_partitions({"partitions": side}, names)
    stale = [p for p in problems if "is not a partition" in p
             and p.split("`")[1] in _known_partitions(project)]
    gate.all("every partition has a role and a hypothesis",
             [p for p in problems if p not in stale])

    claim = project.read_yaml("claim.yaml", {}) or {}
    terms = (project.read_yaml("domain.yaml", {}) or {}).get("terms", {}) or {}
    term_to_name = {v: k for k, v in terms.items()}
    unmapped = [o for o in claim.get("observables", [])
                if o not in names and term_to_name.get(o) not in names]
    gate.check("every claim observable is a partition", not unmapped,
               f"not in the model: {', '.join(unmapped)}" if unmapped else "")

    if checked.ok:
        inputs = [i.get("name") for i in engine.inspect_io(config).get("inputs", [])]
        licences = project.read_yaml("data/licences.yaml", {}) or {}
        missing = [i for i in inputs if i not in licences]
        gate.check("every input has a licence entry", not missing,
                   f"add data/licences.yaml entries for: {', '.join(missing)}" if missing else "")

    learned_structural = [p["name"] for p in sim_partitions(sim)
                          if is_learned(p) and side.get(p["name"], {}).get("role") == "structural"]
    gate.check("no learned structural partition before discover", not learned_structural,
               f"{', '.join(learned_structural)}: try stochadex variants first; a structural "
               "partition becomes learned only through discover" if learned_structural else "")

    written = ["model/partitions.yaml"]
    if gate.passed:
        digest = sha256_file(project.path(config))
        lin = lineage(project)
        last = next((v for v in reversed(lin["variants"]) if v["step"] == "conjecture"), None)
        if last is None or last.get("config_sha") != digest:
            vid = f"v{len(lin['variants'])}"
            _add_variant(project, {
                "id": vid, "parent": lin.get("current"), "step": "conjecture",
                "config": config, "sets": [], "rationale": rationale,
                "config_sha": digest, "at": now(),
            }, make_current=True)
            written.append("model/lineage.yaml")
    return _done(project, gate, written, "confront", "conjecture",
                 graph=graphs.summary(project) if checked.ok else None)


# --- confront -------------------------------------------------------------------


# Relative drift allowed between the last two tenths of an inference run.
CONVERGENCE_TOLERANCE = 0.05


def confront(project: Project, config: str, posterior_partitions: list[str],
             output: str | None = None, sets: list[str] | None = None,
             prior_sd: dict[str, list[float]] | None = None,
             indices: dict[str, list[int]] | None = None,
             convergence_tolerance: float = CONVERGENCE_TOLERANCE) -> dict[str, Any]:
    """Run inference against data and record the resulting parameter beliefs.

    `indices` picks the state slots that hold estimates (a cumulative OLS state also
    carries running sums, which never converge and are not beliefs). The ledger entry
    records how convergence was judged, so an answer resting on a loosened tolerance,
    or on beliefs that never converged, has to say so (see `experiments.answer`).
    """
    gate = Gate("confront")
    gate.check("conjecture gate passed", project.step_passed("conjecture"),
               "run conjecture until its gate passes")
    engine = Engine(project.root)
    r = engine.run(config, sets)
    gate.check("inference run succeeded", r.ok, "" if r.ok else r.summary()["error"])
    if not r.ok:
        return _done(project, gate, [], "test", "confront")

    outs = r.data["outputs"]
    chosen = next((o for o in outs if o["name"] == output), outs[0] if outs else None)
    if chosen is None:
        raise MethodError(f"{config} writes no file output; add a json_log or arrow output")
    series = read(project.path(chosen["path"]))

    posterior: dict[str, Any] = {}
    drifts: dict[str, float] = {}
    for p in posterior_partitions:
        pick = (indices or {}).get(p)
        rows = [[s[i] for i in pick] if pick else s for _, s in series.get(p, [])]
        if len(rows) < 10:
            gate.check(f"`{p}` has enough steps to judge convergence", False,
                       f"{len(rows)} rows in {chosen['path']}")
            continue
        tail, before = rows[-len(rows) // 10:], rows[-2 * (len(rows) // 10):-len(rows) // 10]
        m_tail, sd_tail = mean_sd(tail)
        m_before, _ = mean_sd(before)
        drift = [abs(a - b) / max(abs(a), 1e-9) for a, b in zip(m_tail, m_before)]
        drifts[p] = round(max(drift), 6)
        gate.check(f"`{p}` converged", max(drift) <= convergence_tolerance,
                   f"relative drift over the last 20% of steps: {max(drift):.3g}")
        m, sd = mean_sd(rows[-max(1, len(rows) // 5):])
        posterior[p] = {"mean": m, "sd": sd, **({"indices": pick} if pick else {})}
        for i, s in enumerate((prior_sd or {}).get(p, [])):
            if s > 0 and i < len(sd) and sd[i] / s > 0.5:
                gate.note(f"`{p}`[{i}] is weakly identified: posterior sd is "
                          f"{sd[i] / s:.0%} of the prior sd. Does that matter for the claim?")

    entry = project.append_ledger("beliefs", {
        "kind": "parameters",
        "variant": lineage(project).get("current"),
        "config": config, "sets": sets or [],
        "output": chosen["path"], "provenance_key": chosen["provenance_key"],
        "posterior": posterior,
        "convergence": {"tolerance": convergence_tolerance,
                        "default_tolerance": CONVERGENCE_TOLERANCE,
                        "converged": gate.passed, "drift": drifts},
    })
    return _done(project, gate, ["ledger/beliefs.jsonl", *[o["path"] for o in outs]],
                 "test", "confront", posterior=posterior, ledger_hash=entry["hash"])


# --- test -------------------------------------------------------------------------


def test(project: Project, only: list[str] | None = None) -> dict[str, Any]:
    """Run every check in tests.yaml against the current variant, and set verdicts."""
    gate = Gate("test")
    v = variant(project)
    spec = project.read_yaml("tests.yaml", {}) or {}
    checks = [c for c in (spec.get("checks") or []) if not only or c.get("id") in only]
    gate.check("at least one check is declared", bool(checks),
               "add checks to tests.yaml: backtests, process checks, model-part swaps")
    for c in checks:
        gate.all(f"spec `{c.get('id')}` is well formed", check_test_spec(c))
    if not gate.passed:
        return _done(project, gate, [], "discover", "test")

    engine = Engine(project.root)
    results = spec.get("results") or {}
    for c in checks:
        config = c.get("config", v["config"])
        sets = list(v.get("sets", [])) + list(c.get("sets", []))
        run = engine.run(config, sets)
        if not run.ok:
            results[c["id"]] = {"passed": False, "variant": v["id"], "at": now(),
                                "detail": f"run failed: {run.summary()['error']}"}
            continue
        out = run_script(project, c["script"], config, sets)
        results[c["id"]] = {
            "passed": bool(out.get("passed")),
            "metric": out.get("metric"),
            "detail": out.get("detail", ""),
            "variant": v["id"],
            "provenance_keys": [o["provenance_key"] for o in run.data["outputs"]],
            "at": now(),
        }

    side = _sidecar(project)
    verdicts: dict[str, dict[str, Any]] = {}
    all_checks = spec.get("checks") or []
    for name in _sim_names(project, v["config"]):
        mine = [c for c in all_checks if name in c["partitions"]
                and results.get(c["id"], {}).get("variant") == v["id"]]
        if not mine:
            status = "untested"
        elif any(not results[c["id"]]["passed"] for c in mine):
            status = "failed"
        else:
            status = "passed"
        decided_by = [c["id"] for c in mine if results[c["id"]]["passed"] == (status == "passed")]
        verdicts[name] = {"verdict": status, "decided_by": decided_by}
        if side.get(name, {}).get("status") != "benched":
            side.setdefault(name, {})["status"] = status
    project.write_yaml("tests.yaml", {"checks": all_checks, "results": results,
                                      "verdicts": verdicts})
    project.write_yaml("model/partitions.yaml", {"partitions": side})

    structural = [n for n in verdicts if side.get(n, {}).get("role") == "structural"]
    gate.check("every structural partition has a verdict",
               all(verdicts[n]["verdict"] != "untested" for n in structural),
               ", ".join(n for n in structural if verdicts[n]["verdict"] == "untested"))
    failed = [n for n in structural if verdicts[n]["verdict"] == "failed"]
    gate.check("no structural partition failed", not failed,
               f"failed: {', '.join(failed)}. Localise the misfit and discover" if failed else "")
    kinds = {c["kind"] for c in all_checks if results.get(c["id"], {}).get("variant") == v["id"]}
    gate.check("a backtest or outcome check ran", bool(kinds & {"backtest", "outcome"}))
    after = "warrant" if v["step"] == "compress" else "compress"
    return _done(project, gate, ["tests.yaml", "model/partitions.yaml"],
                 after, "discover", verdicts=verdicts)


# --- discover ---------------------------------------------------------------------


def _score(project: Project, script: str, config: str, sets: list[str]) -> float:
    run = Engine(project.root).run(config, sets)
    if not run.ok:
        raise MethodError(f"scoring run of {config} failed: {run.summary()['error']}")
    out = run_script(project, script, config, sets)
    if "score" not in out:
        raise MethodError(f"score script `{script}` must print {{\"score\": <number>}}")
    return float(out["score"])


def discover(project: Project, id: str, rationale: str, score_script: str,
             partitions_changed: list[str], config: str | None = None,
             sets: list[str] | None = None, parent: str | None = None,
             higher_is_better: bool = True,
             partitions: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Score a structural variant against its parent on held-out prediction.

    `partitions` revises the role and hypothesis of what the variant changes or adds.
    """
    gate = Gate("discover")
    par = variant(project, parent)
    config = config or par["config"]
    sets = list(sets if sets is not None else par.get("sets", []))
    checked = Engine(project.root).check(config, sets)
    gate.check("variant passes stochadex --check", checked.ok,
               "" if checked.ok else checked.summary()["error"])

    # The ladder: a structural partition becomes learned only after stochadex
    # variants for it were tried and failed, and the user approved the switch.
    side = _sidecar(project)
    sim = {p["name"]: p for p in sim_partitions(project.read_yaml(config, {}))}
    for name in partitions_changed:
        if not (sim.get(name) and is_learned(sim[name])):
            continue
        role = side.get(name, {}).get("role")
        if role == "structural":
            tried = [v for v in lineage(project)["variants"]
                     if v["step"] == "discover" and name in v.get("partitions_changed", [])
                     and v.get("evidence", {}).get("verdict") == "rejected"]
            approved = [e for e in (project.read_yaml("interventions.yaml", []) or [])
                        if e.get("step") == "discover" and name in str(e.get("agent_proposal", ""))
                        and e.get("decision") in ("accept", "override")]
            gate.check(f"`{name}`: stochadex variants tried and failed first", bool(tried),
                       "record at least one rejected mechanistic variant for it")
            gate.check(f"`{name}`: user approved the learned component", bool(approved),
                       "log the user's approval with `intervene` (step: discover)")
        elif role == "surrogate":
            ok = any(w.get("variant") for w in project.ledger_entries("warrants"))
            gate.check(f"`{name}`: the component it replaces is warranted", ok)

    evidence: dict[str, Any] = {}
    if checked.ok:
        base = _score(project, score_script, par["config"], par.get("sets", []))
        new = _score(project, score_script, config, sets)
        better = new > base if higher_is_better else new < base
        evidence = {"parent_score": base, "score": new, "score_script": score_script,
                    "verdict": "accepted" if better else "rejected"}
        gate.check("variant beats its parent on held-out prediction", better,
                   f"parent {base:.4g}, variant {new:.4g}")
    _add_variant(project, {
        "id": id, "parent": par["id"], "step": "discover", "config": config, "sets": sets,
        "partitions_changed": partitions_changed, "rationale": rationale,
        "evidence": evidence, "config_sha": sha256_file(project.path(config)), "at": now(),
    }, make_current=gate.passed)
    if gate.passed:
        _update_sidecar(project, partitions)
    return _done(project, gate, ["model/lineage.yaml"], "confront", "discover",
                 current=lineage(project)["current"])


# --- compress ---------------------------------------------------------------------


def compress(project: Project, id: str, rationale: str, removed: list[str],
             config: str | None = None, sets: list[str] | None = None,
             generalisation_script: str | None = None) -> dict[str, Any]:
    """Accept a smaller variant only if the warranted claim does not change."""
    gate = Gate("compress")
    claim = project.read_yaml("claim.yaml", {}) or {}
    par = variant(project)
    config = config or par["config"]
    sets = list(sets if sets is not None else par.get("sets", []))
    gate.check("test gate passed on the parent", project.step_passed("test"),
               "compress only a model whose claim holds")
    metric = claim.get("metric_script")
    gate.check("claim.yaml names a metric_script", bool(metric),
               "compress needs the quantity the claim is about, as a script")
    checked = Engine(project.root).check(config, sets)
    gate.check("variant passes stochadex --check", checked.ok,
               "" if checked.ok else checked.summary()["error"])
    smaller = len(_sim_names(project, config)) < len(_sim_names(project, par["config"])) or (
        set(removed) and set(removed).isdisjoint(_sim_names(project, config)))
    gate.check("variant is smaller than its parent", bool(smaller) or bool(sets != par.get("sets")),
               "remove or merge partitions, or fix sloppy parameters with --set")

    evidence: dict[str, Any] = {}
    if gate.passed:
        tol = float(claim.get("compress_tolerance", 0.05))
        base = _score(project, metric, par["config"], par.get("sets", []))
        new = _score(project, metric, config, sets)
        change = abs(new - base) / max(abs(base), 1e-12)
        evidence = {"parent_metric": base, "metric": new, "relative_change": change,
                    "tolerance": tol}
        gate.check("claim unchanged within tolerance", change <= tol,
                   f"relative change {change:.3g} vs tolerance {tol}")
        if generalisation_script:
            out = run_script(project, generalisation_script, config, sets)
            evidence["generalisation"] = out
            gate.check("generalisation test passes", bool(out.get("passed")), out.get("detail", ""))
        elif claim.get("intended_use") == "design":
            gate.check("generalisation test passes", False,
                       "design use needs a generalisation_script")
        evidence["verdict"] = "accepted" if gate.passed else "rejected"
    _add_variant(project, {
        "id": id, "parent": par["id"], "step": "compress", "config": config, "sets": sets,
        "partitions_changed": removed, "rationale": rationale, "evidence": evidence,
        "config_sha": sha256_file(project.path(config)), "at": now(),
    }, make_current=gate.passed)
    return _done(project, gate, ["model/lineage.yaml"], "test", "warrant",
                 current=lineage(project)["current"])


# --- warrant ------------------------------------------------------------------------


def warrant(project: Project, statement: str, limits: list[str]) -> dict[str, Any]:
    """Commit what is established, for the minimal sufficient model, within limits."""
    gate = Gate("warrant")
    v = variant(project)
    claim = project.read_yaml("claim.yaml", {}) or {}
    results = (project.read_yaml("tests.yaml", {}) or {}).get("results", {}) or {}
    on_variant = [r for r in results.values() if r.get("variant") == v["id"]]
    gate.check("current variant was tested", bool(on_variant),
               f"run `test` on variant {v['id']} first")
    gate.check("all its checks passed", all(r["passed"] for r in on_variant))
    gate.check("limits are stated", bool(limits))
    gate.all("ledger chains intact", project.verify_ledger("beliefs") +
             project.verify_ledger("warrants"))
    written: list[str] = []
    entry = None
    if gate.passed:
        side = _sidecar(project)
        entry = project.append_ledger("warrants", {
            "claim": claim.get("claim"),
            "intended_use": claim.get("intended_use"),
            "statement": statement,
            "limits": limits,
            "variant": v["id"],
            "config": v["config"], "sets": v.get("sets", []),
            "config_sha": sha256_file(project.path(v["config"])),
            "provenance_key": Engine(project.root).provenance_key(v["config"], v.get("sets")),
            "partitions": {n: side.get(n, {}).get("status") for n in
                           _sim_names(project, v["config"])},
            "skills_version": project.meta().get("skills_version"),
        })
        written.append("ledger/warrants.jsonl")
    return _done(project, gate, written, "query", "test",
                 ledger_hash=entry["hash"] if entry else None)


# --- query --------------------------------------------------------------------------


def _passed_kinds(project: Project, vid: str) -> dict[str, set[str]]:
    """partition -> kinds of check that passed on this variant."""
    spec = project.read_yaml("tests.yaml", {}) or {}
    results = spec.get("results") or {}
    kinds: dict[str, set[str]] = {}
    for c in spec.get("checks") or []:
        r = results.get(c["id"], {})
        if r.get("variant") == vid and r.get("passed"):
            for p in c["partitions"]:
                kinds.setdefault(p, set()).add(c["kind"])
    return kinds


def query(project: Project, id: str, mode: str, outcome: str,
          actions: list[str] | None = None, config: str | None = None,
          sets: list[str] | None = None, intervention_sets: list[str] | None = None
          ) -> dict[str, Any]:
    """Run a query only when the warrant reaches its rung."""
    if mode not in MODES:
        raise MethodError(f"mode must be one of {', '.join(MODES)}")
    gate = Gate("query")
    warrants = project.ledger_entries("warrants")
    w = warrants[-1] if warrants else None
    gate.check("a warrant exists", w is not None, "run `warrant` first")
    if w is None:
        return _done(project, gate, [], "query", "warrant")
    v = variant(project, w["variant"])
    config = config or v["config"]
    sets = list(v.get("sets", [])) + list(sets or [])
    g = graphs.load(project, v["config"])
    side = _sidecar(project)
    kinds = _passed_kinds(project, v["id"])
    sim = {p["name"]: p for p in sim_partitions(project.read_yaml(v["config"], {}))}

    if mode in INTERVENTION_MODES:
        gate.check("actions are named", bool(actions), "name the action partitions")
        path = g.path_between(actions or [], outcome)
        gate.check("outcome is downstream of the actions", bool(path),
                   f"no path from {actions} to {outcome}")
    else:
        path = g.ancestors(outcome) | {outcome}
    structural_path = [p for p in path if side.get(p, {}).get("role") == "structural"]

    def needs(kind: str, on: list[str], why: str) -> None:
        missing = [p for p in on if kind not in kinds.get(p, set())]
        gate.check(why, not missing,
                   f"no passed {kind} check on: {', '.join(sorted(missing))}" if missing else "")

    if mode == "forecast":
        needs_any = kinds.get(outcome, set()) & {"backtest", "outcome"}
        gate.check("calibrated outcome validity in the forecast regime", bool(needs_any),
                   f"no passed backtest or outcome check on `{outcome}`")
    if mode == "explain":
        needs("process", structural_path, "process plausibility along the explained path")
    if mode in INTERVENTION_MODES:
        needs("process", sorted(path) if mode == "counterfactual" else structural_path,
              "process validity on the edges from action to outcome")
        swaps = [p for p in structural_path if "swap" in kinds.get(p, set())]
        gate.check("sensitivity across structural variants", bool(swaps),
                   "no passed model-part swap on the path")
        learned = [p for p in path if sim.get(p) and is_learned(sim[p])]
        gate.check("no learned partition on the causal path", not learned,
                   f"learned from observational data: {', '.join(learned)}" if learned else "")
    if mode == "automate":
        rev = project.read_yaml("revise.yaml", {}) or {}
        gate.check("monitors with a rollback are committed",
                   any(m.get("action") == "rollback" for m in rev.get("monitors", [])),
                   "run `revise` with at least one rollback monitor")
    if mode == "design":
        needs("generalisation", structural_path, "generalisation tests beyond the data")
    if mode == "counterfactual":
        gate.check("intervention_sets given for the counterfactual arm", bool(intervention_sets))

    written: list[str] = []
    record: dict[str, Any] = {"id": id, "mode": mode, "outcome": outcome,
                              "actions": actions or [], "warrant": w["hash"],
                              "variant": v["id"], "path": sorted(path), "at": now()}
    if gate.passed:
        engine = Engine(project.root)
        arms = {"factual": sets}
        if mode == "counterfactual":
            arms["counterfactual"] = sets + list(intervention_sets or [])
        record["arms"] = {}
        for arm, arm_sets in arms.items():
            outs = engine.file_outputs(config, arm_sets)
            # Same seeds in both arms: common random numbers make the pair comparable.
            redirect = [f"outputs[name={o['name']}].function.path=out/queries/{id}/{arm}/"
                        f"{Path(o['path']).name}" for o in outs]
            project.path(f"out/queries/{id}/{arm}").mkdir(parents=True, exist_ok=True)
            r = engine.run(config, arm_sets + redirect, skip_if_unchanged=False)
            if not r.ok:
                raise MethodError(f"query run ({arm}) failed: {r.summary()['error']}")
            record["arms"][arm] = r.data["outputs"]
        project.write_yaml(f"queries/{id}.yaml", record)
        written.append(f"queries/{id}.yaml")
    return _done(project, gate, written, "revise", "test", query=record)


# --- revise -------------------------------------------------------------------------


def revise(project: Project, monitors: list[dict[str, Any]],
           value_of_information: list[dict[str, Any]] | None = None,
           new_questions: list[str] | None = None) -> dict[str, Any]:
    """Commit drift monitors and where to look next; these reopen the loop."""
    gate = Gate("revise")
    names = set(_sim_names(project, variant(project)["config"]))
    gate.check("at least one monitor", bool(monitors))
    for m in monitors:
        where = f"monitor `{m.get('name', '?')}`"
        gate.check(f"{where} watches a partition", m.get("partition") in names,
                   f"`{m.get('partition')}` is not in the current model")
        gate.check(f"{where} has a script", bool(m.get("script")) and
                   project.exists(m.get("script", "")))
        gate.check(f"{where} names its action",
                   m.get("action") in ("recalibrate", "reopen", "rollback"),
                   "action: recalibrate, reopen or rollback")
    voi = sorted(value_of_information or [], key=lambda x: -float(x.get("value", 0)))
    project.write_yaml("revise.yaml", {"monitors": monitors, "value_of_information": voi,
                                       "new_questions": new_questions or [], "at": now()})
    return _done(project, gate, ["revise.yaml"], "pose", "revise")
