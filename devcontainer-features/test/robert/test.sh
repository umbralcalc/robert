#!/bin/sh
# Run by `devcontainer features test`: the feature leaves a working robert behind.
set -eu
robert --version
robert doctor
