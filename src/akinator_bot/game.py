"""Akinator adapter with bounded admission and explicit state transitions."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import akipy
import httpx
from akipy.async_akinator import Akinator

from akinator_bot.sessions import GamePhase, GameSession

if TYPE_CHECKING:
    from akinator_bot.config import Settings

logger = logging.getLogger(__name__)


class UpstreamBusy(RuntimeError):
    """No upstream slot was available; the action has not been sent."""


class GameService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sem = asyncio.Semaphore(settings.max_concurrent_aki_calls)

    @asynccontextmanager
    async def slot(self):
        try:
            async with asyncio.timeout(self.settings.admission_timeout_seconds):
                await self._sem.acquire()
        except TimeoutError as exc:
            raise UpstreamBusy("The bot is busy. Please try again shortly.") from exc
        try:
            async with asyncio.timeout(self.settings.action_timeout_seconds):
                yield
        finally:
            self._sem.release()

    @staticmethod
    def transition(session: GameSession) -> None:
        aki = session.aki
        if aki is None:
            raise RuntimeError("No active game")
        session.phase = (
            GamePhase.DONE
            if aki.finished
            else GamePhase.PROPOSITION
            if aki.win
            else GamePhase.PLAYING
        )
        session.touch()

    async def start_akinator(self, session: GameSession) -> Akinator:
        async with self.slot():
            aki = Akinator(
                solver_url=self.settings.solver_url,
                solver_timeout=self.settings.solver_timeout_ms,
            )
            # Cookies/clearance remain isolated per game. Each client needs only
            # one active connection, not httpx's default pool of 100.
            aki.client = httpx.AsyncClient(
                timeout=30,
                limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
            )
            session.aki = aki
            try:
                await aki.start_game(
                    language=session.language,
                    child_mode=session.child_mode,
                    game_mode=session.theme,
                )
            except BaseException:
                await aki.close()
                session.aki = None
                raise
        self.transition(session)
        return aki

    async def answer(self, session: GameSession, choice: str) -> Akinator:
        if choice not in {"0", "1", "2", "3", "4", "b"}:
            raise akipy.InvalidChoiceError("Invalid answer")
        aki = session.aki
        if aki is None:
            raise RuntimeError("No active game")
        async with self.slot():
            if choice == "b":
                await aki.back()
            else:
                await aki.answer(choice)
        self.transition(session)
        return aki

    async def confirm_win(self, session: GameSession, yes: bool) -> Akinator:
        aki = session.aki
        if aki is None:
            raise RuntimeError("No active game")
        async with self.slot():
            if yes:
                await aki.choose()
            else:
                await aki.exclude()
        self.transition(session)
        return aki

    @staticmethod
    def recoverable(exc: Exception) -> bool:
        # Transport failures may have changed the upstream state. Never replay
        # an uncertain answer. These errors occur before accepting an action.
        return isinstance(exc, (UpstreamBusy, akipy.CantGoBackAnyFurther, akipy.InvalidChoiceError))

    @staticmethod
    def map_error(exc: BaseException) -> str:
        if isinstance(exc, UpstreamBusy):
            return str(exc)
        if isinstance(exc, akipy.CantGoBackAnyFurther):
            return "You are already at the first question."
        if isinstance(exc, akipy.InvalidChoiceError):
            return "Invalid answer. Please use the current buttons."
        if isinstance(exc, akipy.CloudflareBlockedError):
            return "Akinator is temporarily unavailable. Please try a new game later."
        if isinstance(exc, akipy.SolverError):
            return "The challenge solver failed. Please start a new game."
        if isinstance(exc, (akipy.AkinatorServerError, TimeoutError)):
            return "This game expired or could not be confirmed. Please start a new game."
        # akipy 1.7.0 can mask an HTTP failure with a constructor TypeError.
        logger.warning("Game request failed: %s", type(exc).__name__)
        return "Akinator could not confirm this action. Please start a new game."
