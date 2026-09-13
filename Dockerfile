FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY codester ./codester
RUN uv sync --frozen --no-dev --no-editable && useradd --create-home --uid 10001 codester && mkdir /data && chown codester:codester /data
ENV PATH="/app/.venv/bin:$PATH" CODESTER_DATA_DIR=/data CODESTER_HOST=0.0.0.0 PYTHONUNBUFFERED=1
USER codester
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)"
CMD ["python", "-m", "codester"]
