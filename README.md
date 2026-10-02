# Akinator Bot

A Telegram Akinator bot built for a Raspberry Pi 5 and other small Linux hosts.
Python 3.12+, akipy 1.7.0, python-telegram-bot 22.8, and SQLite with WAL.
Private chats use Akinator's current question images; inline games use text.

## Raspberry Pi deployment

Use a **64-bit OS** on the Pi 5, Docker Engine, and the Docker Compose plugin.
The Dockerfile uses ARM64-compatible images and dependencies. Native builds on
an SD card can be slow; an SSD is preferable for the database and Docker storage.

```bash
cp .env.example .env
chmod 600 .env
# Edit .env locally: set BOT_TOKEN from @BotFather and your ADMIN_IDS.
./deploy/provision.sh
```

The provisioner creates an empty `.env` template if missing and stops so you can
configure it. It does not install Docker, request credentials, overwrite `.env`,
or provision cloud infrastructure. No domain, open inbound port, Redis, or
external database is required. Only **one bot process** may use a token/database.

Defaults are ceilings, not allocations: 1 CPU, 512 MB RAM, 100 resident games,
4 concurrent Akinator requests, and 16 concurrent updates. Idle CPU should be
low because processing is asynchronous. Actual Pi memory/throughput must be
measured on your device; resource limits do not promise a particular capacity.
When admission is full, users receive a busy response; live games are not evicted.

```bash
docker compose ps
docker compose logs --tail=50 bot
docker stats --no-stream
```

The local health probe checks maintenance
and database readiness, not Telegram/Akinator availability. Docker marks an
unhealthy container but does not automatically restart it for that reason.
The restart policy handles process exits.

## Optional challenge solver

Start with direct requests (`SOLVER_URL` empty). If Cloudflare challenges those
requests, use an existing reachable TRAWL/FlareSolverr endpoint, or:

```bash
./deploy/provision.sh --solver
```

This overlay adds FlareSolverr v3.4.6, which publishes an ARM64 image, and sets
the bot's solver URL to `http://solver:8191`. It allows the solver 1 CPU and
1536 MB RAM separately from the bot. Browser solving is substantially heavier
than normal game requests; tune `SOLVER_CPUS`/`SOLVER_MEMORY` after measuring.
To stop the optional service without deleting data:

```bash
docker compose -f docker-compose.yml -f deploy/compose.solver.yaml stop solver
./deploy/provision.sh
```

Inside a container, `127.0.0.1` means that container. It cannot reach a solver
running directly on the Pi host. Supply a reachable address instead. Existing
`AKIPY_SOLVER_URL` takes precedence over `SOLVER_URL`; remove stale settings.

## Development

```bash
uv sync --frozen --python 3.12
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen akinator-bot
```

The tests block real socket connections. They exercise the released akipy code,
SQLite migrations/transactions, actual Telegram handler dispatch with a simulated
Bot API, game failure paths, callback revisions, ordering, and resource cleanup.
CI builds both AMD64 and ARM64 images. akipy currently declares some testing
packages as runtime dependencies; the bot cannot omit them from a frozen install.

## Configuration

See [.env.example](.env.example) for every operational setting.

- `BOT_TOKEN`: required, injected through the environment or ignored `.env`.
  `BOT_TOKEN_FILE` supports a mounted secret file when `BOT_TOKEN` is absent.
- `ADMIN_IDS`: your own Telegram user IDs. Administration works in private chats.
  Shared `ADMIN_SECRET` unlocks have been removed.
- `DATABASE_PATH`: defaults to `data/akinator.db`; Compose uses `/app/data/akinator.db`.
- `MAX_CONCURRENT_AKI_CALLS`: start at 4; increase only if upstream latency,
  memory, and error rates remain acceptable.
- `MAX_CONCURRENT_GAMES`: bounds resident session/client state independently
  of registered users. Session expiry defaults to 20 minutes.
- `ACTION_TIMEOUT_SECONDS`: bounds a complete upstream operation. An ambiguous
  timeout ends the game instead of replaying a possibly accepted action.
- `REGISTER_COMMANDS`: set true for one deployment to register the BotFather
  command menu, then return to false.
- `EVENT_RETENTION_DAYS`: trims ended-game records and events, retaining user totals.

Turn on inline mode in BotFather with `/setinline`. Inline feedback is not needed:
invitations allocate a session only when their owner presses Start.

## Updates and existing installations

Before the first upgrade, make a backup. The database migration adds a game ledger
and indexes while preserving existing users and scores. The Compose volume keeps
the previous name, `akinator-data`; do not run `docker compose down --volumes`.
Old active games are not restored across a restart. They expire safely, with
completed results preserved. Live session restoration requires a supported akipy
snapshot API and validation of upstream cookie/network affinity.

Remove old hard-coded solver settings and configure your own admin IDs. The bot
no longer joins external Docker networks or uses host networking. Its callbacks
include a revision; old buttons from the previous version expire.

```bash
./deploy/provision.sh   # Build and replace the bot while retaining its data volume
```

Keep the previous image/tag and backup for rollback. Roll back the application
only after checking database compatibility; never restore a backup over a running
SQLite writer.

## Backups

Use SQLite's online backup API, rather than copying only a live `.db` file:

```bash
docker compose exec bot python -m akinator_bot.backup /app/data/backups/backup-$(date -u +%Y%m%dT%H%M%SZ).db
```

The command checks integrity, sets private permissions, and refuses to overwrite
an existing backup. Copy backups to another device using `docker compose cp` and
schedule them with your host's timer/cron. Backups inside the same Docker volume
do not protect against disk failure. Restore with the bot stopped, preserving the
current database and sidecar files before replacing them, and check ownership
(UID/GID 1000) and `PRAGMA integrity_check` before restarting.

## Build proxies

For a build environment with a custom trusted TLS root, pass its CA bundle as an
optional BuildKit secret. The bundle is used only during dependency installation;
it is not copied into the image. TLS and lockfile hash verification remain enabled.

```bash
docker build --secret id=build_ca,src=/path/to/trusted-ca-bundle.pem -t akinator-bot:3.0.0 .
```

## Commands

`/play`, `/cancel`, `/me`, `/leaderboard`, `/language`, `/theme`, `/childmode`,
`/help`, `/stats`, and `/admin` (private-chat admins).

See [architecture and recovery](docs/architecture.md) for invariants and scaling boundaries.
