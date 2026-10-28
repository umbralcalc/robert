"""Reading what stochadex wrote, and drawing the charts a claim needs.

Only stochadex writes out/. robert reads it back, in the two formats a run produces
(json_log always, Arrow when pyarrow is installed), and draws plain SVG so a chart
needs no plotting stack.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

Series = dict[str, list[tuple[float, list[float]]]]


def read(path: Path) -> Series:
    if path.suffix == ".arrow":
        return _read_arrow(path)
    series: Series = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        series.setdefault(row["partition_name"], []).append(
            (float(row["time"]), [float(x) for x in row["state"]])
        )
    return series


def _read_arrow(path: Path) -> Series:
    try:
        import pyarrow.ipc as ipc
    except ImportError as e:  # pragma: no cover - optional dependency
        raise RuntimeError("reading .arrow outputs needs `pip install robert[arrow]`") from e
    table = ipc.open_file(path).read_all().to_pylist()
    series: Series = {}
    for row in table:
        series.setdefault(row["partition_name"], []).append(
            (float(row["time"]), [float(x) for x in row["state"]])
        )
    return series


def last_window(series: Series, partition: str, fraction: float = 0.2) -> list[list[float]]:
    rows = [s for _, s in series.get(partition, [])]
    n = max(1, int(len(rows) * fraction))
    return rows[-n:]


def mean_sd(rows: list[list[float]]) -> tuple[list[float], list[float]]:
    if not rows:
        return [], []
    width = len(rows[0])
    means = [sum(r[i] for r in rows) / len(rows) for i in range(width)]
    sds = [
        (sum((r[i] - means[i]) ** 2 for r in rows) / max(1, len(rows) - 1)) ** 0.5
        for i in range(width)
    ]
    return means, sds


PALETTE = ["#4a6fa5", "#b5651d", "#3a7d3a", "#8a4fa5", "#a33", "#2a8a8a"]


def svg_lines(series: Series, partitions: list[str], title: str, caption: str,
              width: int = 720, height: int = 320) -> str:
    """A line per state slot of each named partition, against time."""
    lines = []
    for p in partitions:
        rows = series.get(p, [])
        if not rows:
            continue
        for i in range(len(rows[0][1])):
            lines.append((f"{p}[{i}]" if len(rows[0][1]) > 1 else p,
                          [(t, s[i]) for t, s in rows]))
    if not lines:
        raise ValueError(f"none of {partitions} appear in the output")
    xs = [x for _, pts in lines for x, _ in pts]
    ys = [y for _, pts in lines for _, y in pts]
    x0, x1 = min(xs), max(xs) or 1.0
    y0, y1 = min(ys), max(ys)
    if y1 == y0:
        y1 = y0 + 1.0
    L, R, T, B = 56, 140, 40, 48
    pw, ph = width - L - R, height - T - B

    def sx(x: float) -> float:
        return L + (x - x0) / ((x1 - x0) or 1.0) * pw

    def sy(y: float) -> float:
        return T + (1 - (y - y0) / (y1 - y0)) * ph

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
           f'font-family="system-ui, sans-serif" font-size="11">',
           f'<rect width="{width}" height="{height}" fill="white"/>',
           f'<text x="{L}" y="22" font-size="14" font-weight="600">{escape(title)}</text>',
           f'<line x1="{L}" y1="{T + ph}" x2="{L + pw}" y2="{T + ph}" stroke="#999"/>',
           f'<line x1="{L}" y1="{T}" x2="{L}" y2="{T + ph}" stroke="#999"/>']
    for k in range(5):
        yv = y0 + (y1 - y0) * k / 4
        out.append(f'<text x="{L - 6}" y="{sy(yv) + 4:.1f}" text-anchor="end" fill="#666">{yv:.3g}</text>')
        xv = x0 + (x1 - x0) * k / 4
        out.append(f'<text x="{sx(xv):.1f}" y="{T + ph + 16}" text-anchor="middle" fill="#666">{xv:.3g}</text>')
    out.append(f'<text x="{L + pw / 2}" y="{height - 18}" text-anchor="middle" fill="#666">time</text>')
    for k, (label, pts) in enumerate(lines):
        colour = PALETTE[k % len(PALETTE)]
        d = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in pts)
        out.append(f'<polyline fill="none" stroke="{colour}" stroke-width="1.6" points="{d}"/>')
        ly = sy(pts[-1][1])
        out.append(f'<text x="{L + pw + 6}" y="{ly + 4:.1f}" fill="{colour}">{escape(label)}</text>')
    out.append(f'<text x="{L}" y="{height - 4}" fill="#444">{escape(caption)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
