"""`robert cloud new` and `robert cloud chat`: talk to a project's agent from a
terminal, whichever runner drives it.

`new` starts a project as a local git repo in the host workspace, sets up the
runner's conversation and records both in ~/.robert/cloud/projects.yaml; `chat`
reopens it. Nothing goes to GitHub unless asked: `new --github`, or `publish`
later. Each turn prints the agent's messages and a one-line summary of each tool
call, and asks you before any call the runner flags for approval.
"""

from __future__ import annotations

import sys

from ..project import MethodError
from . import Config, project, projects, save_project
from . import sandbox
from .runners import Event, get

CONSOLE = "https://platform.claude.com/workspaces/default/sessions/{}"


def kickoff(name: str, description: str) -> str:
    return (f"This is a new robert project, `{name}`; its repo is at /workspace/{name}. "
            f"The question in my words: {description}\n\nStart with `robert --json "
            "status` there; the repo is empty, so interview me for the domain and run "
            f"`robert init --path /workspace/{name}`, then help me pose the claim.")


def new(name: str, description: str, runner: str, github: bool = False) -> None:
    """Start a project: a local git repo in the host workspace, unless `github`
    asks for a private GitHub repo too (which `publish` can also add later)."""
    cfg = Config.load()
    driver = get(runner)
    started = projects().get(name)
    if started and (started.get("turns") or started.get("session_id")):
        raise MethodError(f"`{name}` is already a cloud project; reopen it with "
                          f"`robert cloud chat {name}`")
    path = sandbox.ensure_repo(cfg, name, (started or {}).get("repo"))
    repo = (started or {}).get("repo")
    if github and not repo:
        repo = f"{cfg.github_owner}/{name}"
        print(f"Published to {sandbox.publish(path, repo)}")
    entry = {"runner": runner, **({"repo": repo} if repo else {}),
             **driver.start(cfg, name, repo)}
    save_project(name, entry)
    print(f"Project {name}: {path} ({'GitHub ' + repo if repo else 'local only'}); "
          f"runner {runner}")
    if entry.get("session_id"):
        print(CONSOLE.format(entry["session_id"]))
    converse(cfg, name, entry, first=kickoff(name, description))


def chat(name: str) -> None:
    cfg = Config.load()
    entry = project(name)
    where = f"GitHub {entry['repo']}" if entry.get("repo") else "local only"
    print(f"{name}: runner {entry['runner']}, {where}")
    if entry.get("session_id"):
        print(CONSOLE.format(entry["session_id"]))
    converse(cfg, name, entry)


def publish(name: str, owner: str | None = None) -> None:
    """Push a local project to a new private GitHub repo. From then on the host
    pushes after every turn."""
    cfg = Config.load()
    entry = project(name)
    if entry.get("repo"):
        raise MethodError(f"`{name}` is already on GitHub as {entry['repo']}")
    repo = f"{owner or cfg.github_owner}/{name}"
    url = sandbox.publish(sandbox.ensure_repo(cfg, name), repo)
    entry["repo"] = repo
    save_project(name, entry)
    print(f"Published {name} to {url}")


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
