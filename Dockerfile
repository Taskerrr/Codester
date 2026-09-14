FROM python:3.12-slim AS codex-cli

ARG CODEX_VERSION=0.154.0
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && export CODEX_HOME=/opt/codex \
       CODEX_INSTALL_DIR=/usr/local/bin \
       CODEX_NON_INTERACTIVE=1 \
    && curl -fsSL https://chatgpt.com/codex/install.sh | sh -s -- --release "$CODEX_VERSION" \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv
COPY --from=codex-cli /opt/codex /opt/codex
COPY --from=codex-cli /usr/local/bin/codex /usr/local/bin/codex
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY codester ./codester
RUN uv sync --frozen --no-dev --no-editable && useradd --create-home --uid 10001 codester && mkdir /data && chown codester:codester /data
ENV PATH="/app/.venv/bin:$PATH" CODESTER_DATA_DIR=/data CODESTER_HOST=0.0.0.0 CODEX_HOME=/data/codex PYTHONUNBUFFERED=1
USER codester
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)"
CMD ["python", "-m", "codester"]
