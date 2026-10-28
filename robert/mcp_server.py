"""The MCP face of the tool registry.

MCP is the common denominator for typed tool calls, so every agent (Claude Code,
Cursor, anything else) gets identical enforcement: the gates live here, never in
agent-specific hooks.
"""

from __future__ import annotations

import json
from typing import Any

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from . import __version__
from .project import MethodError
from .tools import BY_NAME, TOOLS

INSTRUCTIONS = (
    "robert drives a stochadex simulation project through the discovery-and-warrant loop: "
    "pose → conjecture → confront → test → (discover | compress) → warrant → query → revise. "
    "Call `status` first. Write model/sim.yaml with the stochadex-model skill before "
    "`conjecture`. A failed gate is not an error: report the failed check, propose the next "
    "step and let the user decide. Log every redirection with `intervene`. Never state a "
    "number that did not come from a run's output."
)


async def _list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[
        types.Tool(name=t.name, description=t.description, input_schema=t.input_schema)
        for t in TOOLS
    ])


async def _call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    tool = BY_NAME.get(params.name)
    if tool is None:
        return _error(f"unknown tool `{params.name}`")
    try:
        # Tools shell out to stochadex; keep the event loop free while they run.
        result = await anyio.to_thread.run_sync(tool.call, dict(params.arguments or {}))
    except MethodError as e:
        return _error(str(e))
    except TypeError as e:
        return _error(f"bad arguments for `{tool.name}`: {e}")
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))],
        structured_content=json.loads(json.dumps(result, default=str)),
    )


def _error(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                is_error=True)


def build() -> Server:
    return Server("robert", version=__version__, instructions=INSTRUCTIONS,
                  on_list_tools=_list_tools, on_call_tool=_call_tool)


def serve() -> None:
    server = build()

    async def main() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(main)
