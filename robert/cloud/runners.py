"""Runners: what drives the work inside the shared sandbox.

Every runner has the same shape. `start` sets up a new project's conversation,
and `turn` sends one message and yields `Event`s until the agent is waiting on the
user. The chat CLI and the a2a stand-in user both drive runners only through this
interface, so swapping the agent changes nothing else about a run.

- `managed-agents`: Anthropic runs the agent loop; `robert cloud host` claims the
  session and runs its tools in the sandbox. The only runner whose model
  credentials stay out of the sandbox.
- `claude-code`: Claude Code, headless, inside the sandbox, one container per turn,
  its conversation history kept in a per-project state directory on the host.
- `command`: any agent CLI, from a template in the cloud config. Its output is
  passed through as plain text.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from ..project import MethodError
from . import Config
from . import sandbox

# Model APIs a CLI runner's sandbox must reach, beyond the project's data hosts.
ANTHROPIC_HOSTS = ["api.anthropic.com"]


@dataclass
class Event:
    kind: str           # "text" | "tool" | "ask" | "done" | "ended" | "error"
    text: str = ""
    tool: str = ""
    raw: Any = None


Confirm = Callable[[Event], bool]


class Runner:
    name = ""

    def start(self, cfg: Config, project: str, repo: str | None) -> dict[str, Any]:
        """Set up a new project's conversation; returns state saved in the registry."""
        return {}

    def turn(self, cfg: Config, project: str, entry: dict[str, Any], message: str,
             confirm: Confirm) -> Iterator[Event]:
        raise NotImplementedError


# --- managed-agents -----------------------------------------------------------------


class ManagedAgents(Runner):
    name = "managed-agents"

    def _client(self):
        from anthropic import Anthropic
        return Anthropic()

    def start(self, cfg: Config, project: str, repo: str | None) -> dict[str, Any]:
        if not cfg.agent_id or not cfg.environment_id:
            raise MethodError("the managed-agents runner needs `robert cloud configure "
                              "--lock claude-lock.json` after `ant apply cloud/agents/robert`")
        session = self._client().beta.sessions.create(
            agent=cfg.agent_id, environment_id=cfg.environment_id, title=project,
            metadata={"robert_project": project, **({"robert_repo": repo} if repo else {})})
        return {"session_id": session.id}

    def turn(self, cfg, project, entry, message, confirm):
        client = self._client()
        sid = entry["session_id"]
        with client.beta.sessions.events.stream(session_id=sid) as stream:
            client.beta.sessions.events.send(session_id=sid, events=[
                {"type": "user.message", "content": [{"type": "text", "text": message}]}])
            for event in stream:
                kind = event.type
                if kind == "agent.message":
                    text = "".join(b.text for b in event.content if b.type == "text")
                    yield Event("text", text, raw=event)
                elif kind in ("agent.tool_use", "agent.mcp_tool_use"):
                    ev = Event("tool", describe(getattr(event, "input", None)), event.name, event)
                    yield ev
                    if getattr(event, "evaluated_permission", None) == "ask":
                        ok = confirm(ev)
                        client.beta.sessions.events.send(session_id=sid, events=[
                            {"type": "user.tool_confirmation", "tool_use_id": event.id,
                             "result": "allow" if ok else "deny"}])
                elif kind == "session.status_idle":
                    if event.stop_reason.type != "requires_action":
                        yield Event("done")
                        return
                elif kind == "session.status_terminated":
                    yield Event("ended")
                    return


# --- CLI agents in the sandbox --------------------------------------------------------


