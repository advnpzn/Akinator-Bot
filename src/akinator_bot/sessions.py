"""Bounded session registry; all live actions acquire the session lock."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from akipy.async_akinator import Akinator

logger = logging.getLogger(__name__)


class CapacityError(RuntimeError):
    """Admission was refused; existing games remain intact."""


class GamePhase(StrEnum):
    PENDING = "pending"
    STARTING = "starting"
    PLAYING = "playing"
    PROPOSITION = "proposition"
    DONE = "done"


@dataclass(slots=True)
class GameSession:
    session_id: str
    user_id: int
    phase: GamePhase = GamePhase.PENDING
    aki: Akinator | None = None
    questions: int = 0
    revision: int = 0
    language: str = "en"
    theme: str = "c"
    child_mode: bool = True
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
    def __init__(self, *, ttl_seconds: int = 1200, max_sessions: int = 100) -> None:
        self.ttl = ttl_seconds
        self.max_sessions = max_sessions
        self._sessions: dict[str, GameSession] = {}
        self._by_user: dict[int, str] = {}
        self._global = asyncio.Lock()

    async def create(
        self,
        user_id: int,
        *,
        language: str,
        child_mode: bool,
        theme: str = "c",
        chat_id: int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        phase: GamePhase = GamePhase.PENDING,
    ) -> GameSession:
        async with self._global:
            if user_id in self._by_user:
                raise CapacityError("Finish or cancel your current game before starting another.")
            if len(self._sessions) >= self.max_sessions:
                raise CapacityError("The bot is busy. Please try again shortly.")
            sid = secrets.token_hex(8)
            while sid in self._sessions:
                sid = secrets.token_hex(8)
            session = GameSession(
                sid,
                user_id,
                language=language,
                child_mode=child_mode,
                theme=theme,
                chat_id=chat_id,
                message_id=message_id,
                inline_message_id=inline_message_id,
                phase=phase,
            )
            self._sessions[sid] = session
            self._by_user[user_id] = sid
            return session

    def get(self, session_id: str) -> GameSession | None:
        session = self._sessions.get(session_id)
        if session and time.monotonic() - session.last_active <= self.ttl:
            return session
        return None

    def get_user_session(self, user_id: int) -> GameSession | None:
        return self.get(self._by_user.get(user_id, ""))

    async def remove(self, session_id: str, *, locked: bool = False) -> GameSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if not locked:
            async with session.lock:
                return await self.remove(session_id, locked=True)
        async with self._global:
            if self._sessions.pop(session_id, None) is None:
                return None
            self._by_user.pop(session.user_id, None)
        session.phase = GamePhase.DONE
        aki, session.aki = session.aki, None
        if aki is not None:
            try:
                await aki.close()
            except Exception:
                logger.warning("Failed to close game client sid=%s", session_id)
        return session

    async def cleanup_expired(self) -> list[GameSession]:
        now = time.monotonic()
        expired = []
        for sid, session in list(self._sessions.items()):
            if not session.lock.locked() and now - session.last_active > self.ttl:
                removed = await self.remove(sid)
                if removed:
                    expired.append(removed)
        return expired

    async def close(self) -> None:
        for sid in list(self._sessions):
            await self.remove(sid)

    @property
    def active_count(self) -> int:
        return len(self._sessions)
