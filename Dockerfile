# syntax=docker/dockerfile:1
# Official Python and uv images support both ARM64 and AMD64.
FROM python:3.13-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=0 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# Optional CA bundle for corporate/cloud build proxies; never persisted in the image.
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --system-certs --frozen --no-dev --no-editable

FROM python:3.13-slim-trixie AS runtime
WORKDIR /app
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home /app app \
    && mkdir -p /app/data && chown app:app /app/data
COPY --from=builder /app/.venv /app/.venv
COPY --chown=app:app assets /app/assets
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/app/data/akinator.db ASSETS_DIR=/app/assets/aki_pics
USER app
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "-m", "akinator_bot.health"]
CMD ["akinator-bot"]
