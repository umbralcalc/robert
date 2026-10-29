# syntax=docker/dockerfile:1

# robert as an image: robert, the stochadex release it locks, Python for analysis
# scripts, and git. It is a dev pod for cloud coding agents and Codespaces (every
# `robert init` project's .devcontainer points here), and an MCP server you can
# reach over the network:
#
#   docker run --rm -it -v "$PWD:/work" ghcr.io/umbralcalc/robert status
#   docker run --rm -p 8765:8765 -e ROBERT_MCP_TOKEN=... -v "$PWD:/work" \
#     ghcr.io/umbralcalc/robert mcp --http --host 0.0.0.0
#
# stochadex comes from its own published image, at the version robert/stochadex.json
# locks (the release workflow passes it in), so the binary is the one stochadex built,
# tested and released: the accelerated build, with Arrow, Postgres, S3, DuckDB and BLAS.

ARG STOCHADEX_VERSION=0.23.0
ARG PYTHON_VERSION=3.12
ARG DEBIAN_RELEASE=bookworm

FROM ghcr.io/umbralcalc/stochadex:${STOCHADEX_VERSION} AS stochadex

# Before stochadex v0.24 the partition graph is a separate binary that no release
# ships, so build it from the same tag. Drop this stage once the lock is >= v0.24.
FROM golang:1.25-bookworm AS graph
ARG STOCHADEX_VERSION
RUN GOBIN=/out go install github.com/umbralcalc/stochadex/cmd/stochadex-graph@v${STOCHADEX_VERSION}

FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE}

# The accelerated stochadex links OpenBLAS (with its Fortran runtime) and DuckDB's
# C++ runtime dynamically; same Debian release as its builder, so the ABI matches.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libopenblas0 libgfortran5 libstdc++6 ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

COPY --from=stochadex /usr/local/bin/stochadex /usr/local/bin/stochadex
COPY --from=graph /out/stochadex-graph /usr/local/bin/stochadex-graph

COPY . /src
RUN pip install --no-cache-dir /src && rm -rf /src

ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="robert" \
      org.opencontainers.image.description="The AI simulation scientist: robert's method CLI and MCP server with the stochadex release it locks" \
      org.opencontainers.image.source="https://github.com/umbralcalc/robert" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

# Same non-root uid as the stochadex image, so bind mounts behave the same way.
RUN useradd --uid 65532 --user-group --create-home robert \
 && mkdir -p /work && chown robert:robert /work
USER robert
WORKDIR /work

# Fail the build if robert cannot find a supported stochadex or a graph renderer.
RUN robert doctor

EXPOSE 8765
ENTRYPOINT ["robert"]
CMD ["--help"]
