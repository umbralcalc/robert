"""Supporting commands: catalogue, run, graph, plot, status, explain, intervene, doctor."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

from . import __version__, deps
from . import graph as graphs
from .contracts import check_intervention, expression_partitions
from .engine import Engine
from .loop import _sim_names, lineage, variant
from .outputs import read, svg_lines
from .project import LOOP, MethodError, Project, now


def run(project: Project, config: str | None = None, sets: list[str] | None = None,
        force: bool = False) -> dict[str, Any]:
    """Run the current variant (or a named config) with provenance."""
    if config is None:
        v = variant(project)
        config, base = v["config"], list(v.get("sets", []))
    else:
        base = []
    r = Engine(project.root).run(config, base + list(sets or []), skip_if_unchanged=not force)
    return {"config": config, **r.summary()}


def _words(entry: dict[str, Any]) -> tuple[set[str], set[str]]:
    """A component's name, and everything else that describes it, as words."""
    rest = [entry.get("description", "")]
    for p in entry.get("params", []):
        rest.append(p["name"])
    for f in entry.get("fields", []):
        rest.append(f["name"])
        rest += [c["name"] + " " + c.get("description", "") for c in f.get("choices", [])]
        rest += [p["name"] for c in f.get("choices", []) for p in c.get("params", [])]
        rest += [sub["name"] for sub in f.get("fields", [])]
    def split(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", text.replace("_", " ").lower()))
    return split(entry["name"]), split(" ".join(rest))


def _has(words: set[str], term: str) -> bool:
    return any(w.startswith(term) for w in words)


def _brief(entry: dict[str, Any]) -> dict[str, Any]:
    """A component as the catalogue states it, nested spec fields cut to their names."""
    out = {k: entry[k] for k in ("description", "params", "params_incomplete") if k in entry}
    if entry.get("fields"):
        out["fields"] = [{k: (v if k != "fields" else [s["name"] for s in v])
                          for k, v in f.items()} for f in entry["fields"]]
    return out


def catalogue(search: list[str] | None = None, kinds: list[str] | None = None,
              limit: int = 12, project: str | None = None) -> dict[str, Any]:
    """Search what the build registers before writing an expression.

    Every search term is matched against each component's name, description, params,
    fields and named-function choices; components are ranked by how many terms they
    match, then by how many of those are in the name. A term matches a word it begins,
    so `count` finds "counting" and `rate` finds `rates`.
    """
    try:
        root = Project.find(project).root
    except MethodError:
        root = Path(project or ".").resolve()
    cat = Engine(root).catalogue()
    sections = {k: v for k, v in cat.items() if isinstance(v, list)
                and (not kinds or k in kinds) and all(isinstance(e, dict) for e in v)}
    out: dict[str, Any] = {"catalogue_version": cat.get("catalogue_version", 1),
                           "stochadex": cat.get("version")}
    if not search:
        out["names"] = {k: [e["name"] for e in v] for k, v in sections.items()}
        return out
    terms = [w for t in search for w in re.findall(r"[a-z0-9]+", t.replace("_", " ").lower())]
    hits = []
    for kind, entries in sections.items():
        for e in entries:
            if e["name"] == "expression":
                continue  # the thing a search is meant to avoid
            name, rest = _words(e)
            in_name = sum(_has(name, t) for t in terms)
            matched = sum(_has(name, t) or _has(rest, t) for t in terms)
            if matched:
                hits.append((-matched, -in_name, kind, e))
    hits.sort(key=lambda h: h[:3] + (h[3]["name"],))
    out["matches"] = [{"kind": kind, "name": e["name"], "matched": -m, **_brief(e)}
                      for m, _, kind, e in hits[:limit]]
    out["next"] = ("chain built-ins through params_from_upstream before writing an "
                   "expression; if none fits, record why_expression for that partition")
    return out


def graph(project: Project, overlay: str | None = None, query: str | None = None,
          fmt: str = "mermaid") -> dict[str, Any]:
    """Render the partition graph with one overlay into figures/."""
    if overlay == "lineage":
        text = graphs.lineage_strip(project)
    else:
        highlight = None
        cfg = "model/sim.yaml"
        if overlay in ("warrant", "query"):
            warrants = project.ledger_entries("warrants")
            if not warrants:
                raise MethodError("nothing is warranted yet")
            v = variant(project, warrants[-1]["variant"])
            cfg = v["config"]
            if overlay == "query":
                if not query:
                    raise MethodError("the query overlay needs a query id")
                highlight = set(project.read_yaml(f"queries/{query}.yaml", {}).get("path", []))
            else:
                highlight = set(warrants[-1]["partitions"])
        else:
            try:
                cfg = variant(project)["config"]
            except MethodError:
                pass
        if fmt == "dot":
            return {"dot": Engine(project.root).graph(cfg, "dot").stdout}
        text = graphs.mermaid(project, overlay, cfg, highlight)
    name = f"figures/graph-{overlay or 'structure'}{'-' + query if query else ''}.mmd"
    project.path(name).parent.mkdir(exist_ok=True)
    project.path(name).write_text(text)
    return {"written": [name], "mermaid": text}


def plot(project: Project, output: str, partitions: list[str], claim_part: str,
         title: str | None = None) -> dict[str, Any]:
    """Draw a chart from a stochadex output. Never a plot without a claim."""
    claim = project.read_yaml("claim.yaml", {}) or {}
    if claim_part not in claim:
        raise MethodError(f"`{claim_part}` is not a field of claim.yaml; every figure names "
                          f"the part of the claim it bears on ({', '.join(claim)})")
    path = project.path(output)
    if not path.exists():
        raise MethodError(f"{output} does not exist; run first")
    terms = (project.read_yaml("domain.yaml", {}) or {}).get("terms", {}) or {}
    series = {terms.get(k, k): v for k, v in read(path).items()}
    names = [terms.get(p, p) for p in partitions]
    caption = f"Bears on claim.{claim_part}: {str(claim[claim_part])[:90]}"
    svg = svg_lines(series, names, title or ", ".join(names), caption)
    stem = path.name.split(".")[0]
    name = f"figures/{stem}-{'-'.join(partitions)}.svg"
    project.path(name).write_text(svg)
    return {"written": [name], "source": output}


def status(project: Project) -> dict[str, Any]:
    """Where the loop stands, compressed to what needs attention."""
    meta = project.meta()
    steps = meta.get("steps", {})
    last = meta.get("last") or {"next": "pose"}
    side = (project.read_yaml("model/partitions.yaml", {}) or {}).get("partitions", {}) or {}
    lin = lineage(project)
    try:
        sim = project.read_yaml(variant(project)["config"], {})
        in_model = set(_sim_names(project, variant(project)["config"]))
    except MethodError:
        sim, in_model = {}, set(side)
    by_status: dict[str, list[str]] = {}
    for n, e in side.items():
        by_status.setdefault(e.get("status", "untested") if n in in_model else "retired",
                             []).append(n)
    ints = project.read_yaml("interventions.yaml", []) or []
    return {
        "project": meta.get("name"),
        "last_step": {k: last[k] for k in ("step", "passed") if k in last},
        "next_step": last["next"],
        "steps": {s: ("passed" if steps[s]["passed"] else "failed") for s in LOOP if s in steps},
        "current_variant": lin.get("current"),
        "variants": len(lin.get("variants", [])),
        "partitions": by_status,
        # Built-ins first: how many of the current model's partitions are expressions.
        "expression_partitions": {"count": len(expression_partitions(sim)),
                                  "of": len(in_model)},
        "warrants": len(project.ledger_entries("warrants")),
        "experiments": _experiment_counts(project),
        "interventions": len(ints),
        "versions": {k: meta.get(k) for k in ("robert_version", "skills_version",
                                              "stochadex_version")},
    }


def _experiment_counts(project: Project) -> dict[str, int]:
    from .experiments import all_experiments
    counts: dict[str, int] = {}
    for e in all_experiments(project):
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    return counts


def explain(project: Project, artefact: str) -> dict[str, Any]:
    """Compress one artefact to the user's domain terms and level."""
    domain = project.read_yaml("domain.yaml", {}) or {}
    terms = domain.get("terms", {}) or {}

    def t(n: str) -> str:
        return terms.get(n, n)

    if artefact == "claim":
        c = project.read_yaml("claim.yaml", {}) or {}
        return {"summary": f"Claim: {c.get('claim')} Used to {c.get('intended_use')}, "
                           f"holding under: {'; '.join(c.get('conditions', []))}."}
    if artefact == "partitions":
        side = (project.read_yaml("model/partitions.yaml", {}) or {}).get("partitions", {})
        return {"summary": [f"{t(n)} ({e.get('role')}, {e.get('status')}): {e.get('hypothesis')}"
                            for n, e in side.items()]}
    if artefact == "tests":
        v = (project.read_yaml("tests.yaml", {}) or {}).get("verdicts", {}) or {}
        held = [t(n) for n, x in v.items() if x["verdict"] == "passed"]
        broke = [t(n) for n, x in v.items() if x["verdict"] == "failed"]
        untested = [t(n) for n, x in v.items() if x["verdict"] == "untested"]
        return {"summary": f"{len(held)} of {len(v)} mechanisms hold."
                           + (f" Failed: {', '.join(broke)}." if broke else "")
                           + (f" Untested: {', '.join(untested)}." if untested else "")}
    if artefact == "lineage":
        lin = lineage(project)
        return {"summary": [f"{v['id']} ← {v.get('parent')}: {v['step']}, "
                            f"{v.get('evidence', {}).get('verdict', 'base')}: {v['rationale']}"
                            for v in lin.get("variants", [])], "current": lin.get("current")}
    if artefact in ("warrants", "beliefs"):
        entries = project.ledger_entries(artefact)
        if not entries:
            return {"summary": f"no {artefact} committed yet"}
        last = entries[-1]
        if artefact == "warrants":
            return {"summary": f"{last['statement']} Within: {'; '.join(last['limits'])}. "
                               f"Model {last['variant']}, committed {last['at']}."}
        return {"summary": {t(p): {"mean": [round(x, 4) for x in s["mean"]],
                                   "sd": [round(x, 4) for x in s["sd"]]}
                            for p, s in last["posterior"].items()},
                "committed": last["at"]}
    raise MethodError("artefact must be one of claim, partitions, tests, lineage, "
                      "beliefs, warrants")


def intervene(project: Project, step: str, actor: str, agent_proposal: str,
              decision: str, reason: str) -> dict[str, Any]:
    """Log a redirection. This log is the experience the project encodes."""
    entry = {"at": now(), "step": step, "actor": actor, "agent_proposal": agent_proposal,
             "decision": decision, "reason": reason,
             "variant": lineage(project).get("current"),
             "skills_version": project.meta().get("skills_version")}
    problems = check_intervention(entry)
    if problems:
        raise MethodError("; ".join(problems))
    project.append_yaml_list("interventions.yaml", entry)
    return {"written": ["interventions.yaml"], "logged": entry}


PINS = ("robert_version", "skills_version", "stochadex_version")


def doctor(project: Project | None = None, repin: bool = False) -> dict[str, Any]:
    """Check the toolchain against robert's stochadex lock and the project's pin.

    With `repin`, move the project's pins to this robert and the stochadex in use: the
    way forward when the pinned version is one this robert no longer supports.
    """
    engine = Engine(project.root if project else ".")
    r = engine.resolved
    lock = deps.lock()
    repinned = None
    if repin:
        if project is None:
            raise MethodError("`--repin` needs a robert project")
        if r.binary is None:
            raise MethodError(f"nothing to re-pin to: {r.problem}")
        meta = project.meta()
        repinned = {"at": now(),
                    "from": {k: meta.get(k) for k in PINS},
                    "to": {"robert_version": __version__, "skills_version": __version__,
                           "stochadex_version": r.version}}
        project.set_meta(**repinned["to"],
                         repins=[*meta.get("repins", []), repinned])
    wanted = (project.meta().get("stochadex_version") if project else None) or lock["version"]
    problems = []
    if r.binary is None:
        problems.append(r.problem)
    elif project and not deps.supported(wanted):
        problems.append(f"the project pins stochadex {wanted}, which robert {__version__} "
                        f"no longer supports ({deps.range_text()}); run "
                        f"`robert doctor --repin` to move the project to {r.version}")
    elif r.version != wanted:
        fix = f"run `robert setup --stochadex {wanted}`"
        if project:
            fix += f", or `robert doctor --repin` to move the project to {r.version}"
        problems.append(f"using stochadex {r.version} but "
                        f"{'the project pins' if project else 'robert locks'} {wanted}; {fix}")
    return {
        "ok": not problems,
        "problems": problems,
        "robert_version": __version__,
        "stochadex": {"path": r.binary, "version": r.version, "source": r.source,
                      "wanted": wanted, "supported": deps.range_text(),
                      "locked": lock["version"]},
        "managed_home": str(deps.home()),
        "arrow_support": importlib.util.find_spec("pyarrow") is not None,
        **({"repinned": repinned} if repinned else {}),
    }
