"""robert in the cloud: one locked-down sandbox, any agent.

- `sandbox`: what every run shares. The robert image, the egress proxy whose
  allowlist comes from each project's `data/licences.yaml`, and the project repo,
  cloned and pushed on the host so the GitHub credential never enters a container.
- `runners`: what drives the work inside the sandbox, behind one interface
  (`turn(message) -> events`). `managed-agents` (Anthropic runs the loop; our
  host runs the tools), `claude-code` (Claude Code headless in the sandbox), and
  `command` (any agent CLI, from a template in the config).
- `chat`: `robert cloud new` / `robert cloud chat`, the same for every runner.
- `host` / `worker`: the Managed Agents launcher and its in-sandbox worker.
- `agent`: `robert cloud agent <runner>`, the in-sandbox entry for CLI agents.

Every runner drives robert through the same `robert` CLI with the same
instructions (`instructions.md`), so across runners only the agent differs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .. import deps
from ..project import MethodError

IMAGE = "ghcr.io/umbralcalc/robert"
AGENT_FILE = "cloud/agents/robert/agent.md"
ENVIRONMENT_FILE = "cloud/agents/robert/environment.yaml"
INSTRUCTIONS = Path(__file__).with_name("instructions.md")


def home() -> Path:
    return deps.home() / "cloud"


def instructions() -> str:
    """The agent instructions every runner gets (also the Managed Agents system prompt)."""
    return INSTRUCTIONS.read_text()


@dataclass
class Config:
    agent_id: str = ""
    environment_id: str = ""
    github_owner: str = "umbralcalc"
    image: str = ""
    workspace: str = ""
    # Per-runner settings, e.g. {"claude-code": {"image": ...},
    # "command": {"image": ..., "command": [...], "hosts": [...], "env": [...]}}
    runners: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def projects(self) -> Path:
        return Path(self.workspace or home() / "projects").expanduser()

    @classmethod
    def load(cls) -> "Config":
        path = home() / "config.yaml"
        if not path.exists():
            raise MethodError(f"no cloud config at {path}: run `robert cloud configure`")
        return cls(**(yaml.safe_load(path.read_text()) or {}))

    def save(self) -> Path:
        path = home() / "config.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self.__dict__, sort_keys=False))
        return path


def ids_from_lock(lock: dict[str, Any]) -> tuple[str, str]:
    """The agent and environment IDs `ant apply` recorded for cloud/agents/robert."""
    resources = lock.get("resources", {})

    def find(rel: str) -> str:
        for key, value in resources.items():
            if key.lstrip("./") == rel:
                return value["id"]
        raise MethodError(f"claude-lock.json has no entry for {rel}; run `ant apply` first")

    return find(AGENT_FILE), find(ENVIRONMENT_FILE)


def configure(lock: str | None = None, github_owner: str = "umbralcalc",
              image: str | None = None, workspace: str | None = None) -> dict[str, Any]:
    """Write ~/.robert/cloud/config.yaml, keeping any runner settings already there.
    `lock` is needed only for the managed-agents runner."""
    from .. import __version__
    try:
        cfg = Config.load()
    except MethodError:
        cfg = Config()
    if lock:
        cfg.agent_id, cfg.environment_id = ids_from_lock(json.loads(Path(lock).read_text()))
    cfg.github_owner = github_owner
    cfg.image = image or cfg.image or f"{IMAGE}:{__version__}"
    cfg.workspace = workspace or cfg.workspace or str(home() / "projects")
    return {"written": str(cfg.save()), **cfg.__dict__}


# --- the project registry: which runner each project uses, and its state --------


def _registry() -> Path:
    return home() / "projects.yaml"


def projects() -> dict[str, dict[str, Any]]:
    path = _registry()
    return (yaml.safe_load(path.read_text()) if path.exists() else None) or {}


def project(name: str) -> dict[str, Any]:
    entry = projects().get(name)
    if not entry:
        raise MethodError(f"no cloud project `{name}`; start one with `robert cloud new {name}`")
    return entry


def save_project(name: str, entry: dict[str, Any]) -> None:
    data = projects()
    data[name] = entry
    path = _registry()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=True))
