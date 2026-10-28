"""The CLI, the MCP server and the adapters all come from one registry and one source."""

import anyio
import pytest
from mcp import Client

from robert import adapters
from robert.cli import build_parser
from robert.mcp_server import build
from robert.tools import TOOLS

from .conftest import REPO, needs_stochadex


def test_every_tool_is_a_cli_command():
    parser = build_parser()
    commands = parser._subparsers._group_actions[0].choices
    assert {t.name for t in TOOLS} <= set(commands)


def test_cli_parses_lists_objects_and_booleans():
    ns = build_parser().parse_args([
        "init", "--path", "p", "--name", "n", "--description", "d", "--level", "expert",
        "--user-knows", "a", "--user-knows", "b", "--terms", '{"x": "X"}', "--no-git"])
    assert ns.user_knows == ["a", "b"] and ns.terms == {"x": "X"} and ns.git is False


def test_mcp_lists_the_same_tools_with_the_same_schemas():
    async def main():
        async with Client(build()) as client:
            return (await client.list_tools()).tools

    listed = {t.name: t.input_schema for t in anyio.run(main)}
    assert listed == {t.name: t.input_schema for t in TOOLS}


@needs_stochadex
def test_mcp_call_reports_method_errors_as_tool_errors(tmp_path):
    async def main():
        async with Client(build()) as client:
            return await client.call_tool("status", {"project": str(tmp_path)})

    result = anyio.run(main)
    assert result.is_error and "robert init" in result.content[0].text


@pytest.mark.parametrize("rel,text", sorted(adapters.outputs().items()))
def test_committed_adapters_match_their_source(rel, text):
    path = REPO / rel
    assert path.exists() and path.read_text() == text, (
        f"{rel} is stale: run `robert adapters`")


@needs_stochadex
@pytest.mark.parametrize("recipe", sorted((REPO / "skills/stochadex-model/recipes").glob("*.yaml")),
                         ids=lambda p: p.stem)
def test_skill_recipes_pass_the_pinned_stochadex_check(recipe):
    """The contract with stochadex: every recipe the skills cite must --check."""
    from robert.engine import Engine
    r = Engine(recipe.parent).check(recipe.name)
    assert r.ok, r.summary()
