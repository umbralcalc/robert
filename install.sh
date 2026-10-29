#!/bin/sh
# Install robert, the AI simulation scientist, in one line:
#
#   curl -fsSL https://raw.githubusercontent.com/umbralcalc/robert/main/install.sh | sh
#
# It installs the `robert-ai` package as an isolated tool (uv, else pipx), then runs
# `robert setup`, which downloads the stochadex release robert locks (checksum
# verified) and registers robert with the coding agents it finds.
#
# Environment:
#   ROBERT_VERSION   a release such as 0.2.0 (default: the latest)
#   ROBERT_SOURCE    install from elsewhere, e.g. git+https://github.com/umbralcalc/robert
#   ROBERT_NO_AGENTS set to 1 to skip agent registration (CI, containers)
# Arguments after `sh -s --` pass through to `robert setup`, e.g. `--accelerated`.
set -eu

say() { printf 'robert: %s\n' "$*"; }
fail() { printf 'robert: %s\n' "$*" >&2; exit 1; }

spec="${ROBERT_SOURCE:-robert-ai}"
if [ -z "${ROBERT_SOURCE:-}" ] && [ -n "${ROBERT_VERSION:-}" ]; then
  spec="robert-ai==${ROBERT_VERSION}"
fi

if command -v uv >/dev/null 2>&1; then
  say "installing ${spec} with uv"
  uv tool install --force --python '>=3.11' "$spec"
  bindir="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
elif command -v pipx >/dev/null 2>&1; then
  say "installing ${spec} with pipx"
  pipx install --force "$spec"
  bindir="${PIPX_BIN_DIR:-$HOME/.local/bin}"
else
  say "neither uv nor pipx found; installing uv from https://astral.sh/uv"
  command -v curl >/dev/null 2>&1 || fail "curl is required"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv did not install; install uv or pipx and re-run"
  uv tool install --force --python '>=3.11' "$spec"
  bindir="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
fi

case ":$PATH:" in
  *":$bindir:"*) ;;
  *) PATH="$bindir:$PATH"; path_note=1 ;;
esac
command -v robert >/dev/null 2>&1 || fail "robert was installed but is not on PATH ($bindir)"

if [ "${ROBERT_NO_AGENTS:-0}" = "1" ]; then
  robert setup --no-agents "$@"
else
  robert setup "$@"
fi

if [ "${path_note:-0}" = "1" ]; then
  say "add ${bindir} to your PATH (for example in ~/.profile) so agents can start robert"
fi
say "done. Check the toolchain any time with: robert doctor"
