"""robert: the AI simulation scientist.

A thin method layer over the stochadex engine. It owns the method files and the
gates of the discovery-and-warrant loop, and delegates every simulation action to
the stochadex binary. The same tool registry drives the CLI and the MCP server, so
a chat-driven project and a hand-driven one leave the same trail in the repo.

The version below is the single source: the package metadata, the plugin manifest
and the skills version every project records all read it. The stochadex version
robert supports lives in `stochadex.json`.
"""

__version__ = "0.2.0"
