#!/bin/sh
# Dev Container Feature: install robert system-wide, plus the stochadex release it
# locks under /usr/local/share/robert (ROBERT_HOME), readable by every user.
set -eu

VERSION="${VERSION:-latest}"
ACCELERATED="${ACCELERATED:-false}"

if ! command -v python3 >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates
    rm -rf /var/lib/apt/lists/*
  else
    echo "robert feature: python3 is required (add the python feature first)" >&2
    exit 1
  fi
fi

spec="robert-ai"
[ "$VERSION" != "latest" ] && spec="robert-ai==${VERSION}"

python3 -m venv /usr/local/robert
/usr/local/robert/bin/pip install --no-cache-dir "$spec"
ln -sf /usr/local/robert/bin/robert /usr/local/bin/robert

export ROBERT_HOME=/usr/local/share/robert
if [ "$ACCELERATED" = "true" ]; then
  robert setup --no-agents --accelerated
else
  robert setup --no-agents
fi
chmod -R a+rX "$ROBERT_HOME"
robert doctor
