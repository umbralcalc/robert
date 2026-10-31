"""`robert cloud new` and `robert cloud chat`: talk to a project's agent from a
terminal, whichever runner drives it.

`new` creates the project's private GitHub repo, sets up the runner's
conversation and records both in ~/.robert/cloud/projects.yaml; `chat` reopens
it. Each turn prints the agent's messages and a one-line summary of each tool
call, and asks you before any call the runner flags for approval.
"""

from __future__ import annotations

import subprocess
import sys

from ..project import MethodError
from . import Config, project, save_project
from .runners import Event, get

CONSOLE = "https://platform.claude.com/workspaces/default/sessions/{}"


def kickoff(name: str, description: str) -> str:
    return (f"This is a new robert project, `{name}`; its repo is at /workspace/{name}. "
            f"The question in my words: {description}\n\nStart with `robert --json "
            "status` there; the repo is empty, so interview me for the domain and run "
            f"`robert init --path /workspace/{name}`, then help me pose the claim.")


def new(name: str, description: str, runner: str) -> None:
    cfg = Config.load()
    driver = get(runner)
    repo = f"{cfg.github_owner}/{name}"
    made = subprocess.run(["gh", "repo", "create", repo, "--private", "--add-readme",
                           "--description", f"robert project: {description}"[:350]],
                          capture_output=True, text=True)
    if made.returncode != 0:
        raise MethodError(f"could not create {repo}: {made.stderr.strip()}")
    entry = {"runner": runner, "repo": repo, **driver.start(cfg, name, repo)}
    save_project(name, entry)
    print(f"Created {repo}; runner {runner}")
    if entry.get("session_id"):
        print(CONSOLE.format(entry["session_id"]))
    converse(cfg, name, entry, first=kickoff(name, description))


def chat(name: str) -> None:
    cfg = Config.load()
    entry = project(name)
    print(f"{name}: runner {entry['runner']}, repo {entry['repo']}")
    if entry.get("session_id"):
        print(CONSOLE.format(entry["session_id"]))
    converse(cfg, name, entry)


def show(event: Event) -> None:
    if event.kind == "text" and event.text:
        print(event.text, flush=True)
    elif event.kind == "tool":
        print(f"  · {event.tool}: {event.text}", flush=True)
    elif event.kind == "error":
        print(f"  ! {event.text}", file=sys.stderr, flush=True)
    elif event.kind == "ended":
        print("--- session ended ---")


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def confirm_on_terminal(event: Event) -> bool:
    return _ask(f"    allow {event.tool}: {event.text}? [y/N] ").strip().lower() == "y"


def converse(cfg: Config, name: str, entry: dict, first: str | None = None) -> None:
    driver = get(entry["runner"])
    message = first
    while True:
        if message is None:
            message = _ask("\nyou> ").strip()
            if not message:
                return
        ended = False
        for event in driver.turn(cfg, name, entry, message, confirm_on_terminal):
            show(event)
            ended = ended or event.kind == "ended"
        save_project(name, entry)
        if ended or not sys.stdin.isatty():
            return
        message = None
