"""Async SQLite persistence for users, stats, and leaderboards."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
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
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class UserRow:
    user_id: int
    first_name: str | None
    last_name: str | None
    username: str | None
    language_code: str | None
    aki_lang: str
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
        return cls(
            user_id=row["user_id"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            username=row["username"],
            language_code=row["language_code"],
            aki_lang=row["aki_lang"] or "en",
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


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info("SQLite ready at %s", self.path)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database is not connected")
        return self._db

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
    ) -> UserRow:
        now = _utc_now()
        await self.conn.execute(
            """
            INSERT INTO users (
                user_id, first_name, last_name, username, language_code,
                aki_lang, child_mode, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                1 if default_child_mode else 0,
                now,
                now,
            ),
        )
        await self.conn.commit()
        user = await self.get_user(user_id)
        assert user is not None
        return user

    async def get_user(self, user_id: int) -> UserRow | None:
        async with self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return UserRow.from_row(row) if row else None

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
            )
        # light profile refresh
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

    async def set_language(self, user_id: int, lang: str) -> None:
        await self.conn.execute(
            "UPDATE users SET aki_lang = ?, last_seen_at = ? WHERE user_id = ?",
            (lang, _utc_now(), user_id),
        )
        await self.conn.commit()

    async def set_child_mode(self, user_id: int, enabled: bool) -> None:
        await self.conn.execute(
            "UPDATE users SET child_mode = ?, last_seen_at = ? WHERE user_id = ?",
            (1 if enabled else 0, _utc_now(), user_id),
        )
        await self.conn.commit()

    async def bump_total_guess(self, user_id: int, delta: int = 1) -> None:
        await self.conn.execute(
            """
            UPDATE users SET
                total_guess = total_guess + ?,
                unfinished_guess = unfinished_guess + ?,
                last_seen_at = ?
            WHERE user_id = ?
            """,
            (delta, delta, _utc_now(), user_id),
        )
        await self.conn.commit()

    async def bump_questions(self, user_id: int, delta: int = 1) -> None:
        await self.conn.execute(
            """
            UPDATE users SET
                total_questions = MAX(0, total_questions + ?),
                last_seen_at = ?
            WHERE user_id = ?
            """,
            (delta, _utc_now(), user_id),
        )
        await self.conn.commit()

    async def record_correct(self, user_id: int) -> None:
        await self.conn.execute(
            """
            UPDATE users SET
                correct_guess = correct_guess + 1,
                unfinished_guess = MAX(0, unfinished_guess - 1),
                last_seen_at = ?
            WHERE user_id = ?
            """,
            (_utc_now(), user_id),
        )
        await self.conn.commit()

    async def record_wrong(self, user_id: int) -> None:
        await self.conn.execute(
            """
            UPDATE users SET
                wrong_guess = wrong_guess + 1,
                unfinished_guess = MAX(0, unfinished_guess - 1),
                last_seen_at = ?
            WHERE user_id = ?
            """,
            (_utc_now(), user_id),
        )
        await self.conn.commit()

    async def record_abandon(self, user_id: int) -> None:
        """Mark an unfinished game as abandoned (already counted in unfinished)."""
        await self.conn.execute(
            "UPDATE users SET last_seen_at = ? WHERE user_id = ?",
            (_utc_now(), user_id),
        )
        await self.conn.commit()

    async def total_users(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) AS c FROM users") as cur:
            row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def total_games(self) -> int:
        async with self.conn.execute(
            "SELECT COALESCE(SUM(total_guess), 0) AS c FROM users"
        ) as cur:
            row = await cur.fetchone()
        return int(row["c"]) if row else 0

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

    async def list_users(self, offset: int = 0, limit: int = 10) -> list[UserRow]:
        async with self.conn.execute(
            """
            SELECT * FROM users
            ORDER BY last_seen_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [UserRow.from_row(r) for r in rows]

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
            ORDER BY score DESC, correct_guess DESC, total_guess DESC
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
            ORDER BY {col} DESC, correct_guess DESC
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
                name = " ".join(
                    p for p in (row["first_name"], row["last_name"]) if p
                )
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
