"""`robert`: the CLI face of the tool registry.

Arguments are generated from each tool's JSON Schema: strings and numbers are
flags, string lists repeat (`--conditions a --conditions b`), booleans are
`--x/--no-x`, and objects take JSON. Exit codes: 0 gate passed, 1 gate failed,
2 the request could not be carried out.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import yaml

from . import __version__
from .project import MethodError
from .tools import TOOLS


def _add_arg(p: argparse.ArgumentParser, name: str, schema: dict[str, Any],
             required: bool) -> None:
    flag = "--" + name.replace("_", "-")
    t = schema.get("type")
    kw: dict[str, Any] = {"dest": name, "help": schema.get("description")}
    if t == "boolean":
        p.add_argument(flag, action=argparse.BooleanOptionalAction, default=None, **kw)
        return
    if t == "array" and schema.get("items", {}).get("type") == "string":
        kw.update(action="append")
    elif t in ("array", "object"):
        kw.update(type=json.loads, metavar="JSON")
    elif t == "number":
        kw.update(type=float)
    if "enum" in schema:
        kw["choices"] = schema["enum"]
    p.add_argument(flag, required=required, **kw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="robert", description="The AI simulation scientist's method CLI.")
    parser.add_argument("--version", action="version", version=f"robert {__version__}")
    parser.add_argument("--json", action="store_true", help="print JSON instead of YAML")
    sub = parser.add_subparsers(dest="command", required=True)
    for tool in TOOLS:
        p = sub.add_parser(tool.name, help=tool.description.split(". ")[0],
                           description=tool.description)
        schema = tool.input_schema
        for name, prop in schema["properties"].items():
            _add_arg(p, name, prop, name in tool.required)
    mcp = sub.add_parser("mcp", help="Serve every tool over MCP (stdio by default)")
    mcp.add_argument("--http", action="store_true",
                     help="serve streamable HTTP at /mcp instead of stdio")
    mcp.add_argument("--host", default="127.0.0.1",
                     help="bind address; anything but loopback requires ROBERT_MCP_TOKEN")
    mcp.add_argument("--port", type=int, default=8765)
    setup = sub.add_parser("setup", help="Install the locked stochadex and register agents")
    setup.add_argument("--stochadex", metavar="VERSION",
                       help="stochadex version to install; default: the lock's")
    setup.add_argument("--accelerated", action="store_true",
                       help="the BLAS + DuckDB build instead of the portable one")
    setup.add_argument("--agents", nargs="+", metavar="AGENT",
                       help="agents to register (claude, cursor); default: all found")
    setup.add_argument("--no-agents", action="store_true", help="install stochadex only")
    sub.add_parser("adapters", help="Render agent adapters from the skills source")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    try:
        if ns.command == "mcp":
            from .mcp_server import serve, serve_http
            if ns.http:
                serve_http(ns.host, ns.port)
            else:
                serve()
            return 0
        if ns.command == "adapters":
            from .adapters import render
            for path in render():
                print(path)
            return 0
        if ns.command == "setup":
            from .setup import setup
            result = setup(ns.stochadex, ns.accelerated, ns.agents, ns.no_agents)
        else:
            tool = next(t for t in TOOLS if t.name == ns.command)
            args = {k: v for k, v in vars(ns).items()
                    if k not in ("command", "json") and v is not None}
            result = tool.call(args)
    except MethodError as e:
        print(f"robert {ns.command}: {e}", file=sys.stderr)
        return 2
    if ns.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True, width=100), end="")
    gate = result.get("gate")
    return 1 if (gate and not gate["passed"]) or result.get("ok") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
