"""In-memory concurrent game session store."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from akipy.async_akinator import Akinator

logger = logging.getLogger(__name__)


class GamePhase(str, Enum):
    PENDING = "pending"  # inline message waiting for Start
    PLAYING = "playing"
    PROPOSITION = "proposition"  # Akinator guessed, awaiting yes/no
    DONE = "done"


@dataclass
class GameSession:
    session_id: str
    user_id: int
    phase: GamePhase = GamePhase.PENDING
    aki: Akinator | None = None
    questions: int = 0
    language: str = "en"
    child_mode: bool = True
    # message targeting
    chat_id: int | None = None
    message_id: int | None = None
    inline_message_id: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    last_active: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def touch(self) -> None:
        self.last_active = time.monotonic()

    @property
    def is_inline(self) -> bool:
        return self.inline_message_id is not None


class SessionManager:
    """Thread-safe (asyncio) registry of active games.

    One active session per user. Callback data embeds ``session_id`` so stale
    buttons are rejected cleanly.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 1800,
        max_sessions: int = 500,
    ) -> None:
        self.ttl = ttl_seconds
        self.max_sessions = max_sessions
        self._sessions: dict[str, GameSession] = {}
        self._by_user: dict[int, str] = {}
        self._global = asyncio.Lock()

    def _new_id(self) -> str:
        # 8 hex chars → fits Telegram callback_data budget with room to spare
        return secrets.token_hex(4)

    async def create(
        self,
        user_id: int,
        *,
        language: str,
        child_mode: bool,
        chat_id: int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        phase: GamePhase = GamePhase.PENDING,
    ) -> GameSession:
        async with self._global:
            await self._drop_user_locked(user_id)
            await self._evict_if_needed_locked()

            sid = self._new_id()
            while sid in self._sessions:
                sid = self._new_id()

            session = GameSession(
                session_id=sid,
                user_id=user_id,
                phase=phase,
                language=language,
                child_mode=child_mode,
                chat_id=chat_id,
                message_id=message_id,
                inline_message_id=inline_message_id,
            )
            self._sessions[sid] = session
            self._by_user[user_id] = sid
            logger.debug("session created sid=%s user=%s", sid, user_id)
            return session

    def get(self, session_id: str) -> GameSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if time.monotonic() - session.last_active > self.ttl:
            return None
        return session

    def get_user_session(self, user_id: int) -> GameSession | None:
        sid = self._by_user.get(user_id)
        if not sid:
            return None
        return self.get(sid)

    async def remove(self, session_id: str) -> GameSession | None:
        async with self._global:
            return await self._remove_locked(session_id)

    async def _remove_locked(self, session_id: str) -> GameSession | None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return None
        if self._by_user.get(session.user_id) == session_id:
            self._by_user.pop(session.user_id, None)
        await self._close_aki(session)
        logger.debug("session removed sid=%s user=%s", session_id, session.user_id)
        return session

    async def _drop_user_locked(self, user_id: int) -> None:
        sid = self._by_user.get(user_id)
        if sid:
            await self._remove_locked(sid)

    async def _evict_if_needed_locked(self) -> None:
        if len(self._sessions) < self.max_sessions:
            return
        # Drop oldest by last_active
        oldest = sorted(self._sessions.values(), key=lambda s: s.last_active)
        for s in oldest[: max(1, len(oldest) // 10)]:
            await self._remove_locked(s.session_id)

    async def cleanup_expired(self) -> int:
        now = time.monotonic()
        async with self._global:
            expired = [
                sid
                for sid, s in self._sessions.items()
                if now - s.last_active > self.ttl
            ]
            for sid in expired:
                await self._remove_locked(sid)
        if expired:
            logger.info("expired %d game session(s)", len(expired))
        return len(expired)

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    @staticmethod
    async def _close_aki(session: GameSession) -> None:
        aki = session.aki
        session.aki = None
        if aki is None:
            return
        client = getattr(aki, "client", None)
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                logger.debug("failed closing aki client", exc_info=True)
