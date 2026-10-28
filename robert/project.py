"""The generated project repo: where every method file lives, and how it is written.

Every project has the same shape, so an agent, a reader or a second run can navigate
it without being told where things are. Append-only files are only ever appended to,
and the ledger is hash-chained so a later edit to an earlier entry is detectable.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

MARKER = ".robert/project.yaml"

LOOP = [
    "init",
    "pose",
    "conjecture",
    "confront",
    "test",
    "discover",
    "compress",
    "warrant",
    "query",
    "revise",
]


class MethodError(Exception):
    """A request the method cannot carry out as asked. The message says what to fix."""


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Project:
    root: Path

    # --- locating ---------------------------------------------------------

    @classmethod
    def find(cls, start: str | Path | None = None) -> "Project":
        here = Path(start or Path.cwd()).resolve()
        for d in [here, *here.parents]:
            if (d / MARKER).is_file():
                return cls(d)
        raise MethodError(
            f"no robert project at or above {here}; run `robert init` to create one"
        )

    # --- paths ------------------------------------------------------------

    def path(self, rel: str) -> Path:
        return self.root / rel

    @property
    def meta_path(self) -> Path:
        return self.root / MARKER

    @property
    def sim(self) -> Path:
        return self.root / "model/sim.yaml"

    # --- yaml -------------------------------------------------------------

    def exists(self, rel: str) -> bool:
        return self.path(rel).exists()

    def read_yaml(self, rel: str, default: Any = None) -> Any:
        p = self.path(rel)
        if not p.exists():
            return default
        data = yaml.safe_load(p.read_text())
        return default if data is None else data

    def write_yaml(self, rel: str, data: Any) -> Path:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        return p

    def append_yaml_list(self, rel: str, entry: dict[str, Any]) -> Path:
        """Append one item to a YAML list file without rewriting earlier items."""
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        text = p.read_text() if p.exists() else ""
        if text.strip() in ("", "[]"):
            text = ""
        elif not text.endswith("\n"):
            text += "\n"
        p.write_text(
            text + yaml.safe_dump([entry], sort_keys=False, allow_unicode=True)
        )
        return p

    # --- project metadata ---------------------------------------------------

    def meta(self) -> dict[str, Any]:
        return self.read_yaml(MARKER, {})

    def set_meta(self, **updates: Any) -> None:
        meta = self.meta()
        meta.update(updates)
        self.write_yaml(MARKER, meta)

    def record_step(self, step: str, passed: bool, next_step: str) -> None:
        """Remember the last outcome of each loop step, for status and later gates."""
        meta = self.meta()
        steps = meta.setdefault("steps", {})
        steps[step] = {"passed": passed, "at": now()}
        meta["last"] = {"step": step, "passed": passed, "next": next_step}
        self.write_yaml(MARKER, meta)

    def step_passed(self, step: str) -> bool:
        return bool(self.meta().get("steps", {}).get(step, {}).get("passed"))

    # --- ledger ---------------------------------------------------------------

    def ledger_entries(self, name: str) -> list[dict[str, Any]]:
        p = self.path(f"ledger/{name}.jsonl")
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]

    def append_ledger(self, name: str, entry: dict[str, Any]) -> dict[str, Any]:
        """Append a timestamped entry, chained to the hash of the one before it.

        The chain proves when a claim was made and that nothing earlier was edited
        since; it says nothing about whether the claim is true.
        """
        entries = self.ledger_entries(name)
        prev = entries[-1]["hash"] if entries else None
        body = {"at": now(), "prev": prev, **entry}
        body["hash"] = sha256_text(json.dumps(body, sort_keys=True))
        p = self.path(f"ledger/{name}.jsonl")
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(body, sort_keys=True) + "\n")
        return body

    def verify_ledger(self, name: str) -> list[str]:
        problems = []
        prev = None
        for i, e in enumerate(self.ledger_entries(name)):
            body = {k: v for k, v in e.items() if k != "hash"}
            if body.get("prev") != prev:
                problems.append(f"{name}[{i}]: chain broken (prev does not match)")
            if sha256_text(json.dumps(body, sort_keys=True)) != e.get("hash"):
                problems.append(f"{name}[{i}]: entry edited after it was committed")
            prev = e.get("hash")
        return problems
