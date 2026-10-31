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

## [0.1.0] — 2026-10-31

The first release of robert, the method layer of an AI simulation scientist. It
packages the discovery-and-warrant loop as tools any coding agent can call, over MCP
or as a CLI with the same arguments, and leaves every simulation to stochadex.
Each step's gate is enforced by robert, not by the agent, and every redirection is
logged as the experience the project encodes. It installs in one line, pins and
verifies the stochadex release it runs, and works locally, in a container or from a
cloud coding agent.

### Added

- **The loop as tools.** The method CLI and MCP server have one tool per step:
  `init`, `pose`, `conjecture`, `confront`, `test`, `discover`, `compress`,
  `warrant`, `query` and `revise`. Each writes its method files and runs its gate.
  Supporting tools are `run`, `graph`, `plot`, `status`, `explain`, `intervene` and
  `doctor`.
- **Skills.** The `simulation-scientist` skill encodes the method, and the
  `stochadex-model` skill (moved from stochadex) authors configs. It installs
  stochadex only through `robert setup`. `robert adapters` renders the Claude Code
  plugin, Cursor rules and `AGENTS.md` from them.
- **One-line install.** `install.sh` installs the `robert-ai` package and runs
  `robert setup`. Setup installs the locked stochadex release into
  `~/.robert/stochadex/<version>/`, checksum-verified, and registers robert with
  Claude Code and Cursor.
- **A stochadex lock.** `robert/stochadex.json` locks stochadex v0.24.0 and records
  every release asset's SHA-256. robert supports `>=0.24.0,<0.25.0` and refuses
  unverified downloads and binaries outside that range. The partition graph comes
  from `stochadex graph`, a test checks the skills against `stochadex catalogue`, and
  a weekly workflow proposes lock updates.
- **Cloud access.** `robert mcp --http` serves streamable HTTP at `/mcp`, and any
  bind address other than loopback requires `ROBERT_MCP_TOKEN`. The image
  `ghcr.io/umbralcalc/robert` and a Dev Container Feature are new, and every
  project `robert init` creates gets a `.devcontainer/`.
- **Releases.** This changelog, a prepare-release PR, tag-on-merge, and a release
  that publishes to PyPI, GitHub Releases and GHCR.

[Unreleased]: https://github.com/umbralcalc/robert/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/umbralcalc/robert/releases/tag/v0.1.0
