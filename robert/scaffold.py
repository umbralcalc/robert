"""The files `robert init` writes into a new project repo.

The project carries its own agent wiring (an MCP config for Claude Code and Cursor,
and an AGENTS.md for anything else), so whichever agent opens the repo calls the
same tools and meets the same gates.
"""

from __future__ import annotations

import json

from . import __version__

AGENTS_MD = """\
# {name}

A simulation science project driven by `robert`, the method layer over the
stochadex engine. Read this before changing anything.

## How to work here

- The user asks questions; you answer them. Open an experiment with `ask` for each
  question, answer it with `answer` (assumptions stated, evidence cited, follow-ups
  suggested), and load `context` before a deeper question.
- Drive the project through the robert tools (MCP server `robert`, or the `robert`
  CLI with identical arguments). Each loop step is one tool:
  init → pose → conjecture → confront → test → (discover | compress) → warrant →
  query → revise. Call `status` first to see where the loop stands.
- Every model change is an edit to `model/sim.yaml`, a pure stochadex config.
  Follow the `stochadex-model` skill to write it. Never put method annotations in
  it; they go in `model/partitions.yaml`.
- Never state a number you did not read from `out/`. Every figure traces back to a
  config, a seed and its provenance sidecar.
- A failed gate is not an error. Report which check failed, propose the next step,
  and let the user decide.
- When the user redirects you, call `intervene` with what you proposed, what they
  decided and why. That log is the project's most valuable output.
- Climb the ladder only on a recorded failure: expressions and catalogue
  iterations first, learned (ONNX) components only through `discover`, custom Go
  last.

## Files

| File | Contract |
| --- | --- |
| experiments/ | Every question asked, robert's answer, its assumptions, evidence and follow-ups |
| claim.yaml | The claim, its intended use and the conditions it must hold under |
| domain.yaml | Partition names in the user's terms; what the user already knows |
| model/sim.yaml | A valid stochadex config and nothing else |
| model/partitions.yaml | Per partition: role, one-line hypothesis, evidence status |
| model/lineage.yaml | Every variant, its parent, and the test that justified it |
| tests.yaml | Check specs and a verdict per partition |
| ledger/ | Append-only, hash-chained beliefs and warrants |
| interventions.yaml | Append-only log of every redirection |
| out/ | Written only by stochadex, with provenance sidecars |
| analysis/ | Python: preprocessing, test and score scripts |
| learned/ | Training scripts for learned components (ONNX) |
| figures/ | Graphs and charts robert renders |
"""

MCP_SERVER = {"command": "robert", "args": ["mcp"]}


def mcp_json() -> str:
    return json.dumps({"mcpServers": {"robert": MCP_SERVER}}, indent=2) + "\n"


IMAGE = "ghcr.io/umbralcalc/robert"


def devcontainer_json() -> str:
    """Open the project in Codespaces, a dev pod or a cloud agent with robert and the
    pinned stochadex already installed: the robert image of this robert version."""
    return json.dumps({
        "name": "robert project",
        "image": f"{IMAGE}:{__version__}",
        "workspaceFolder": "/workspaces/${localWorkspaceFolderBasename}",
        "postCreateCommand": "robert doctor",
        "customizations": {"vscode": {"extensions": ["ms-python.python",
                                                      "bierner.markdown-mermaid"]}},
    }, indent=2) + "\n"


GITIGNORE = """\
.robert/harness/
__pycache__/
.venv/
"""

TESTS_YAML = """\
# Check specs. Each script prints one JSON object on its last line:
#   {"passed": true, "metric": 0.12, "detail": "..."}
# kinds: backtest (needs train_end < test_start), process, swap, generalisation, outcome
checks: []
"""

LICENCES_YAML = """\
# One entry per stochadex input name: licence and provenance of the source.
# e.g.
# observations: {licence: OGL-3.0, source: "https://...", retrieved: 2026-10-28}
{}
"""
