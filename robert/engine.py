"""The only door to the stochadex binary.

robert never reimplements what stochadex does: validation is `--check`, what a run
reads and writes is `inspect --io`, what it was made from is `--provenance`, and the
partition graph is `stochadex graph`, and what a build can run is `stochadex catalogue`.
Which binary runs is decided by `deps.resolve`: the project's pinned version first,
always within robert's supported range. Every call runs with the project root as its
working directory, so relative paths in a config mean the same thing everywhere.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import deps
from .project import MethodError

# stochadex classifies every failure by exit code (see api.ExitCode).
EXIT_MEANING = {
    0: "ok",
    64: "the command line was wrong",
    65: "an input's contents are unusable",
    70: "the simulation failed while running",
    75: "an input or output was unreachable (re-running unchanged might succeed)",
    78: "the config is wrong; fix it",
}

PROVENANCE_SUFFIX = ".provenance.json"


def _json_tail(text: str) -> Any:
    """stochadex prints a provenance banner line before its JSON; skip to the JSON."""
    start = text.find("{")
    if start < 0:
        raise MethodError(f"stochadex printed no JSON:\n{text.strip()}")
    return json.loads(text[start:])


@dataclass
class Result:
    ok: bool
    exit_code: int
    meaning: str
    stdout: str = ""
    stderr: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok, "exit_code": self.exit_code}
        if not self.ok:
            out["meaning"] = self.meaning
            out["error"] = (self.stderr or self.stdout).strip()[-2000:]
        out.update(self.data)
        return out


def project_pin(root: Path) -> str | None:
    """The stochadex version a project was created against, if it is a project."""
    meta = Path(root) / ".robert/project.yaml"
    if not meta.exists():
        return None
    return (yaml.safe_load(meta.read_text()) or {}).get("stochadex_version")


class Engine:
    """A stochadex binary resolved for one project root (see `deps.resolve`)."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.resolved = deps.resolve(project_pin(self.root))
        self.bin = self.resolved.binary

    # --- plumbing ---------------------------------------------------------

    def _call(self, args: list[str]) -> Result:
        if not self.bin:
            raise MethodError(self.resolved.problem or "stochadex is not installed")
        proc = subprocess.run(
            [self.bin, *args], cwd=self.root, capture_output=True, text=True
        )
        return Result(
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            meaning=EXIT_MEANING.get(proc.returncode, "unclassified failure"),
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    @staticmethod
    def _sets(sets: list[str] | None) -> list[str]:
        args: list[str] = []
        for s in sets or []:
            args += ["--set", s]
        return args

    # --- the stochadex surface robert uses ---------------------------------

    def version(self) -> str | None:
        return self.resolved.version

    def catalogue(self) -> dict[str, Any]:
        """What this build registers, as stochadex reports it."""
        r = self._call(["catalogue"])
        if not r.ok:
            raise MethodError(f"stochadex catalogue failed: {r.summary()['error']}")
        return _json_tail(r.stdout)

    def check(self, config: str, sets: list[str] | None = None) -> Result:
        return self._call(["--config", config, "--check", *self._sets(sets)])

    def inspect_io(self, config: str, sets: list[str] | None = None) -> dict[str, Any]:
        r = self._call(["inspect", "--io", "-c", config, *self._sets(sets)])
        if not r.ok:
            raise MethodError(f"stochadex inspect --io failed: {r.summary()['error']}")
        return _json_tail(r.stdout)

    def provenance_key(self, config: str, sets: list[str] | None = None) -> str:
        r = self._call(["inspect", "--provenance", "-c", config, *self._sets(sets)])
        if not r.ok:
            raise MethodError(f"stochadex inspect --provenance failed: {r.summary()['error']}")
        return _json_tail(r.stdout)["key"]

    def run(
        self,
        config: str,
        sets: list[str] | None = None,
        skip_if_unchanged: bool = True,
    ) -> Result:
        """Run with provenance on, and report each file output with its provenance key."""
        flag = "--skip-if-unchanged" if skip_if_unchanged else "--provenance"
        r = self._call(["--config", config, flag, *self._sets(sets)])
        if r.ok:
            r.data["outputs"] = self.file_outputs(config, sets)
        return r

    def file_outputs(
        self, config: str, sets: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Each file output a config writes, with the provenance key it carries now."""
        io = self.inspect_io(config, sets)
        outs = []
        for o in io.get("outputs", []):
            loc = o.get("location")
            if not loc or o.get("sink") in ("stdout", "websocket", "connection", "nil"):
                continue
            side = self.root / (loc + PROVENANCE_SUFFIX)
            key = json.loads(side.read_text())["key"] if side.exists() else None
            outs.append({"name": o.get("name"), "sink": o.get("sink"), "path": loc,
                         "provenance_key": key})
        return outs

    def graph(self, config: str, fmt: str = "dot") -> Result:
        return self._call(["graph", "--config", config, "--format", fmt])
