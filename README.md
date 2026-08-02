# Akinator Bot (v2)

Modern, concurrent Telegram bot for the Akinator guessing game.

- **akipy 1.6.0** (async API) with **TRAWL** / FlareSolverr Cloudflare bypass  
- **SQLite** (WAL) via `aiosqlite`  
- **uv** packaging · **Docker Compose** · `.env` config  
- **Inline mode** — play in any group/chat via `@your_bot play`  
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

1. Disable privacy mode if you want group command visibility (`/setprivacy` → Disable) — not required for private play or inline.  
2. Enable inline: `/setinline` → set a placeholder like `play`.  
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

The compose file reaches host TRAWL via `host.docker.internal:8193`. To embed a solver:

```bash
docker compose --profile with-trawl up -d --build
```

To attach to an existing Docker network named `trawl_default`, uncomment the `networks` block in `docker-compose.yml` and set:

```env
AKIPY_SOLVER_URL=http://trawl:8191
```

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

## Architecture

```text
Telegram updates ──► python-telegram-bot (concurrent_updates)
                         │
         ┌───────────────┼────────────────┐
         ▼               ▼                ▼
   SessionManager    GameService       Database
   (per-user lock)   (akipy async      (aiosqlite WAL)
                      + semaphore)
                           │
                           ▼
                    TRAWL (optional CF solve)
                           │
                           ▼
                       Akinator
```

## Credits

- Original idea: [advnpzn/Akinator-Bot](https://github.com/advnpzn/Akinator-Bot)  
- [akipy](https://github.com/advnpzn/akipy) · [TRAWL](https://github.com/germondai/trawl) · [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
