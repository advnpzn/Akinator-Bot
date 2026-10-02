# Architecture and recovery

This deployment is a single asynchronous process with SQLite. Registered users
are stored on disk; only admitted active games consume session/client memory.
It does not claim million-user concurrency or automatic horizontal scaling.

## Responsibilities

- `handlers/`: validates Telegram inputs and ownership, acknowledges callbacks,
  and delegates game actions. User/chat process dictionaries retain no durable state.
- `controller.py`: orchestrates accepted actions, database records, and rendering.
- `game.py`: isolates akipy, applies admission/deadline limits, and maps outcomes.
- `sessions.py`: bounded live registry and per-session locks; never evicts live games.
- `db.py`: SQLite repositories, additive migrations, serialized transactions,
  unique game IDs, expected revisions, and one final outcome per game.
- `presentation.py`: escaped/truncated dynamic HTML, private/inline rendering,
  Telegram file IDs, byte-bounded media caches and downloads, lazy fallback.
- `processing.py`: fixed-size lock stripes serialize updates by user. Duplicate
  update IDs are retained for five minutes with a 4096-entry ceiling.
- `app.py`: bounded ingress queue/concurrency, connection pools, rate limiter,
  maintenance, process ownership, and graceful shutdown.

## Game invariants

1. One admitted game per user. Another `/play` asks them to finish/cancel first.
2. Buttons carry a game ID and expected revision. Accepted upstream actions advance
   the revision; stale buttons only refresh the current screen.
3. Cancellation and expiry cannot close a client in the middle of a locked action.
4. Counters change after upstream acceptance. A terminal transition and its final
   statistics/event record commit together. Failed or duplicate actions do not count.
5. Guess confirmation uses `choose()`/`exclude()`. An exception cannot become a win.
6. `finished`, `win`, `child_mode_blocked`, and `soundlike` are evaluated after each
   action, including startup and rejected guesses.
7. Telegram rendering happens after the commit. If an edit fails, the new revision
   stays accepted. A retry of the old button refreshes it without calling Akinator.

## Statistics

User totals survive game/event retention. `total_guess` counts successfully started
games. `total_questions` counts accepted forward answers, less accepted Back actions.
`correct_guess` counts accepted completed guesses; `wrong_guess` counts terminal
unsuccessful outcomes that are neither child-mode restrictions nor sounds-like endings.
`unfinished_guess` is the historical number of starts without a correct/wrong outcome,
including cancelled, expired, blocked, sounds-like, and failed games. It is not a live
session gauge. Existing scores are not reinterpreted during migration.

## Recovery limits

SQLite revisions and unique outcomes prevent local duplicate statistics. They do
not make upstream POST requests exactly-once. A timeout, transport failure, or
out-of-sync server response ends the uncertain game. Automatically replaying an
answer could advance the upstream game twice.

Restart reconciles unfinished ledger rows to `expired`. The bot retains pending
Telegram updates instead of requesting that they be dropped. Old callbacks cannot
find a live session after restart. Process-local update-ID suppression does not
survive restart; game buttons/outcomes provide separate protection. Non-game commands
may repeat after Telegram redelivery. Inline invitations are claimed once per
message in SQLite, so replay cannot start another game after completion or restart.
Those small claims are retained permanently to reject old invitation buttons.
This is polling, not a durable webhook inbox.

akipy 1.7.0 still has an HTTPStatusError constructor bug in its initialization error
path. The adapter treats it as a failed start and closes the allocated client; it
does not patch installed library files or pretend that the network action succeeded.

## Resource management

The update queue, update concurrency, session count, upstream concurrency, client
pools, media bytes, file-ID count, logs, event retention, and processor metadata are
bounded. Games keep separate cookie jars and small HTTP pools. Media fallback is
lazy; inline games never download/upload photos. SQLite uses WAL and a reentrant
async transaction guard so unrelated tasks cannot commit each other's work.

Profile writes are skipped when unchanged within the same day. Session cleanup and
local health checks run every 30 seconds; retention runs hourly. Full leaderboard
win-rate sorting and public aggregate statistics still query SQLite. Benchmark these
before adding a cache: avoid extra background/services at low traffic.

The bot's memory ceiling does not include the optional browser solver. A solver can
be the dominant resource consumer. Docker health status is a local readiness signal,
not an end-to-end Telegram/Akinator check or an automatic healing mechanism.

## Future scaling gates

Measure CPU/RSS, active games, action latency, upstream errors, Telegram throttling,
and SQLite latency on the Pi. Increase bounded concurrency only while all stay healthy.
If database/query latency becomes the bottleneck, add a repository adapter for PostgreSQL.
Multiple bot workers also require supported session snapshots or game ownership routing,
durable ingestion, distributed ordering, and coordinated outbound rate limiting. Simply
replicating the current poller will not work. Redis is optional until those needs exist.
