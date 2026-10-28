"""Turn the truth run into the observation table: time, population, per-capita growth."""
import json
from pathlib import Path

rows = [json.loads(line) for line in Path("data/truth.log").read_text().splitlines()]
xs = [(r["time"], r["state"][0]) for r in rows if r["partition_name"] == "population"]
lines = ["time,population,growth"]
for (t, x), (_, x_next) in zip(xs, xs[1:]):
    lines.append(f"{t},{x:.6f},{(x_next - x) / x:.6f}")
Path("data/obs.csv").write_text("\n".join(lines) + "\n")
print(json.dumps({"rows": len(lines) - 1}))
