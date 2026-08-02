# Akinator Bot (v2)

Modern, concurrent Telegram bot for the Akinator guessing game.

- **akipy 1.6.0** (async API) with **TRAWL** / FlareSolverr Cloudflare bypass
- **SQLite** (WAL) via `aiosqlite`
- **uv** packaging, **Docker Compose**, `.env` config
- **Inline mode** - play in any group/chat via `@your_bot play`
- Per-user session locks + global API semaphore for multi-user load
- Modern leaderboard (correct / win rate / games / questions)
- Admin panel (`ADMIN_IDS` + optional `ADMIN_SECRET`) with secret-safe logging

## Quick start (local)

```bash
# requires Python 3.12+ and uv
cp .env.example .env
# set BOT_TOKEN and SOLVER_URL

uv sync
uv run akinator-bot
```

### BotFather checklist

1. Disable privacy mode if you want group command visibility (`/setprivacy` -> Disable) - not required for private play or inline.
2. Enable inline: `/setinline` -> set a placeholder like `play`.
3. Optional: `/setinlinefeedback` Enabled (improves session bind; not required).

## Environment

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram token |
| `SOLVER_URL` / `AKIPY_SOLVER_URL` | TRAWL or FlareSolverr base URL |
| `DATABASE_PATH` | SQLite file path |
| `ADMIN_IDS` | Comma-separated admin Telegram IDs |
| `ADMIN_SECRET` | Optional `/admin <secret>` unlock |
| `MAX_CONCURRENT_AKI_CALLS` | Semaphore for Akinator HTTP (default 32) |
| `SESSION_TTL_SECONDS` | Idle game expiry (default 1800) |

This host already runs TRAWL at `http://127.0.0.1:8193` and `https://trawl.advnpzn.dev`.

## Docker

```bash
cp .env.example .env   # fill BOT_TOKEN
docker compose up -d --build
docker compose logs -f bot
```

Compose joins the external Docker network `trawl_default` and uses `http://trawl:8191` as the solver. For host-only TRAWL without that network, set:

```env
AKIPY_SOLVER_URL=http://host.docker.internal:8193
```

and ensure `extra_hosts` / host gateway is configured.

## Commands

| Command | Action |
|---------|--------|
| `/start` | Welcome + menu |
| `/play` | Start a game |
| `/cancel` | Abandon current game |
| `/me` | Your stats |
| `/leaderboard` | Rankings |
| `/language` | Question language |
| `/childmode` | NSFW filter |
| `/stats` | Global counters |
| `/admin` | Admin panel (admins only) |

### Inline

In any chat:

```text
@YourBot play
```

Pick **Play Akinator**, then **Start game**. Only the starter can answer.
