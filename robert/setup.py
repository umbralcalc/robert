"""`robert setup`: everything after the package itself is installed.

Installs the locked stochadex release (checksum-verified), then registers robert with
whichever coding agents are present. Every step is idempotent, so re-running it is
also how you repair or upgrade an install.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import deps
from .project import MethodError
from .scaffold import MCP_SERVER

MARKETPLACE = "umbralcalc/robert"
AGENTS = ("claude", "cursor")


def _claude() -> dict[str, Any]:
    """Install the Claude Code plugin: both skills plus the MCP server."""
    if not shutil.which("claude"):
        return {"status": "skipped", "reason": "`claude` is not on PATH"}
    steps = [["claude", "plugin", "marketplace", "add", MARKETPLACE],
             ["claude", "plugin", "install", "robert@robert"]]
    for cmd in steps:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out = (proc.stdout + proc.stderr).lower()
        if proc.returncode != 0 and "already" not in out:
            return {"status": "failed", "command": " ".join(cmd),
                    "error": (proc.stderr or proc.stdout).strip()[-500:]}
    return {"status": "installed", "plugin": "robert@robert"}


def _cursor() -> dict[str, Any]:
    """Add robert to Cursor's global MCP servers, keeping every other entry."""
    cursor_dir = Path.home() / ".cursor"
    if not cursor_dir.exists():
        return {"status": "skipped", "reason": "~/.cursor does not exist"}
    path = cursor_dir / "mcp.json"
    config = json.loads(path.read_text()) if path.exists() else {}
    servers = config.setdefault("mcpServers", {})
    if servers.get("robert") == MCP_SERVER:
        return {"status": "already configured", "path": str(path)}
    servers["robert"] = MCP_SERVER
    path.write_text(json.dumps(config, indent=2) + "\n")
    return {"status": "configured", "path": str(path),
            "note": "copy adapters/cursor/rules/ into a project's .cursor/rules/ for the skills"}


def setup(stochadex: str | None = None, accelerated: bool = False,
          agents: list[str] | None = None, no_agents: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"stochadex": deps.install(stochadex, accelerated)}
    chosen = [] if no_agents else (agents or list(AGENTS))
    unknown = set(chosen) - set(AGENTS)
    if unknown:
        raise MethodError(f"unknown agent(s): {', '.join(sorted(unknown))}; "
                          f"choose from {', '.join(AGENTS)}")
    result["agents"] = {a: {"claude": _claude, "cursor": _cursor}[a]() for a in chosen}
    on_path = shutil.which("robert")
    if not on_path:
        result["warning"] = ("`robert` is not on PATH, so agents cannot start its MCP "
                             "server; add the install's bin directory to PATH")
    result["next"] = "robert doctor"
    return result
