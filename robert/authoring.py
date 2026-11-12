"""How authoring a config goes: every stochadex call on one, and how it came out.

Every stochadex call on a config in a project appends one line to
`.robert/authoring.jsonl`: the command, the config and a hash of its text, the
outcome and the first error line. Calls on the same text of the same config are one
authoring attempt; an attempt fails on a config error (exit 78), and a failed attempt
followed by another text of the same config was retried. The errors that recur across
projects are where authoring a config is hard.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

LOG = ".robert/authoring.jsonl"

# stochadex's exit code for a config it refuses (api.ExitConfig).
CONFIG_ERROR = 78


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
    """Authoring attempts, failures and retries, and each failed attempt's error.

    An attempt is one text of one config, however many times it was checked, inspected
    or run. It failed when any call on it was a config error, and was retried when a
    later text of the same config followed it. errors counts the failed attempts by
    their first error line, most frequent first.
    """
    attempts: list[dict[str, Any]] = []
    by_text: dict[tuple[str, str], dict[str, Any]] = {}
    for call in calls:
        key = (call["config"], call["sha"])
        if key not in by_text:
            by_text[key] = {"config": call["config"], "failed": False, "error": ""}
            attempts.append(by_text[key])
        if call["exit_code"] == CONFIG_ERROR and not by_text[key]["failed"]:
            by_text[key].update(failed=True, error=call["error"])
    last: dict[str, int] = {}
    for i, attempt in enumerate(attempts):
        last[attempt["config"]] = i
    failed = [a for a in attempts if a["failed"]]
    retried = [a for i, a in enumerate(attempts) if a["failed"] and last[a["config"]] > i]
    counts: dict[str, int] = {}
    for a in failed:
        counts[a["error"]] = counts.get(a["error"], 0) + 1
    return {
        "attempts": len(attempts),
        "failed": len(failed),
        "retried": len(retried),
        "errors": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))),
    }


def report(roots: Iterable[Path]) -> dict[str, Any]:
    """The summary of each project, and of all of them together."""
    per: dict[str, Any] = {}
    every: list[dict[str, Any]] = []
    for root in roots:
        # Configs are named per project, so two projects' model/sim.yaml stay apart.
        every += [{**c, "config": f"{root}:{c['config']}"} for c in entries(root)]
        per[str(root)] = summary(entries(root))
    return {"projects": per, "total": summary(every)}
