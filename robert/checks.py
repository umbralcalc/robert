"""Deterministic checks shared by the gates.

A gate collects named checks. A failed gate is not an error: the result says which
check failed and what the method suggests next, and the user decides whether to
accept that, override it (logged as an intervention) or bench the project.
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .engine import Engine
from .project import MethodError, Project


@dataclass
class Gate:
    step: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append({"check": name, "passed": bool(passed),
                            **({"detail": detail} if detail else {})})
        return bool(passed)

    def all(self, name: str, problems: list[str]) -> bool:
        return self.check(name, not problems, "; ".join(problems))

    def note(self, text: str) -> None:
        """Something for the user's judgment that does not block the gate."""
        self.notes.append(text)

    @property
    def passed(self) -> bool:
        return all(c["passed"] for c in self.checks)

    def result(self, next_if_passed: str, next_if_failed: str) -> dict[str, Any]:
        failed = [c for c in self.checks if not c["passed"]]
        out: dict[str, Any] = {"passed": self.passed}
        # Compressed by default: show what failed and what needs a judgment.
        out["failed"] = failed
        out["passed_checks"] = [c["check"] for c in self.checks if c["passed"]]
        if self.notes:
            out["for_your_judgment"] = self.notes
        out["next"] = next_if_passed if self.passed else next_if_failed
        return out


def run_script(project: Project, script: str, config: str | None = None,
               sets: list[str] | None = None, extra_env: dict[str, str] | None = None
               ) -> dict[str, Any]:
    """Run an analysis script and read the JSON object on its last line of stdout.

    Scripts are functions of committed inputs: they get the project root, the
    config and overrides under test, and the outputs that config writes.
    """
    path = project.path(script)
    if not path.is_file():
        raise MethodError(f"script `{script}` does not exist")
    env = dict(os.environ)
    env["ROBERT_ROOT"] = str(project.root)
    if config:
        env["ROBERT_CONFIG"] = config
        env["ROBERT_SETS"] = json.dumps(sets or [])
        outs = Engine(project.root).file_outputs(config, sets)
        env["ROBERT_OUTPUTS"] = json.dumps({o["name"]: o["path"] for o in outs})
    env.update(extra_env or {})
    python = os.environ.get("ROBERT_PYTHON", sys.executable)
    proc = subprocess.run([python, str(path)], cwd=project.root, env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise MethodError(f"script `{script}` failed:\n{proc.stderr.strip()[-2000:]}")
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        raise MethodError(f"script `{script}` printed nothing; it must print one JSON object")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as e:
        raise MethodError(f"script `{script}`: last line is not JSON: {lines[-1]!r}") from e


def _canonical_json_log(path: Path) -> list[tuple[float, str, str]]:
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            rows.append((r.get("time"), r.get("partition_name"), line))
    return sorted(rows)


def harness_twice(project: Project, config: str, sets: list[str] | None = None
                  ) -> tuple[bool, str]:
    """Run the config twice with its file outputs redirected, and compare bytes.

    Catches statefulness residues and unseeded randomness from outside the engine.
    """
    engine = Engine(project.root)
    outs = engine.file_outputs(config, sets)
    work = project.path(".robert/harness")
    shutil.rmtree(work, ignore_errors=True)
    stdouts = []
    for arm in ("a", "b"):
        redirect = [f"outputs[name={o['name']}].function.path=.robert/harness/{arm}/{Path(o['path']).name}"
                    for o in outs]
        project.path(f".robert/harness/{arm}").mkdir(parents=True, exist_ok=True)
        r = engine._call(["--config", config, *engine._sets((sets or []) + redirect)])
        if not r.ok:
            return False, f"run {arm} failed: {r.summary()['error']}"
        stdouts.append(r.stdout)
    for o in outs:
        name = Path(o["path"]).name
        a, b = work / "a" / name, work / "b" / name
        if o["sink"] == "json_log":
            # Partitions write concurrently, so rows within one step may arrive in
            # either order; what must match is the set of rows at each time.
            same = _canonical_json_log(a) == _canonical_json_log(b)
        else:
            same = filecmp.cmp(a, b, shallow=False)
        if not same:
            return False, f"output `{o['name']}` differs between two identical runs"
    if not outs and stdouts[0] != stdouts[1]:
        return False, "stdout differs between two identical runs"
    shutil.rmtree(work, ignore_errors=True)
    return True, f"{len(outs) or 'stdout'} output(s) byte-identical across two runs"
