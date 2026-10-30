# Changelog

All notable changes to robert are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Versioning policy.** robert is pre-1.0 (`v0.x`), so a minor bump may break the CLI,
the MCP tool schemas or the project file contracts; a patch bump never does. Each
release locks one stochadex version (`robert/stochadex.json`) and declares the range
it supports. A project records the robert, skills and stochadex versions it was
created with, so a comparison between runs is always like for like.

## [Unreleased]

### Changed

- **robert locks stochadex v0.24.0 and needs v0.24 or later.** The partition graph comes
  from `stochadex graph` and the skills are checked against `stochadex catalogue`, so the
  separate `stochadex-graph` binary, and the Go toolchain `robert setup`, the image and CI
  used to build it, are no longer needed.
- The `stochadex-model` skill tells agents to install stochadex only through
  `robert setup`, never from `latest`, and documents `stochadex graph` and
  `stochadex catalogue`.

### Added

- The method CLI and MCP server: one tool per step of the discovery-and-warrant loop
  (`init`, `pose`, `conjecture`, `confront`, `test`, `discover`, `compress`, `warrant`,
  `query`, `revise`) plus `run`, `graph`, `plot`, `status`, `explain`, `intervene` and
  `doctor`, all gated as the design specifies.
- The `simulation-scientist` skill, and the `stochadex-model` skill moved from
  stochadex v0.23.0; `robert adapters` renders the Claude Code plugin, Cursor rules
  and `AGENTS.md` from them.
- One-line install (`install.sh`) and `robert setup`, which installs the locked
  stochadex release into `~/.robert/stochadex/<version>/`, checksum-verified, and
  registers robert with Claude Code and Cursor.
- A stochadex lock (`robert/stochadex.json`): the default version, the supported
  range and every release asset's SHA-256. robert refuses unverified downloads and
  binaries outside the range, and a weekly workflow proposes lock updates.
- `robert mcp --http`: streamable HTTP at `/mcp` for agents that reach robert over
  the network; any bind other than loopback requires `ROBERT_MCP_TOKEN`.
- The robert image (`ghcr.io/umbralcalc/robert`), a Dev Container Feature, and a
  `.devcontainer/` in every project `robert init` creates.
- Releases: this changelog, a prepare-release PR, tag-on-merge, and a release that
  publishes to PyPI (`robert-ai`), GitHub Releases and GHCR.

[Unreleased]: https://github.com/umbralcalc/robert/commits/main
