"""robert: the AI simulation scientist.

A thin method layer over the stochadex engine. It owns the method files and the
gates of the discovery-and-warrant loop, and delegates every simulation action to
the stochadex binary. The same tool registry drives the CLI and the MCP server, so
a chat-driven project and a hand-driven one leave the same trail in the repo.
"""

__version__ = "0.1.0"

# The stochadex release this version of robert is written and checked against.
STOCHADEX_VERSION = "v0.23.0"

# Skills are versioned so every project records which version shaped it.
SKILLS_VERSION = "0.1.0"
