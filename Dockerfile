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

ARG STOCHADEX_VERSION=0.24.0
ARG PYTHON_VERSION=3.12
ARG DEBIAN_RELEASE=bookworm

FROM ghcr.io/umbralcalc/stochadex:${STOCHADEX_VERSION} AS stochadex

FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE}

# The accelerated stochadex links OpenBLAS (with its Fortran runtime) and DuckDB's
# C++ runtime dynamically; same Debian release as its builder, so the ABI matches.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libopenblas0 libgfortran5 libstdc++6 ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

COPY --from=stochadex /usr/local/bin/stochadex /usr/local/bin/stochadex

COPY . /src
# The cloud extra adds the Managed Agents worker, so the same image is the
# per-session sandbox for `robert cloud host` (entrypoint `robert cloud worker`).
RUN pip install --no-cache-dir "/src[cloud]" \
 && mkdir -p /opt/robert && cp -r /src/skills /src/examples /opt/robert/ && rm -rf /src

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
 && mkdir -p /work /workspace /mnt/memory \
 && chown robert:robert /work /workspace /mnt/memory
USER robert
WORKDIR /work

# Fail the build if robert cannot find a supported stochadex.
RUN robert doctor

EXPOSE 8765
ENTRYPOINT ["robert"]
CMD ["--help"]
