# syntax=docker/dockerfile:1

# The claude-code runner's sandbox: the robert image plus Claude Code, pinned.
# Everything else (user, read-only root, egress proxy, project mount) is the same
# as for every other runner, so only the agent differs between runs.
ARG BASE=ghcr.io/umbralcalc/robert:latest
FROM ${BASE}

ARG CLAUDE_CODE_VERSION=2.1.316
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force \
 && apt-get purge -y npm && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*
USER robert
RUN claude --version
