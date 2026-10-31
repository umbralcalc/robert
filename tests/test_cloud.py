"""The cloud pieces that can be checked without Docker or Anthropic credentials."""

import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import yaml

from robert.cloud import AGENT_FILE, ENVIRONMENT_FILE, Config, ids_from_lock, instructions
from robert.cloud.egress import allowlist, project_hosts, squid_conf
from robert.cloud.runners import RUNNERS, ClaudeCode, Command, ManagedAgents, describe
from robert.cloud.sandbox import NETWORK, container_args
from robert.project import MethodError

from .conftest import REPO


def test_licences_open_the_network(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/licences.yaml").write_text(yaml.safe_dump({
        "obs": {"licence": "OGL-3.0", "source": "https://environment.data.gov.uk/hydrology/x"},
        "met": {"licence": "CC-BY-4.0", "source": "x", "hosts": ["Data.Example.org"]},
        "synthetic": {"licence": "CC0-1.0", "source": "made by data/truth.yaml"},
    }))
    assert project_hosts(tmp_path) == ["data.example.org", "environment.data.gov.uk"]
    assert allowlist([tmp_path])[0] == "api.anthropic.com"


def test_proxy_refuses_everything_else():
    conf = squid_conf()
    assert 'acl allowed dstdomain "/etc/squid/allowlist.txt"' in conf
    assert conf.index("http_access allow allowed") < conf.index("http_access deny all")


def test_ids_from_lock_accepts_either_path_spelling():
    lock = {"resources": {f"./{AGENT_FILE}": {"id": "agent_1"},
                          ENVIRONMENT_FILE: {"id": "env_1"}}}
    assert ids_from_lock(lock) == ("agent_1", "env_1")


def test_every_sandbox_is_locked_down_and_keeps_secrets_out_of_argv(tmp_path):
    args = container_args("img:1", "robert-x", "proj", tmp_path,
                          ["ANTHROPIC_API_KEY"], ["robert", "cloud", "worker"],
                          {tmp_path / "state": "/state"})
    joined = " ".join(args)
    for flag in ("--read-only", "--cap-drop ALL", "no-new-privileges", f"--network {NETWORK}",
                 "-e ANTHROPIC_API_KEY ", f"{tmp_path}:/workspace/proj",
                 f"{tmp_path / 'state'}:/state"):
        assert flag in joined
    assert "ANTHROPIC_API_KEY=" not in joined
    assert args[args.index("--entrypoint") + 1:] == ["robert", "img:1", "cloud", "worker"]


def test_runners_share_one_interface():
    assert set(RUNNERS) == {"managed-agents", "claude-code", "command"}
    cfg = Config(image="robert:x")
    cc = ClaudeCode()
    assert "api.anthropic.com" in cc.hosts(cfg) and cc.secrets(cfg) == ["ANTHROPIC_API_KEY"]
    first = cc.command(cfg, "p", "hello", first=True)
    later = cc.command(cfg, "p", "-again", first=False)
    assert "--continue" not in first and later[-3:] == ["--continue", "--", "-again"]


def test_claude_code_stream_json_becomes_events():
    lines = [
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Checking status."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "robert --json status"}}]}}),
        json.dumps({"type": "result", "is_error": True, "result": "Invalid API key"}),
        "not json",
    ]
    events = [e for line in lines for e in ClaudeCode().parse(line)]
    assert [(e.kind, e.tool, e.text) for e in events] == [
        ("text", "", "Checking status."), ("tool", "Bash", "robert --json status"),
        ("error", "", "Invalid API key"), ("text", "", "not json")]


def test_command_runner_fills_in_the_message():
    cfg = Config(runners={"command": {"image": "my-agent:1",
                                      "command": ["agent", "run", "{message}"],
                                      "continue_command": ["agent", "resume", "{message}"]}})
    assert Command().command(cfg, "p", "hi", first=True) == ["agent", "run", "hi"]
    assert Command().command(cfg, "p", "hi", first=False) == ["agent", "resume", "hi"]
    with pytest.raises(MethodError, match="runners.command"):
        Command().command(Config(), "p", "hi", first=True)


class FakeStream:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return iter(self.events)

    def __exit__(self, *a):
        return False


def test_managed_agents_turn_asks_before_a_flagged_call(monkeypatch):
    sent = []
    events = [
        NS(type="agent.message", content=[NS(type="text", text="Running status.")]),
        NS(type="agent.tool_use", id="tu_1", name="bash", input={"command": "rm -rf x"},
           evaluated_permission="ask"),
        NS(type="session.status_idle", stop_reason=NS(type="requires_action")),
        NS(type="session.status_idle", stop_reason=NS(type="end_turn")),
    ]
    client = NS(beta=NS(sessions=NS(events=NS(
        stream=lambda session_id: FakeStream(events),
        send=lambda session_id, events: sent.append(events)))))
    monkeypatch.setattr(ManagedAgents, "_client", lambda self: client)
    out = list(ManagedAgents().turn(Config(), "p", {"session_id": "s"}, "hello",
                                    confirm=lambda e: False))
    assert [e.kind for e in out] == ["text", "tool", "done"]
    assert sent[0][0]["type"] == "user.message"
    assert sent[1] == [{"type": "user.tool_confirmation", "tool_use_id": "tu_1",
                        "result": "deny"}]


def test_tool_calls_describe_as_one_line():
    assert describe({"command": "robert --json status\nmore"}) == "robert --json status"
    assert describe({"file_path": "/workspace/p/claim.yaml"}) == "/workspace/p/claim.yaml"


