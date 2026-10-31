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

### Fixed

- **An approved data source now actually opens the sandbox's network.** The egress
  proxy never reloaded its allowlist: `squid -k reconfigure` can't find squid without a
  PID file, and the failure was ignored, so the proxy kept the hosts it started with.
  robert now reloads it with SIGHUP. Each turn of a CLI runner also prints which hosts
  the sandbox can reach, and the agent instructions explain that the host is the
  user's own `robert cloud` process, re-reading `data/licences.yaml` every turn.

- `robert cloud` reports a Docker problem in plain words ("Docker isn't running...")
  instead of a traceback, and passes on docker's own message for any other failure.

### Changed

- **Cloud projects are local git repos by default.** `robert cloud new` creates the
  project's repo in the host workspace and nothing leaves the host. `--github` creates a
  private GitHub repo as well, and `robert cloud publish <project>` adds one later; for a
  published project the host pushes after each turn, as before. `gh` is needed only for
  publishing.

## [0.3.0] — 2026-10-31

This release makes robert's answers harder to fool, robert included. Every answer now
states the strongest case against itself, keeps every analysis tried, and reports on
the project's standing questions, the channel for surprises nobody thought to ask
about. Follow-ups are ranked by how much their result would change what we believe,
and robert states the operationalisation choices it makes instead of keeping them
silent.

**Upgrading from 0.2.** `answer` now requires `against`, and every assumption needs a
`kind` (`implementation`, `operationalisation` or `belief`). Projects created with 0.2
have no standing questions until you add some with `robert standing --add "..."`.

### Added

- **Standing questions** (`standing.yaml`, the `standing` tool): questions posed once
  that every answer must report on. They are the channel for what nobody thought to ask
  about. `init` sets four defaults (contradictions, surprises, operationalisation
  choices, anything that would flip a warranted claim), and the user can add or retire
  their own.
- **Answers guard against confirmation bias.** `answer` now requires the strongest
  evidence or argument against the answer (`against`), and records every analysis tried,
  kept or not (`tried`), and the competing explanations weighed (`hypotheses`).
- **Follow-ups that tell explanations apart.** Each follow-up has a value (high,
  medium, low) and they are ranked by it; at least one must name in `discriminates` the
  explanations its result would separate.

### Changed

- **Three kinds of choice.** Every assumption is an `implementation`,
  `operationalisation` or `belief` choice. robert decides implementation choices
  silently, makes operationalisation choices provisionally and states them where the
  user can contest them, and asks about beliefs only when an answer depends on one. This
  replaces 0.2.0's "never ask about the build", which hid choices that change what a
  result means. The `answer` arguments change accordingly; `against` is now required.

## [0.2.0] — 2026-10-31

This release makes robert question-led and runnable in the cloud with any agent. The
user asks questions; robert answers each one as an experiment, with its assumptions
stated, its evidence cited and follow-ups suggested, and makes every build choice
itself. Projects can run in a locked-down sandbox from the robert image, driven by
Managed Agents, Claude Code or any agent CLI, with network access limited to the
model API and the project's licensed data hosts.

**Upgrading from 0.1.** Existing projects keep working; `experiments/` is created by
the first `ask`. For the cloud, install `robert-ai[cloud]` and run
`robert cloud configure`; the sandbox images are `ghcr.io/umbralcalc/robert:0.2.0` and
`ghcr.io/umbralcalc/robert-claude-code:0.2.0`.

### Added

- **Experiments: the unit the user works with.** The user asks a question and robert
  answers it. `ask` opens experiment `E###` and returns what earlier experiments
  established; `answer` records the answer with every assumption it rests on (owned by
  the user or robert, with its sensitivity), the evidence behind every number, and
  follow-up questions; `context` loads the chain of experiments a deeper question
  builds on. The answer gate refuses missing assumptions, numbers without evidence,
  evidence that doesn't exist, and answers with no follow-ups. Experiments live in
  `experiments/` in every project.

- **robert in the cloud** (`robert-ai[cloud]`, see `cloud/README.md`): one locked-down
  sandbox, any agent. Every run gets a fresh container from the robert image (non-root,
  read-only, no capabilities) on an internal network whose only way out is a proxy
  allowing the runner's model API and the hosts in the project's `data/licences.yaml`.
  Project repos are cloned and pushed on the host, so no GitHub token enters a sandbox.
- **Runners**, behind one `turn(message) -> events` interface: `managed-agents` (a
  Managed Agents agent and self-hosted environment in `cloud/agents/robert/` for
  `ant apply`, served by `robert cloud host`), `claude-code` (Claude Code headless in the
  sandbox, from the new `robert-claude-code` image), and `command` (any agent CLI from a
  configured template). All get the same instructions and skills.
- `robert cloud new --runner ...` and `robert cloud chat` create a project and talk to
  its agent from a terminal.
- The robert image installs the cloud extra and the skills, so it is the sandbox base.

### Changed

- **robert owns the build.** The `simulation-scientist` skill and the cloud
  instructions now lead every reply with the answer, its assumptions and numbered
  follow-ups. robert makes build choices itself and records them as its own
  assumptions, asking the user only what they believe about the world, and only when
  an answer depends on it.
- String-list arguments also take one JSON list, and the commands with JSON arguments
  show a worked example in `--help`. The robert image includes `examples/`.

### Fixed

- `robert cloud` clones and pushes project repos over HTTPS with the GitHub CLI's
  credentials and never prompts, whatever protocol `gh` is set to.
- `robert cloud new` reuses a project that never completed a turn.
- The `stochadex-model` skill's frontmatter is now strict YAML, as the Skills API
  requires; `robert adapters` parses it strictly so this cannot regress.

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

[Unreleased]: https://github.com/umbralcalc/robert/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/umbralcalc/robert/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/umbralcalc/robert/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/umbralcalc/robert/releases/tag/v0.1.0
