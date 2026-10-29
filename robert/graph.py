"""The partition graph: the one canvas every loop step draws on.

Exact within-step wiring comes from stochadex's own derivation (`stochadex graph`),
so the picture cannot drift from the model. Lag-1 `upstreams` reads, which that
derivation does not cover, are added as dashed hints. Each loop step then adds one
overlay from the method sidecars, and nodes carry the user's domain terms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .contracts import is_learned, sim_partitions
from .engine import Engine
from .project import MethodError, Project

_NODE = re.compile(r'^\s*(n\d+)\s*\[label="([^"]*)"\];')
_EDGE = re.compile(r'^\s*(n\d+)\s*->\s*(n\d+)(?:\s*\[label="([^"]*)"\])?;')

OVERLAYS = ["roles", "tests", "lineage", "warrant", "query"]


@dataclass
class Graph:
    nodes: list[str]
    exact: list[tuple[str, str, str]] = field(default_factory=list)  # src, dst, param
    hints: list[tuple[str, str, str]] = field(default_factory=list)  # src, dst, alias

    def parents(self, name: str) -> set[str]:
        return {s for s, d, _ in self.exact + self.hints if d == name}

    def ancestors(self, name: str) -> set[str]:
        seen: set[str] = set()
        stack = [name]
        while stack:
            for p in self.parents(stack.pop()):
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        return seen

    def path_between(self, sources: list[str], target: str) -> set[str]:
        """Every partition on some path from any source to the target, inclusive."""
        up = self.ancestors(target) | {target}
        hit = {s for s in sources if s in up}
        if not hit:
            return set()
        down: set[str] = set(hit)
        changed = True
        while changed:
            changed = False
            for s, d, _ in self.exact + self.hints:
                if s in down and d not in down and d in up:
                    down.add(d)
                    changed = True
        return down


def _parse_dot(dot: str) -> tuple[list[str], list[tuple[str, str, str]]]:
    ids: dict[str, str] = {}
    edges = []
    for line in dot.splitlines():
        if m := _NODE.match(line):
            ids[m.group(1)] = m.group(2)
        elif m := _EDGE.match(line):
            edges.append((ids[m.group(1)], ids[m.group(2)], m.group(3) or ""))
    return list(ids.values()), edges


def load(project: Project, config: str = "model/sim.yaml") -> Graph:
    r = Engine(project.root).graph(config, "dot")
    if not r.ok:
        raise MethodError(f"stochadex graph failed: {r.summary()['error']}")
    nodes, exact = _parse_dot(r.stdout)
    sim = project.read_yaml(config, {})
    hints = []
    for e in ((sim.get("main") or {}).get("expressions") or []):
        for alias, src in (e.get("upstreams") or {}).items():
            hints.append((src, e["partition"], alias))
    return Graph(nodes=nodes, exact=exact, hints=hints)


def _ident(name: str) -> str:
    return "p_" + re.sub(r"\W", "_", name)


def mermaid(project: Project, overlay: str | None = None,
            config: str = "model/sim.yaml", highlight: set[str] | None = None) -> str:
    """Render the partition graph with one overlay. Only what changed or needs a
    judgment is marked; everything else stays plain."""
    g = load(project, config)
    terms = (project.read_yaml("domain.yaml", {}) or {}).get("terms", {}) or {}
    side = (project.read_yaml("model/partitions.yaml", {}) or {}).get("partitions", {}) or {}
    sim = {p["name"]: p for p in sim_partitions(project.read_yaml(config, {}))}
    claim = project.read_yaml("claim.yaml", {}) or {}
    observables = set(claim.get("observables") or [])

    lines = ["flowchart LR"]
    classes: dict[str, list[str]] = {}

    def mark(cls: str, name: str) -> None:
        classes.setdefault(cls, []).append(_ident(name))

    for n in g.nodes:
        meta = side.get(n, {}) or {}
        label = terms.get(n, n)
        sub = []
        if overlay == "roles":
            sub.append(meta.get("role", "no role"))
            if meta.get("hypothesis"):
                sub.append(meta["hypothesis"])
        elif overlay == "tests":
            sub.append(meta.get("status", "untested"))
        if sim.get(n) and is_learned(sim[n]):
            sub.append("learned")
        text = label if not sub else f"{label}<br/><small>{' · '.join(sub)}</small>"
        shape = ('(["', '"])') if meta.get("observed") else ('["', '"]')
        lines.append(f'  {_ident(n)}{shape[0]}{text}{shape[1]}')

        if meta.get("observed"):
            mark("observed", n)
        if overlay == "tests":
            mark(meta.get("status", "untested"), n)
        if overlay in ("warrant", "query") and highlight is not None:
            mark("inscope" if n in highlight else "outscope", n)
        if n in observables and overlay in (None, "roles"):
            mark("claim", n)

    for s, d, p in g.exact:
        lines.append(f"  {_ident(s)} -->|{p}| {_ident(d)}")
    for s, d, a in g.hints:
        lines.append(f"  {_ident(s)} -.->|{a} lag 1| {_ident(d)}")

    styles = {
        "observed": "fill:#e8eef7,stroke:#4a6fa5",
        "claim": "stroke:#b5651d,stroke-width:3px",
        "passed": "fill:#e3f1e3,stroke:#3a7d3a",
        "failed": "fill:#f7e3e3,stroke:#a33",
        "untested": "fill:#f4f4f4,stroke:#999,stroke-dasharray:4 3",
        "benched": "fill:#eee,stroke:#bbb,color:#999",
        "inscope": "stroke:#b5651d,stroke-width:3px",
        "outscope": "fill:#f7f7f7,stroke:#ccc,color:#aaa",
    }
    for cls, members in classes.items():
        lines.append(f"  classDef {cls} {styles[cls]}")
        lines.append(f"  class {','.join(members)} {cls}")
    return "\n".join(lines) + "\n"


def lineage_strip(project: Project) -> str:
    """How discovery grew the model and compression trimmed it, as one small graph."""
    variants = (project.read_yaml("model/lineage.yaml", {}) or {}).get("variants", []) or []
    lines = ["flowchart LR"]
    for v in variants:
        verdict = v.get("evidence", {}).get("verdict", "")
        lines.append(f'  {_ident(v["id"])}["{v["id"]}<br/><small>{v["step"]} {verdict}</small>"]')
        if v.get("parent"):
            lines.append(f"  {_ident(v['parent'])} --> {_ident(v['id'])}")
    return "\n".join(lines) + "\n"


def summary(project: Project) -> dict[str, Any]:
    g = load(project)
    return {"partitions": g.nodes,
            "within_step_edges": [f"{s} -> {d} ({p})" for s, d, p in g.exact],
            "lag1_edges": [f"{s} -> {d} ({a})" for s, d, a in g.hints]}
