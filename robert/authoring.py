"""How authoring a config goes: every stochadex call on one, and what the `main:` level costs.

A stochadex config puts a run's own parts (`partitions`, `expressions`, `simulation`)
under `main:`, and everything about the run as a whole (`inputs`, `outputs`, `macros`,
`run`, `embedded`) at the top. Whether that level is worth keeping, or should be
flattened away, is decided on evidence: how often writing a key at the wrong level
makes a config fail, and so costs a retry. stochadex names a misplaced key but not
where it was written, so the level is read from the config itself.

Every stochadex call on a config in a project appends one line to
`.robert/authoring.jsonl`: the command, the config and a hash of its text, the
outcome, the first error line, and any keys written at the wrong level. Calls on the
same text of the same config are one authoring attempt; an attempt fails on a config
error (exit 78), and a failed attempt followed by another text of the same config was
retried.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

LOG = ".robert/authoring.jsonl"

# The keys that belong under `main:`, and those that belong at the top level.
MAIN_KEYS = ("partitions", "expressions", "simulation")
TOP_KEYS = ("inputs", "outputs", "macros", "run", "embedded")

# stochadex's exit code for a config it refuses (api.ExitConfig).
CONFIG_ERROR = 78


def slips(text: str) -> list[str]:
    """The keys a config writes at the wrong side of the `main:` level."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(doc, dict):
        return []
    found = [f"{key} outside main" for key in MAIN_KEYS if key in doc]
    main = doc.get("main")
    if isinstance(main, dict):
        found += [f"{key} inside main" for key in TOP_KEYS if key in main]
    return found


def _command(args: list[str]) -> str:
    if args and not args[0].startswith("-"):
        return args[0]
    return "check" if "--check" in args else "run"


def _config(args: list[str]) -> str | None:
    for flag in ("--config", "-c"):
        if flag in args and args.index(flag) + 1 < len(args):
            return args[args.index(flag) + 1]
    return None


def _first_error(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("stochadex:"):
            return line[:300]
    return ""


def record(root: Path, args: list[str], exit_code: int, stderr: str) -> dict[str, Any] | None:
    """Log one stochadex call on a config, when root is a project and args name a config."""
    root = Path(root)
    config = _config(args)
    if config is None or not (root / ".robert/project.yaml").exists():
        return None
    path = root / config
    text = path.read_text() if path.is_file() else ""
    entry = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": _command(args),
        "config": config,
        "sha": hashlib.sha256(text.encode()).hexdigest()[:16],
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "error": "" if exit_code == 0 else _first_error(stderr),
        "slips": slips(text),
    }
    log = root / LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def entries(root: Path) -> list[dict[str, Any]]:
    log = Path(root) / LOG
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def summary(calls: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Authoring attempts, failures and retries, and how many of each the `main:` level caused.

    An attempt is one text of one config, however many times it was checked, inspected
    or run. It failed when any call on it was a config error, and was retried when a
    later text of the same config followed it. A failure is the `main:` level's when the
    failed text wrote a key at the wrong side of it.
    """
    attempts: list[dict[str, Any]] = []
    by_text: dict[tuple[str, str], dict[str, Any]] = {}
    for call in calls:
        key = (call["config"], call["sha"])
        if key not in by_text:
            by_text[key] = {"config": call["config"], "failed": False, "slips": call["slips"]}
            attempts.append(by_text[key])
        if call["exit_code"] == CONFIG_ERROR:
            by_text[key]["failed"] = True
    last: dict[str, int] = {}
    for i, attempt in enumerate(attempts):
        last[attempt["config"]] = i
    failed = [a for a in attempts if a["failed"]]
    retried = [a for i, a in enumerate(attempts) if a["failed"] and last[a["config"]] > i]
    level = [a for a in failed if a["slips"]]
    counts: dict[str, int] = {}
    for a in level:
        for slip in a["slips"]:
            counts[slip] = counts.get(slip, 0) + 1
    return {
        "attempts": len(attempts),
        "failed": len(failed),
        "retried": len(retried),
        "main_level": {
            "failed": len(level),
            "retried": len([a for a in retried if a["slips"]]),
            "share_of_failed": round(len(level) / len(failed), 3) if failed else None,
            "slips": dict(sorted(counts.items())),
        },
    }


def report(roots: Iterable[Path]) -> dict[str, Any]:
    """The summary of each project, and of all of them together."""
    per: dict[str, Any] = {}
    every: list[dict[str, Any]] = []
    for root in roots:
        # Configs are named per project, so two projects' model/sim.yaml stay apart.
        calls = [{**c, "config": f"{root}:{c['config']}"} for c in entries(root)]
        per[str(root)] = summary(entries(root))
        every += calls
    return {"projects": per, "total": summary(every)}
