"""Shared readers for the analysis scripts. robert runs each script from the project
root with ROBERT_OUTPUTS naming the files the config under test wrote."""
import csv
import json
import os
from pathlib import Path

TRAIN_END, TEST_START = 24, 25


def observations() -> dict[float, float]:
    with open("data/obs.csv") as f:
        return {float(r["time"]): float(r["population"]) for r in csv.DictReader(f)}


def growth_table() -> list[tuple[float, float]]:
    with open("data/obs.csv") as f:
        return [(float(r["population"]), float(r["growth"])) for r in csv.DictReader(f)]


def model_trajectory(partition: str = "population") -> dict[float, float]:
    outputs = json.loads(os.environ["ROBERT_OUTPUTS"])
    path = Path(outputs["model"])
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {r["time"]: r["state"][0] for r in rows if r["partition_name"] == partition}


def slope(points: list[tuple[float, float]]) -> float:
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    return sum((x - mx) * (y - my) for x, y in points) / sxx


def test_window_rmse() -> tuple[float, float]:
    obs, sim = observations(), model_trajectory()
    errs = [(sim[t] - obs[t]) ** 2 for t in obs if t >= TEST_START and t in sim]
    rmse = (sum(errs) / len(errs)) ** 0.5
    scale = sum(obs[t] for t in obs if t >= TEST_START) / len(errs)
    return rmse, scale
