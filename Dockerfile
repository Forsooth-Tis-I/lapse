# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime
RUN pip install --no-cache-dir uv==0.8.22
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
COPY lapse ./lapse
RUN uv sync --locked --no-dev
EXPOSE 8000 8765
CMD ["lapse-api"]

FROM runtime AS api
CMD ["uvicorn", "lapse.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS worker
CMD ["lapse-worker"]

FROM runtime AS bot
CMD ["lapse-bot"]

FROM runtime AS mcp
CMD ["lapse-mcp"]

FROM worker AS worker-browser
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN uv sync --locked --no-dev --extra browser \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

FROM api AS default
