# syntax=docker/dockerfile:1
# Debian trixie ships OpenSSL 3.5+, which Cloudflare accepts more reliably
# than bookworm's OpenSSL 3.0 (datacenter TLS fingerprints often get 403).
FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

COPY pyproject.toml README.md uv.lock ./
COPY src ./src
COPY assets ./assets

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# --- runtime ---
FROM python:3.13-slim-trixie

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
