"""`robert cloud host`: the launcher for the managed-agents runner.

Anthropic runs that runner's agent loop; this host runs its tools. It long-polls
the self-hosted environment's work queue (outbound only), and for each session it
reads the session's `robert_project` / `robert_repo` metadata with the host's own
credentials, then runs one sandbox from the shared `sandbox` module, which clones
the repo, opens egress to the project's data hosts, and pushes afterwards.
CLI runners don't need this process: `robert cloud chat` starts their sandboxes.
"""

from __future__ import annotations

import asyncio
import os

from ..project import MethodError
from . import Config
from . import sandbox

WORKER = ["robert", "cloud", "worker"]
ENV = ["ANTHROPIC_SESSION_ID", "ANTHROPIC_WORK_ID", "ANTHROPIC_ENVIRONMENT_ID",
       "ANTHROPIC_ENVIRONMENT_KEY", "ANTHROPIC_WORK_SECRET", "ANTHROPIC_BASE_URL"]


async def _serve_one(cfg: Config, control, work, environment_key: str) -> None:
    session_id = work.data.id
    session = await control.beta.sessions.retrieve(session_id)
    meta = session.metadata or {}
    project, repo = meta.get("robert_project"), meta.get("robert_repo")
    if not project or not repo:
        print(f"[{session_id}] no robert_project/robert_repo metadata; refusing")
        await control.beta.environments.work.stop(work.id, environment_id=work.environment_id)
        return
    path = await asyncio.to_thread(sandbox.ensure_repo, cfg, project, repo)
    hosts = await asyncio.to_thread(sandbox.ensure_egress, sandbox.active_projects(cfg))
    print(f"[{session_id}] {project}: sandbox starting; egress to {', '.join(hosts)}")
    env = {
        "ANTHROPIC_SESSION_ID": session_id,
        "ANTHROPIC_WORK_ID": work.id,
        "ANTHROPIC_ENVIRONMENT_ID": work.environment_id,
        "ANTHROPIC_ENVIRONMENT_KEY": environment_key,
        "ANTHROPIC_WORK_SECRET": work.secret or "",
        "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL", ""),
    }
    names = [n for n in ENV if env.get(n)]
    args = sandbox.container_args(cfg.image, f"robert-{session_id}", project, path,
                                  names, WORKER)
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, env={**os.environ, **{n: env[n] for n in names}},
        stdin=asyncio.subprocess.DEVNULL)
    code = await proc.wait()
    print(f"[{session_id}] sandbox exited {code}; "
          f"{await asyncio.to_thread(sandbox.push, path)}")


async def _run(environment_key: str) -> None:
    from anthropic import AsyncAnthropic

    cfg = Config.load()
    if not cfg.environment_id:
        raise MethodError("run `robert cloud configure --lock claude-lock.json` first")
    cfg.projects.mkdir(parents=True, exist_ok=True)
    sandbox.ensure_egress(sandbox.active_projects(cfg))
    # Two clients: the environment key only claims work; reading session
    # metadata uses the host's own credentials, which never enter a sandbox.
    control = AsyncAnthropic()
    queue = AsyncAnthropic(auth_token=environment_key)
    running: set[asyncio.Task] = set()
    print(f"robert cloud host: polling {cfg.environment_id}; workspace {cfg.projects}")
    async for work in queue.beta.environments.work.poller(
            environment_id=cfg.environment_id, environment_key=environment_key,
            auto_stop=False):
        if work.data.type != "session":
            continue
        task = asyncio.create_task(_serve_one(cfg, control, work, environment_key))
        running.add(task)
        task.add_done_callback(running.discard)


def run() -> None:
    key = os.environ.get("ANTHROPIC_ENVIRONMENT_KEY")
    if not key:
        raise MethodError("set ANTHROPIC_ENVIRONMENT_KEY (generate it in the Console on "
                          "the robert environment's page)")
    try:
        asyncio.run(_run(key))
    except KeyboardInterrupt:
        pass
