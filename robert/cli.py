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


class _JsonList(list):
    """One flag value that was a JSON list of strings."""


def _list_item(value: str) -> str | _JsonList:
    """A string-list flag takes one item per flag, or a whole JSON list once."""
    if value.lstrip().startswith("["):
        try:
            items = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(items, list) and all(isinstance(i, str) for i in items):
            return _JsonList(items)
    return value


def _flatten(values: list) -> list[str]:
    out: list[str] = []
    for v in values:
        out.extend(v) if isinstance(v, _JsonList) else out.append(v)
    return out


def _add_arg(p: argparse.ArgumentParser, name: str, schema: dict[str, Any],
             required: bool) -> None:
    flag = "--" + name.replace("_", "-")
    t = schema.get("type")
    kw: dict[str, Any] = {"dest": name, "help": schema.get("description")}
    if t == "boolean":
        p.add_argument(flag, action=argparse.BooleanOptionalAction, default=None, **kw)
        return
    if t == "array" and schema.get("items", {}).get("type") == "string":
        kw.update(action="append", type=_list_item)
    elif t in ("array", "object"):
        kw.update(type=json.loads, metavar="JSON")
    elif t == "number":
        kw.update(type=float)
    if "enum" in schema:
        kw["choices"] = schema["enum"]
    p.add_argument(flag, required=required, **kw)


# Worked examples for the commands whose arguments are JSON, shown in --help.
EXAMPLES = {
    "conjecture": """example:
  robert conjecture --rationale "simplest mechanism: unconstrained growth" \\
    --partitions '{"population": {"role": "structural", "observed": true,
                   "hypothesis": "grows at a constant per-capita rate"},
                   "season": {"role": "nuisance", "hypothesis": "a weak yearly cycle"}}'""",
    "confront": """example:
  robert confront --config model/confront.yaml --posterior-partitions ols \\
    --indices '{"ols": [6, 7]}'""",
    "answer": """example:
  robert answer --experiment E002 \\
    --answer "Yes: the model reproduces 2.0 home and 1.0 away goals per match" \\
    --hypotheses "goals arrive at random" --hypotheses "red cards change the game" \\
    --assumptions '[{"assumption": "goals arrive as a Poisson process",
                     "owner": "robert", "kind": "implementation", "sensitivity": "untested"},
                    {"assumption": "reproduces means within 10% of each rate",
                     "owner": "robert", "kind": "operationalisation"}]' \\
    --evidence '[{"kind": "test", "ref": "backtest-goals"}]' \\
    --against '[{"point": "totals alone cannot tell when goals happen"}]' \\
    --tried '[{"analysis": "posterior_estimation on the rates",
               "outcome": "abandoned: proposals went negative"}]' \\
    --reports '[{"standing": "S1", "report": "nothing to report"}, ...]' \\
    --follow-ups '[{"question": "Does a red card change the scoring rate?",
                    "kind": "test-assumption", "value": "high",
                    "discriminates": ["goals arrive at random",
                                      "red cards change the game"]}]'""",
    "revise": """example:
  robert revise --monitors '[{"name": "drift", "partition": "population",
                              "script": "analysis/drift.py", "action": "recalibrate"}]'""",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="robert", description="The AI simulation scientist's method CLI.")
    parser.add_argument("--version", action="version", version=f"robert {__version__}")
    parser.add_argument("--json", action="store_true", help="print JSON instead of YAML")
    sub = parser.add_subparsers(dest="command", required=True)
    for tool in TOOLS:
        p = sub.add_parser(tool.name, help=tool.description.split(". ")[0],
                           description=tool.description, epilog=EXAMPLES.get(tool.name),
                           formatter_class=argparse.RawDescriptionHelpFormatter)
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
    cloud = sub.add_parser("cloud", help="Run robert as a cloud agent (needs robert-ai[cloud])")
    csub = cloud.add_subparsers(dest="cloud_command", required=True)
    conf = csub.add_parser("configure", help="Record the agent and environment IDs")
    conf.add_argument("--lock", help="the claude-lock.json `ant apply` wrote "
                      "(needed for the managed-agents runner)")
    conf.add_argument("--github-owner", default="umbralcalc")
    conf.add_argument("--image", help="sandbox image; default: this robert version's image")
    conf.add_argument("--workspace", help="host directory for project repos")
    new = csub.add_parser("new", help="Create a project repo and start chatting")
    new.add_argument("project")
    new.add_argument("--description", required=True, help="the question, in your words")
    new.add_argument("--github", action="store_true",
                     help="also create a private GitHub repo and push to it after each "
                     "turn; by default the project stays a local git repo")
    new.add_argument("--runner", default="managed-agents",
                     choices=["managed-agents", "claude-code", "command"],
                     help="which agent drives the project")
    talk = csub.add_parser("chat", help="Reopen a project's session")
    talk.add_argument("project")
    pub = csub.add_parser("publish", help="Push a local project to a new private GitHub repo")
    pub.add_argument("project")
    pub.add_argument("--owner", help="GitHub owner; default: the config's github_owner")
    csub.add_parser("host", help="Claim sessions and run each in a fresh sandbox")
    csub.add_parser("worker", help="(inside a sandbox) serve one claimed session")
    agent = csub.add_parser("agent", help="(inside a sandbox) start a CLI agent for one turn")
    agent.add_argument("runner", choices=["claude-code"])
    agent.add_argument("--model", required=True)
    agent.add_argument("--continue", dest="cont", action="store_true")
    agent.add_argument("message")
    return parser


def cloud_main(ns: argparse.Namespace) -> dict[str, Any] | None:
    from . import cloud
    if ns.cloud_command == "configure":
        return cloud.configure(ns.lock, ns.github_owner, ns.image, ns.workspace)
    if ns.cloud_command == "new":
        from .cloud.chat import new
        new(ns.project, ns.description, ns.runner, ns.github)
    elif ns.cloud_command == "chat":
        from .cloud.chat import chat
        chat(ns.project)
    elif ns.cloud_command == "publish":
        from .cloud.chat import publish
        publish(ns.project, ns.owner)
    elif ns.cloud_command == "host":
        from .cloud.host import run
        run()
    elif ns.cloud_command == "worker":
        from .cloud.worker import main as worker
        worker()
    elif ns.cloud_command == "agent":
        from .cloud.agent import AGENTS
        AGENTS[ns.runner](ns.message, ns.model, ns.cont)
    return None


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
        elif ns.command == "cloud":
            try:
                result = cloud_main(ns)
            except ImportError as e:
                raise MethodError(f"{e}; install the cloud extra: pip install 'robert-ai[cloud]'")
            if result is None:
                return 0
        else:
            tool = next(t for t in TOOLS if t.name == ns.command)
            args = {k: (_flatten(v) if isinstance(v, list) else v)
                    for k, v in vars(ns).items()
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
