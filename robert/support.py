"""Supporting commands: run, graph, plot, status, explain, intervene, doctor."""

from __future__ import annotations

import importlib.util
from typing import Any

from . import __version__, deps
from . import graph as graphs
from .contracts import check_intervention
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
        in_model = set(_sim_names(project, variant(project)["config"]))
    except MethodError:
        in_model = set(side)
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
        "warrants": len(project.ledger_entries("warrants")),
        "interventions": len(ints),
        "versions": {k: meta.get(k) for k in ("robert_version", "skills_version",
                                              "stochadex_version")},
    }


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


def doctor(project: Project | None = None) -> dict[str, Any]:
    """Check the toolchain against robert's stochadex lock and the project's pin."""
    engine = Engine(project.root if project else ".")
    r = engine.resolved
    lock = deps.lock()
    wanted = (project.meta().get("stochadex_version") if project else None) or lock["version"]
    problems = []
    if r.binary is None:
        problems.append(r.problem)
    elif r.version != wanted:
        problems.append(f"using stochadex {r.version} but "
                        f"{'the project pins' if project else 'robert locks'} {wanted}; "
                        f"run `robert setup --stochadex {wanted}`")
    if r.binary and r.graph is None:
        problems.append("no partition graph renderer (stochadex < v0.24 without "
                        "stochadex-graph); `robert setup` installs it when Go is available")
    return {
        "ok": not problems,
        "problems": problems,
        "robert_version": __version__,
        "stochadex": {"path": r.binary, "version": r.version, "source": r.source,
                      "wanted": wanted, "supported": deps.range_text(),
                      "locked": lock["version"],
                      "graph": " ".join(r.graph) if r.graph else None,
                      "catalogue": r.has_catalogue},
        "managed_home": str(deps.home()),
        "arrow_support": importlib.util.find_spec("pyarrow") is not None,
    }
