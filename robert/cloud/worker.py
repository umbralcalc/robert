"""`robert cloud worker`: the entrypoint inside a per-session sandbox.

It serves exactly one claimed work item with Anthropic's EnvironmentWorker and
exits. The launcher passes the work item's IDs, the environment key and the
per-session secret in as ANTHROPIC_* environment variables. Stopping the
container with SIGTERM cancels the worker, which still uploads memory changes.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

# Skills download here, beside the project (which is mounted at /workspace/<project>),
# so they never land in the project repo.
WORKDIR = "/workspace"


async def _main() -> None:
    from anthropic import AsyncAnthropic
    from anthropic.lib.environments import EnvironmentWorker

    key = os.environ["ANTHROPIC_ENVIRONMENT_KEY"]
    async with AsyncAnthropic(auth_token=key) as client:
        task = asyncio.create_task(EnvironmentWorker(client, workdir=WORKDIR).handle_item())
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, task.cancel)
        with contextlib.suppress(asyncio.CancelledError):
            await task


def main() -> None:
    asyncio.run(_main())
