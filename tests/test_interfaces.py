"""The CLI, the MCP server and the adapters all come from one registry and one source."""

import re

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


SKILL_CATALOGUE_KEYS = {
    "Iterations": "iterations", "Kernels": "kernels", "Likelihoods": "likelihoods",
    "Priors": "priors", "Macros": "macros",
}
SKILL_COMPONENT_KEYS = {
    "condition": "output_conditions", "function": "output_functions",
    "termination": "termination_conditions", "timestep": "timestep_functions",
}


def _skill_catalogue() -> dict[str, set[str]]:
    """Every `{type: ...}` name the stochadex-model skill tells an agent it may use."""
    text = (REPO / "skills/stochadex-model/SKILL.md").read_text()
    section = text[text.index("## Catalogue"):]
    named: dict[str, set[str]] = {}
    for para in re.split(r"\n(?=\*\*)", section):
        heading = re.match(r"\*\*([^*:]+):\*\*", para)
        if not heading:
            continue
        flat = para
        while (stripped := re.sub(r"\([^()]*\)", "", flat)) != flat:
            flat = stripped  # parenthesised text holds params and fields, not types
        key = next((v for k, v in SKILL_CATALOGUE_KEYS.items()
                    if heading.group(1).startswith(k)), None)
        if key:
            named.setdefault(key, set()).update(re.findall(r"`([a-z_]+)`", flat))
        for word, ckey in SKILL_COMPONENT_KEYS.items():
            for group in re.findall(rf"{word} `([a-z_|]+)`", para):
                named.setdefault(ckey, set()).update(group.split("|"))
    return named


@needs_stochadex
def test_skill_names_only_types_stochadex_registers():
    """The contract with stochadex: the skill is checked against `stochadex catalogue`,
    so a renamed or removed type fails here instead of confusing an agent."""
    from robert.engine import Engine
    catalogue = Engine(REPO).catalogue()
    registered = {k: {e["name"] for e in v} for k, v in catalogue.items()
                  if isinstance(v, list) and v and isinstance(v[0], dict)}
    named = _skill_catalogue()
    assert set(named) >= set(SKILL_CATALOGUE_KEYS.values())
    unknown = {k: sorted(names - registered.get(k, set())) for k, names in named.items()}
    assert not any(unknown.values()), f"skill names types stochadex does not register: {unknown}"


@needs_stochadex
@pytest.mark.parametrize("recipe", sorted((REPO / "skills/stochadex-model/recipes").glob("*.yaml")),
                         ids=lambda p: p.stem)
def test_skill_recipes_pass_the_pinned_stochadex_check(recipe):
    """The contract with stochadex: every recipe the skills cite must --check."""
    from robert.engine import Engine
    r = Engine(recipe.parent).check(recipe.name)
    assert r.ok, r.summary()