class CliRunner(Runner):
    """One container per turn: prepare the repo and egress, run the agent's command,
    stream its output as events, push what it committed."""

    def image(self, cfg: Config) -> str:
        return (cfg.runners.get(self.name) or {}).get("image") or cfg.image

    def hosts(self, cfg: Config) -> list[str]:
        return list((cfg.runners.get(self.name) or {}).get("hosts") or [])

    def secrets(self, cfg: Config) -> list[str]:
        return list((cfg.runners.get(self.name) or {}).get("env") or [])

    def command(self, cfg: Config, project: str, message: str, first: bool) -> list[str]:
        raise NotImplementedError

    def mounts(self, cfg: Config, project: str) -> dict[Path, str]:
        return {}

    def parse(self, line: str) -> Iterator[Event]:
        yield Event("text", line.rstrip("\n"))

    def turn(self, cfg, project, entry, message, confirm):
        path = sandbox.ensure_repo(cfg, project, entry.get("repo"))
        sandbox.ensure_egress(sandbox.active_projects(cfg), self.hosts(cfg))
        missing = [n for n in self.secrets(cfg) if not os.environ.get(n)]
        if missing:
            raise MethodError(f"the {self.name} runner needs {', '.join(missing)} "
                              "set in this terminal")
        first = not entry.get("turns")
        args = sandbox.container_args(
            self.image(cfg), f"robert-{project}-{os.getpid()}", project, path,
            self.secrets(cfg), self.command(cfg, project, message, first),
            self.mounts(cfg, project))
        proc = subprocess.Popen(["docker", *args], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            yield from self.parse(line)
        code = proc.wait()
        if code != 0:
            yield Event("error", (proc.stderr.read() if proc.stderr else "")[-1500:]
                        or f"the agent exited with code {code}")
        else:
            # Only a completed turn starts a conversation the next turn can continue.
            entry["turns"] = entry.get("turns", 0) + 1
        yield Event("text", f"[{sandbox.push(path)}]")
        yield Event("done")


class ClaudeCode(CliRunner):
    """Claude Code, headless (`claude -p --output-format stream-json`). Its home, and
    so its conversation history, is a per-project directory on the host, so each
    turn's container continues the last turn's conversation."""

    name = "claude-code"
    model = "claude-opus-5-5"

    def image(self, cfg: Config) -> str:
        from .. import __version__
        return (cfg.runners.get(self.name) or {}).get("image") \
            or f"ghcr.io/umbralcalc/robert-claude-code:{__version__}"

    def hosts(self, cfg: Config) -> list[str]:
        return ANTHROPIC_HOSTS + super().hosts(cfg)

    def secrets(self, cfg: Config) -> list[str]:
        return super().secrets(cfg) or ["ANTHROPIC_API_KEY"]

    def mounts(self, cfg: Config, project: str) -> dict[Path, str]:
        return {sandbox.state_dir(project, self.name): "/state"}

    def command(self, cfg, project, message, first):
        model = (cfg.runners.get(self.name) or {}).get("model") or self.model
        return ["robert", "cloud", "agent", "claude-code", "--model", model,
                *([] if first else ["--continue"]), "--", message]

    def parse(self, line: str) -> Iterator[Event]:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            if line.strip():
                yield Event("text", line.rstrip("\n"))
            return
        if msg.get("type") == "assistant":
            for block in (msg.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text"):
                    yield Event("text", block["text"], raw=msg)
                elif block.get("type") == "tool_use":
                    yield Event("tool", describe(block.get("input")), block.get("name", ""), msg)
        elif msg.get("type") == "result" and msg.get("is_error"):
            yield Event("error", str(msg.get("result", "")), raw=msg)


class Command(CliRunner):
    """Any agent CLI. Configure it under `runners.command` in the cloud config:
    `image` (built on the robert image), `command` (argv with `{message}` where the
    message goes), optional `continue_command` for later turns, `hosts` (its model
    API) and `env` (its API key variable names)."""

    name = "command"

    def _conf(self, cfg: Config) -> dict[str, Any]:
        conf = cfg.runners.get(self.name) or {}
        if not conf.get("command") or not conf.get("image"):
            raise MethodError("configure runners.command (image, command) in "
                              "~/.robert/cloud/config.yaml first")
        return conf

    def command(self, cfg, project, message, first):
        conf = self._conf(cfg)
        template = conf["command"] if first else conf.get("continue_command", conf["command"])
        return [part.replace("{message}", message) for part in template]


RUNNERS: dict[str, Runner] = {r.name: r for r in (ManagedAgents(), ClaudeCode(), Command())}


def get(name: str) -> Runner:
    if name not in RUNNERS:
        raise MethodError(f"unknown runner `{name}`; choose from {', '.join(RUNNERS)}")
    return RUNNERS[name]


def describe(data: Any) -> str:
    """One line for a tool call: the command for a shell tool, else the path."""
    if not isinstance(data, dict):
        return ""
    detail = data.get("command") or data.get("file_path") or data.get("path") \
        or data.get("pattern") or json.dumps(data)[:80]
    lines = str(detail).splitlines()
    return lines[0][:120] if lines else ""
