# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

COPY pyproject.toml README.md ./
COPY src ./src
COPY assets ./assets

# Lockfile optional on first build - generate if present
COPY uv.lock* ./

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -f uv.lock ]; then uv sync --frozen --no-dev --no-editable; \
    else uv sync --no-dev --no-editable; fi

# --- runtime ---
FROM python:3.13-slim-bookworm

WORKDIR /app

RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home /app app \
    && mkdir -p /app/data \
    && chown app:app /app/data

COPY --from=builder --chown=app:app /app /app
COPY --chown=app:app assets ./assets

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/app/data/akinator.db \
    ASSETS_DIR=/app/assets/aki_pics

USER app

CMD ["akinator-bot"]
