# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
RUN pip install --no-cache-dir uv==0.8.22
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_HTTP_TIMEOUT=300 PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./

# Dependencies only: cached until pyproject.toml or uv.lock change, so code edits never re-download them.
FROM base AS deps
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project

FROM deps AS deps-browser
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra browser --no-install-project \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

FROM deps AS runtime
COPY lapse ./lapse
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev
EXPOSE 8000 8766
CMD ["lapse-api"]

FROM runtime AS api
CMD ["uvicorn", "lapse.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS worker
CMD ["lapse-worker"]

FROM runtime AS bot
CMD ["lapse-bot"]

FROM runtime AS mcp
CMD ["lapse-mcp", "--transport", "streamable-http"]

FROM deps-browser AS worker-browser
COPY lapse ./lapse
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --extra browser
EXPOSE 8000 8766
CMD ["lapse-worker"]

FROM api AS default
