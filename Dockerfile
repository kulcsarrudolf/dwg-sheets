# syntax=docker/dockerfile:1.7

# ---- CADCraft command-line tool, official release, pinned and checksum-verified ----
FROM debian:trixie-slim AS cadcraft
ARG CADCRAFT_VERSION=0.8.0
ARG CADCRAFT_SHA256_X86_64=df3c2e668439f0410564b1fa9d21827bb663eb3d01703902c41f02b9c5276193
ARG CADCRAFT_SHA256_AARCH64=e7e7a805d683433733a77951326163506f203bd5dee515f465a5c575669d3f85
ARG TARGETARCH
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) arch=x86_64;  sum="$CADCRAFT_SHA256_X86_64" ;; \
      arm64) arch=aarch64; sum="$CADCRAFT_SHA256_AARCH64" ;; \
      *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    name="cadcraft-${CADCRAFT_VERSION}-linux-${arch}"; \
    curl -fsSL -o /tmp/cadcraft.tar.gz \
      "https://github.com/storytold/cadcraft/releases/download/v${CADCRAFT_VERSION}/${name}.tar.gz"; \
    echo "${sum}  /tmp/cadcraft.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/cadcraft.tar.gz -C /tmp "${name}/bin/cadcraft-cli"; \
    install -m 0755 "/tmp/${name}/bin/cadcraft-cli" /usr/local/bin/cadcraft-cli; \
    /usr/local/bin/cadcraft-cli --version

# ---- Arial / Times New Roman / Courier New stand-ins (Liberation, renamed; see docker/alias_fonts.py) ----
FROM python:3.13-slim-trixie AS fonts
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-liberation \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fonttools==4.60.1
COPY docker/alias_fonts.py /tmp/alias_fonts.py
RUN python /tmp/alias_fonts.py /usr/share/fonts/truetype/liberation /out/fonts \
 && cp /usr/share/doc/fonts-liberation/copyright /out/fonts/LICENSE-Liberation.txt

# ---- Python dependencies ----
FROM python:3.13-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra web --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra web --no-editable

# ---- Runtime ----
FROM python:3.13-slim-trixie
# DejaVu covers characters the drawing's own fonts lack (Romanian and Hungarian letters included).
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin app
COPY --from=fonts /out/fonts /usr/local/share/fonts/drawing-compat
COPY --from=cadcraft /usr/local/bin/cadcraft-cli /usr/local/bin/cadcraft-cli
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    WORK_DIR=/tmp/jobs \
    CADCRAFT_CONFIG_DIR=/tmp/cadcraft
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"]
CMD ["dwg-sheets-web"]