def _frontmatter(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---", 2)[1])


def test_agent_file_is_well_formed_and_uses_the_shared_instructions():
    agent = _frontmatter(REPO / AGENT_FILE)
    for skill in agent["skills"]:
        assert ((REPO / AGENT_FILE).parent / skill / "SKILL.md").resolve().is_file()
    configs = {c["name"]: c["enabled"] for c in agent["tools"][0]["configs"]}
    assert configs == {"web_fetch": False, "web_search": False}
    assert (REPO / AGENT_FILE).read_text().endswith(instructions())
    env = yaml.safe_load((REPO / ENVIRONMENT_FILE).read_text())
    assert env["config"] == {"type": "self_hosted"}


def test_configure_keeps_runner_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBERT_HOME", str(tmp_path))
    from robert.cloud import configure
    Config(runners={"command": {"image": "a"}}).save()
    out = configure(github_owner="me")
    assert out["runners"] == {"command": {"image": "a"}} and out["github_owner"] == "me"


@pytest.mark.parametrize("skill", sorted((REPO / "skills").glob("*/SKILL.md")),
                         ids=lambda p: p.parent.name)
def test_skill_frontmatter_is_strict_yaml(skill):
    front = _frontmatter(skill)
    assert front["name"] == skill.parent.name and front["description"]


def test_projects_are_local_git_repos_by_default(tmp_path):
    import subprocess
    from robert.cloud.sandbox import ensure_repo, push
    cfg = Config(workspace=str(tmp_path / "projects"))
    path = ensure_repo(cfg, "trial")
    log = subprocess.run(["git", "-C", str(path), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    remotes = subprocess.run(["git", "-C", str(path), "remote"],
                             capture_output=True, text=True).stdout
    assert "Start the project" in log and remotes.strip() == ""
    assert push(path) == "kept locally"
    (path / "notes.md").write_text("kept\n")
    assert ensure_repo(cfg, "trial") == path and (path / "notes.md").exists()


def test_docker_not_running_is_a_plain_error(monkeypatch):
    import subprocess
    from robert.cloud import sandbox
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(sandbox.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, "", "failed to connect to the docker API"))
    with pytest.raises(MethodError, match="Docker isn't running"):
        sandbox.ensure_egress([])
    with pytest.raises(MethodError, match="failed to connect to the docker API"):
        sandbox._docker("network", "create", "x")


def test_a_running_proxy_reloads_its_allowlist_with_hup(monkeypatch, tmp_path):
    from robert.cloud import sandbox
    calls = []
    monkeypatch.setenv("ROBERT_HOME", str(tmp_path))
    monkeypatch.setattr(sandbox, "ensure_docker", lambda: None)
    monkeypatch.setattr(sandbox, "_exists", lambda kind, name: True)
    monkeypatch.setattr(sandbox, "_docker", lambda *a, **k: calls.append(a))
    hosts = sandbox.ensure_egress([], ["api.example.com"])
    assert "api.example.com" in hosts
    assert calls == [("kill", "--signal", "HUP", sandbox.PROXY)]
    assert "api.example.com" in (tmp_path / "cloud/egress/allowlist.txt").read_text()


class SlowProc:
    """A stand-in for the docker process: emits lines with gaps between them."""

    def __init__(self, lines, gap):
        self.lines, self.gap = lines, gap

    @property
    def stdout(self):
        import time
        for line in self.lines:
            time.sleep(self.gap)
            yield line


def test_quiet_turns_tick_and_long_ones_stop():
    from robert.cloud.runners import TurnTimeout, stream_with_progress
    out = list(stream_with_progress(SlowProc(["a\n", "b\n"], 0.15), 1, every=0.05))
    assert out[-1] == "b\n" and any(getattr(o, "kind", "") == "progress" for o in out)
    with pytest.raises(TurnTimeout):
        list(stream_with_progress(SlowProc(["a\n"] * 50, 0.05), 0.002, every=0.02))


def test_ctrl_c_stops_the_turn_and_returns_to_the_prompt(monkeypatch, capsys):
    from robert.cloud import chat
    from robert.cloud.runners import Event

    def turn():
        try:
            yield Event("text", "working")
            yield Event("text", "more")
        except KeyboardInterrupt:
            yield Event("error", "The turn ended early because you stopped it.")
            yield Event("done")

    shown = []

    def show(event):
        shown.append(event.text)
        if event.text == "working":
            raise KeyboardInterrupt

    monkeypatch.setattr(chat, "show", show)
    assert chat.run_turn(turn()) is True
    assert shown == ["working", "The turn ended early because you stopped it.", ""]


def test_an_interrupted_turn_resumes_with_a_note(monkeypatch, tmp_path):
    from robert.cloud import runners
    sent = {}
    monkeypatch.setattr(runners.sandbox, "ensure_repo", lambda *a: tmp_path)
    monkeypatch.setattr(runners.sandbox, "ensure_egress", lambda *a: ["api.anthropic.com"])
    monkeypatch.setattr(runners.sandbox, "active_projects", lambda cfg: [])
    monkeypatch.setattr(runners.sandbox, "push", lambda path: "kept locally")
    monkeypatch.setattr(runners.sandbox, "container_args",
                        lambda image, name, project, path, env, command, mounts:
                        sent.setdefault("command", command) and ["true"])

    class Done:
        stdout, stderr = iter([]), None

        def wait(self):
            return 0

    monkeypatch.setattr(runners.subprocess, "Popen", lambda *a, **k: Done())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    entry = {"runner": "claude-code", "turns": 2, "interrupted": True}
    list(runners.ClaudeCode().turn(Config(), "p", entry, "carry on", lambda e: False))
    assert sent["command"][-1].startswith("[Your previous turn was stopped")
    assert "--continue" in sent["command"]
    assert entry == {"runner": "claude-code", "turns": 3}
