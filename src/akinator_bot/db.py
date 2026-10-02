"""Async SQLite persistence for users, stats, and leaderboards."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Literal

import aiosqlite

logger = logging.getLogger(__name__)

LeadColumn = Literal[
    "total_guess",
    "correct_guess",
    "wrong_guess",
    "total_questions",
    "win_rate",
]

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS users (
    user_id          INTEGER PRIMARY KEY,
    first_name       TEXT,
    last_name        TEXT,
    username         TEXT,
    language_code    TEXT,
    aki_lang         TEXT NOT NULL DEFAULT 'en',
    aki_theme        TEXT NOT NULL DEFAULT 'c',
    child_mode       INTEGER NOT NULL DEFAULT 1,
    total_guess      INTEGER NOT NULL DEFAULT 0,
    correct_guess    INTEGER NOT NULL DEFAULT 0,
    wrong_guess      INTEGER NOT NULL DEFAULT 0,
    unfinished_guess INTEGER NOT NULL DEFAULT 0,
    total_questions  INTEGER NOT NULL DEFAULT 0,
    first_seen_at    TEXT NOT NULL,
    last_seen_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_correct ON users(correct_guess DESC);
CREATE INDEX IF NOT EXISTS idx_users_total ON users(total_guess DESC);
CREATE INDEX IF NOT EXISTS idx_users_wrong ON users(wrong_guess DESC);
CREATE INDEX IF NOT EXISTS idx_users_questions ON users(total_questions DESC);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    event_type TEXT NOT NULL,
    user_id    INTEGER,
    detail     TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, ts DESC);
CREATE INDEX IF NOT EXISTS idx_users_recent ON users(last_seen_at DESC, user_id);
CREATE TABLE IF NOT EXISTS games (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    status TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    questions INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_games_status ON games(status);
CREATE INDEX IF NOT EXISTS idx_games_finished ON games(finished_at);
CREATE TABLE IF NOT EXISTS inline_invitations (
    inline_message_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
"""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class UserRow:
    user_id: int
    first_name: str | None
    last_name: str | None
    username: str | None
    language_code: str | None
    aki_lang: str
    aki_theme: str
    child_mode: bool
    total_guess: int
    correct_guess: int
    wrong_guess: int
    unfinished_guess: int
    total_questions: int
    first_seen_at: str
    last_seen_at: str

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        name = " ".join(p for p in (self.first_name, self.last_name) if p)
        return name or str(self.user_id)

    @property
    def win_rate(self) -> float:
        finished = self.correct_guess + self.wrong_guess
        if finished <= 0:
            return 0.0
        return 100.0 * self.correct_guess / finished

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> UserRow:
        keys = row.keys()
        return cls(
            user_id=row["user_id"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            username=row["username"],
            language_code=row["language_code"],
            aki_lang=row["aki_lang"] or "en",
            aki_theme=(row["aki_theme"] if "aki_theme" in keys else None) or "c",
            child_mode=bool(row["child_mode"]),
            total_guess=row["total_guess"] or 0,
            correct_guess=row["correct_guess"] or 0,
            wrong_guess=row["wrong_guess"] or 0,
            unfinished_guess=row["unfinished_guess"] or 0,
            total_questions=row["total_questions"] or 0,
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
        )


@dataclass(slots=True)
class LeaderboardEntry:
    rank: int
    user_id: int
    display_name: str
    value: float
    correct: int
    total: int
    win_rate: float


def serialized(method):
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        async with self.guard():
            return await method(self, *args, **kwargs)

    return wrapped


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task | None = None

    @asynccontextmanager
    async def guard(self):
        task = asyncio.current_task()
        if self._owner is task:
            yield
            return
        async with self._lock:
            self._owner = task
            try:
                yield
            finally:
                self._owner = None

    @asynccontextmanager
    async def transaction(self):
        async with self.guard():
            await self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                await self.conn.commit()
            except BaseException:
                await self.conn.rollback()
                raise

    @serialized
    async def connect(self) -> None:
        if self._db is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._db = await aiosqlite.connect(self.path)
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(SCHEMA)
            await self._migrate()
            await self._db.execute(
                "UPDATE games SET status='expired', finished_at=? WHERE finished_at IS NULL",
                (_utc_now(),),
            )
            await self._db.commit()
        except BaseException:
            await self.close()
            raise
        logger.info("SQLite ready at %s", self.path)

    async def _migrate(self) -> None:
        """Add columns introduced after the first schema."""
        assert self._db is not None
        async with self._db.execute("PRAGMA table_info(users)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        if "aki_theme" not in cols:
            await self._db.execute(
                "ALTER TABLE users ADD COLUMN aki_theme TEXT NOT NULL DEFAULT 'c'"
            )
            logger.info("migrated users.aki_theme")

    @serialized
    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database is not connected")
        return self._db

    @serialized
    async def upsert_user(
        self,
        user_id: int,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
        language_code: str | None = None,
        default_aki_lang: str = "en",
        default_child_mode: bool = True,
        default_theme: str = "c",
    ) -> UserRow:
        now = _utc_now()
        await self.conn.execute(
            """
            INSERT INTO users (
                user_id, first_name, last_name, username, language_code,
                aki_lang, aki_theme, child_mode, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                username = excluded.username,
                language_code = excluded.language_code,
                last_seen_at = excluded.last_seen_at
            """,
            (
                user_id,
                first_name,
                last_name,
                username,
                language_code,
                default_aki_lang,
                default_theme,
                1 if default_child_mode else 0,
                now,
                now,
            ),
        )
        await self.conn.commit()
        user = await self.get_user(user_id)
        assert user is not None
        return user

    @serialized
    async def get_user(self, user_id: int) -> UserRow | None:
        async with self.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        return UserRow.from_row(row) if row else None

    @serialized
    async def ensure_user(
        self,
        user_id: int,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
        language_code: str | None = None,
        default_aki_lang: str = "en",
        default_child_mode: bool = True,
        default_theme: str = "c",
    ) -> UserRow:
        existing = await self.get_user(user_id)
        if existing is None:
            return await self.upsert_user(
                user_id,
                first_name=first_name,
                last_name=last_name,
                username=username,
                language_code=language_code,
                default_aki_lang=default_aki_lang,
                default_child_mode=default_child_mode,
                default_theme=default_theme,
            )
        if (existing.first_name, existing.last_name, existing.username, existing.language_code) == (
            first_name,
            last_name,
            username,
            language_code or existing.language_code,
        ) and existing.last_seen_at[:10] == _utc_now()[:10]:
            return existing
        # Refresh changed profiles or once per day, rather than on every command.
        await self.conn.execute(
            """
            UPDATE users SET
                first_name = ?, last_name = ?, username = ?,
                language_code = COALESCE(?, language_code),
                last_seen_at = ?
            WHERE user_id = ?
            """,
            (first_name, last_name, username, language_code, _utc_now(), user_id),
        )
        await self.conn.commit()
        user = await self.get_user(user_id)
        assert user is not None
        return user

    @serialized
    async def set_language(self, user_id: int, lang: str) -> None:
        await self.conn.execute(
            "UPDATE users SET aki_lang = ?, last_seen_at = ? WHERE user_id = ?",
            (lang, _utc_now(), user_id),
        )
        await self.conn.commit()

    @serialized
    async def set_theme(self, user_id: int, theme: str) -> None:
        await self.conn.execute(
            "UPDATE users SET aki_theme = ?, last_seen_at = ? WHERE user_id = ?",
            (theme, _utc_now(), user_id),
        )
        await self.conn.commit()

    @serialized
    async def set_child_mode(self, user_id: int, enabled: bool) -> None:
        await self.conn.execute(
            "UPDATE users SET child_mode = ?, last_seen_at = ? WHERE user_id = ?",
            (1 if enabled else 0, _utc_now(), user_id),
        )
        await self.conn.commit()

    @serialized
    async def total_users(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) AS c FROM users") as cur:
            row = await cur.fetchone()
        return int(row["c"]) if row else 0

    @serialized
    async def total_games(self) -> int:
        async with self.conn.execute("SELECT COALESCE(SUM(total_guess), 0) AS c FROM users") as cur:
            row = await cur.fetchone()
        return int(row["c"]) if row else 0

    @serialized
    async def log_event(
        self,
        event_type: str,
        user_id: int | None = None,
        detail: str | None = None,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO events (ts, event_type, user_id, detail) VALUES (?, ?, ?, ?)",
            (_utc_now(), event_type, user_id, detail),
        )
        await self.conn.commit()

    @serialized
    async def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self.conn.execute(
            """
            SELECT e.ts, e.event_type, e.user_id, e.detail, u.username, u.first_name
            FROM events e
            LEFT JOIN users u ON u.user_id = e.user_id
            ORDER BY e.id DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    @serialized
    async def list_users(self, offset: int = 0, limit: int = 10) -> list[UserRow]:
        async with self.conn.execute(
            """
            SELECT * FROM users
            ORDER BY last_seen_at DESC, user_id
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [UserRow.from_row(r) for r in rows]

    @serialized
    async def leaderboard(
        self,
        category: LeadColumn,
        *,
        limit: int = 10,
        offset: int = 0,
        min_games: int = 1,
    ) -> list[LeaderboardEntry]:
        if category == "win_rate":
            # Require at least min_games finished (correct+wrong)
            sql = """
            SELECT user_id, first_name, last_name, username,
                   correct_guess, wrong_guess, total_guess, total_questions,
                   CASE
                     WHEN (correct_guess + wrong_guess) > 0
                     THEN (100.0 * correct_guess / (correct_guess + wrong_guess))
                     ELSE 0
                   END AS score
            FROM users
            WHERE (correct_guess + wrong_guess) >= ?
            ORDER BY score DESC, correct_guess DESC, total_guess DESC, user_id
            LIMIT ? OFFSET ?
            """
            params: tuple[Any, ...] = (min_games, limit, offset)
        else:
            col_map = {
                "total_guess": "total_guess",
                "correct_guess": "correct_guess",
                "wrong_guess": "wrong_guess",
                "total_questions": "total_questions",
            }
            col = col_map[category]
            sql = f"""
            SELECT user_id, first_name, last_name, username,
                   correct_guess, wrong_guess, total_guess, total_questions,
                   {col} AS score
            FROM users
            WHERE {col} > 0
            ORDER BY {col} DESC, correct_guess DESC, user_id
            LIMIT ? OFFSET ?
            """
            params = (limit, offset)

        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()

        entries: list[LeaderboardEntry] = []
        for i, row in enumerate(rows):
            uname = row["username"]
            if uname:
                display = f"@{uname}"
            else:
                name = " ".join(p for p in (row["first_name"], row["last_name"]) if p)
                display = name or str(row["user_id"])
            correct = row["correct_guess"] or 0
            wrong = row["wrong_guess"] or 0
            finished = correct + wrong
            wr = (100.0 * correct / finished) if finished else 0.0
            entries.append(
                LeaderboardEntry(
                    rank=offset + i + 1,
                    user_id=row["user_id"],
                    display_name=display,
                    value=float(row["score"] or 0),
                    correct=correct,
                    total=row["total_guess"] or 0,
                    win_rate=wr,
                )
            )
        return entries

    @serialized
    async def start_game(self, sid: str, user_id: int) -> bool:
        async with self.transaction():
            cursor = await self.conn.execute(
                "INSERT INTO games(session_id,user_id,status,started_at) "
                "VALUES(?,?,'playing',?) ON CONFLICT(session_id) DO NOTHING",
                (sid, user_id, _utc_now()),
            )
            if not cursor.rowcount:
                return False
            await self.conn.execute(
                "UPDATE users SET total_guess=total_guess+1, "
                "unfinished_guess=unfinished_guess+1 WHERE user_id=?",
                (user_id,),
            )
            await self.conn.execute(
                "INSERT INTO events(ts,event_type,user_id,detail) VALUES(?,'game_start',?,?)",
                (_utc_now(), user_id, sid),
            )
            return True

    @serialized
    async def record_action(
        self, sid: str, revision: int, delta: int, status: str, outcome: str | None = None
    ) -> bool:
        async with self.transaction():
            cursor = await self.conn.execute(
                "UPDATE games SET revision=revision+1, questions=MAX(0,questions+?), status=? "
                "WHERE session_id=? AND revision=? AND finished_at IS NULL",
                (delta, status, sid, revision),
            )
            if not cursor.rowcount:
                return False
            await self.conn.execute(
                "UPDATE users SET total_questions=MAX(0,total_questions+?) "
                "WHERE user_id=(SELECT user_id FROM games WHERE session_id=?)",
                (delta, sid),
            )
            if outcome is not None:
                await self._finish_game(sid, outcome)
            return True

    @serialized
    async def finish_game(self, sid: str, outcome: str) -> bool:
        async with self.transaction():
            return await self._finish_game(sid, outcome)

    async def _finish_game(self, sid: str, outcome: str) -> bool:
        if outcome not in {
            "correct",
            "wrong",
            "cancelled",
            "expired",
            "failed",
            "blocked",
            "soundlike",
        }:
            raise ValueError("Invalid game outcome")
        cursor = await self.conn.execute(
            "UPDATE games SET status=?, finished_at=? WHERE session_id=? AND finished_at IS NULL",
            (outcome, _utc_now(), sid),
        )
        if not cursor.rowcount:
            return False
        if outcome in {"correct", "wrong"}:
            column = "correct_guess" if outcome == "correct" else "wrong_guess"
            await self.conn.execute(
                f"UPDATE users SET {column}={column}+1, "
                "unfinished_guess=MAX(0,unfinished_guess-1) "
                "WHERE user_id=(SELECT user_id FROM games WHERE session_id=?)",
                (sid,),
            )
        await self.conn.execute(
            "INSERT INTO events(ts,event_type,user_id,detail) "
            "SELECT ?,?,user_id,session_id FROM games WHERE session_id=?",
            (_utc_now(), "game_" + outcome, sid),
        )
        return True

    @serialized
    async def prune(self, days: int) -> None:
        async with self.transaction():
            await self.conn.execute(
                "DELETE FROM events WHERE ts < strftime('%Y-%m-%dT%H:%M:%S','now',?)",
                (f"-{days} days",),
            )
            await self.conn.execute(
                "DELETE FROM games WHERE finished_at < strftime('%Y-%m-%dT%H:%M:%S','now',?)",
                (f"-{days} days",),
            )

    @serialized
    async def claim_inline(self, inline_message_id: str) -> bool:
        async with self.transaction():
            cursor = await self.conn.execute(
                "INSERT INTO inline_invitations VALUES(?,?) "
                "ON CONFLICT(inline_message_id) DO NOTHING",
                (inline_message_id, _utc_now()),
            )
            return bool(cursor.rowcount)

    @serialized
    async def ping(self) -> None:
        async with self.conn.execute("SELECT 1") as cursor:
            await cursor.fetchone()
