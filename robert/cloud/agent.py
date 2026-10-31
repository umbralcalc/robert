"""`robert cloud agent <runner>`: start a CLI agent inside the sandbox.

It gives the agent the same skills and instructions every runner gets, then
replaces itself with the agent's process, whose stdout the host streams.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..project import MethodError
from . import instructions

SKILLS = Path("/opt/robert/skills")
STATE = Path("/state")


def claude_code(message: str, model: str, cont: bool) -> None:
    """Claude Code, headless. Its home is the mounted per-project state directory,
    so `--continue` picks up the previous turn's conversation."""
    if not shutil.which("claude"):
        raise MethodError("claude is not installed in this image; use the "
                          "robert-claude-code image")
    home = STATE if STATE.is_dir() else Path(os.environ.get("HOME", "/tmp"))
    skills = home / ".claude/skills"
    if SKILLS.is_dir():
        shutil.copytree(SKILLS, skills, dirs_exist_ok=True)
    os.environ["HOME"] = str(home)
    # No telemetry or update checks: the sandbox reaches only the model API.
    os.environ["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    argv = ["claude", "-p", message, "--output-format", "stream-json", "--verbose",
            "--model", model, "--permission-mode", "bypassPermissions",
            "--append-system-prompt", instructions()]
    if cont:
        argv.append("--continue")
    os.execvp("claude", argv)


AGENTS = {"claude-code": claude_code}
