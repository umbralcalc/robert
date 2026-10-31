"""The sandbox every runner shares: the project repo, the egress proxy, and one
locked-down container per session or turn.

The runner decides only which image runs, which command, and which extra hosts
and secrets it needs. Everything that makes a run comparable across agents is
here: the same image base, the same filesystem and process limits, the same
network with the same allowlist rules, and the same repo handling (cloned and
pushed on the host, so no GitHub credential enters a sandbox).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..project import MethodError
from . import Config, home
from .egress import PROXY_DOCKERFILE, PROXY_PORT, allowlist, allowlist_text, squid_conf

NETWORK = "robert-sandbox"
PROXY = "robert-egress"
PROXY_IMAGE = "robert-egress:local"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    if not shutil.which("docker"):
        raise MethodError("docker is not on PATH")
    return subprocess.run(["docker", *args], check=check, text=True, capture_output=True)


def _exists(kind: str, name: str) -> bool:
    return _docker(kind, "inspect", name, check=False).returncode == 0


def egress_dir() -> Path:
    return home() / "egress"


def active_projects(cfg: Config) -> list[Path]:
    return [p for p in cfg.projects.iterdir() if (p / ".git").exists()] \
        if cfg.projects.exists() else []


def ensure_egress(projects: list[Path], extra_hosts: list[str] | None = None) -> list[str]:
    """Start (or refresh) the internal network and its allowlisting proxy."""
    d = egress_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "robert.conf").write_text(squid_conf())
    hosts = sorted(set(allowlist(projects)) | set(extra_hosts or []))
    (d / "allowlist.txt").write_text(allowlist_text(hosts))

    if not _exists("network", NETWORK):
        _docker("network", "create", "--internal", NETWORK)
    if not _exists("image", PROXY_IMAGE):
        subprocess.run(["docker", "build", "-t", PROXY_IMAGE, "-"], input=PROXY_DOCKERFILE,
                       text=True, check=True, capture_output=True)
    if not _exists("container", PROXY):
        _docker("run", "-d", "--name", PROXY, "--restart", "unless-stopped",
                "-v", f"{d / 'robert.conf'}:/etc/squid/robert.conf:ro",
                "-v", f"{d / 'allowlist.txt'}:/etc/squid/allowlist.txt:ro",
                PROXY_IMAGE)
        _docker("network", "connect", NETWORK, PROXY)
    else:
        _docker("exec", PROXY, "squid", "-k", "reconfigure", "-f", "/etc/squid/robert.conf",
                check=False)
    return hosts


def container_args(image: str, name: str, project: str, project_dir: Path,
                   env_names: list[str], command: list[str],
                   mounts: dict[Path, str] | None = None) -> list[str]:
    """`docker run` arguments for one sandbox. Secret values never appear here:
    `env_names` are passed by name and read from the caller's environment."""
    proxy = f"http://{PROXY}:{PROXY_PORT}"
    args = [
        "run", "--rm", "-i", "--name", name, "--network", NETWORK,
        "--read-only", "--tmpfs", "/tmp", "--tmpfs", "/workspace:uid=65532,gid=65532",
        "--tmpfs", "/mnt/memory:uid=65532,gid=65532",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "512", "--memory", "4g", "--cpus", "2",
        "-v", f"{project_dir}:/workspace/{project}",
        "-w", f"/workspace/{project}",
        "-e", f"HTTPS_PROXY={proxy}", "-e", f"HTTP_PROXY={proxy}",
        "-e", f"https_proxy={proxy}", "-e", f"http_proxy={proxy}",
        "-e", "NO_PROXY=localhost,127.0.0.1", "-e", "HOME=/tmp",
        "-e", "GIT_AUTHOR_NAME=robert", "-e", "GIT_AUTHOR_EMAIL=robert@localhost",
        "-e", "GIT_COMMITTER_NAME=robert", "-e", "GIT_COMMITTER_EMAIL=robert@localhost",
        "-e", "GIT_CONFIG_COUNT=1", "-e", "GIT_CONFIG_KEY_0=safe.directory",
        "-e", "GIT_CONFIG_VALUE_0=*",
    ]
    for host_path, target in (mounts or {}).items():
        args += ["-v", f"{host_path}:{target}"]
    for env_name in env_names:
        args += ["-e", env_name]
    return [*args, "--entrypoint", command[0], image, *command[1:]]


def ensure_repo(cfg: Config, project: str, repo: str) -> Path:
    """Clone the project repo into the host workspace, or bring it up to date."""
    path = cfg.projects / project
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["gh", "repo", "clone", repo, str(path)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise MethodError(f"could not clone {repo}: {r.stderr.strip()}")
    else:
        subprocess.run(["git", "-C", str(path), "pull", "--ff-only", "-q"], check=False,
                       capture_output=True)
    return path


def push(path: Path) -> str:
    """Push what the agent committed, with the host's git credentials."""
    ahead = subprocess.run(["git", "-C", str(path), "rev-list", "--count", "@{u}..HEAD"],
                           capture_output=True, text=True)
    if ahead.returncode != 0 or ahead.stdout.strip() in ("", "0"):
        return "nothing to push"
    r = subprocess.run(["git", "-C", str(path), "push", "-q"], capture_output=True, text=True)
    return "pushed" if r.returncode == 0 else f"push failed: {r.stderr.strip()[-300:]}"


def state_dir(project: str, runner: str) -> Path:
    """Per-project, per-runner state that outlives a container (a CLI agent's
    conversation history), kept on the host beside the egress config."""
    path = home() / "state" / project / runner
    path.mkdir(parents=True, exist_ok=True)
    return path
