"""Akinator API wrapper with concurrency limits and media helpers."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import akipy
from akipy.async_akinator import Akinator
from telegram import InputMediaPhoto

from akinator_bot.sessions import GamePhase, GameSession

if TYPE_CHECKING:
    from akinator_bot.config import Settings

logger = logging.getLogger(__name__)

AKITUDE_BASE = "https://en.akinator.com/assets/img/akitudes_670x1096"


class GameService:
    """Creates and drives async Akinator instances behind a semaphore."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sem = asyncio.Semaphore(settings.max_concurrent_aki_calls)
        self.assets = settings.assets_dir

    def asset(self, name: str) -> Path:
        return self.assets / name

    def loading_photo(self) -> Path:
        p = self.asset("aki_01.png")
        return p if p.exists() else self.asset("none.jpg")

    def win_photo(self) -> Path:
        return self.asset("aki_win.png")

    def defeat_photo(self) -> Path:
        return self.asset("aki_defeat.png")

    def akitude_url(self, aki: Akinator) -> str:
        # Prefer akipy's region-aware helper when available
        try:
            url = getattr(aki, "akitude_url", None)
            if callable(url):
                got = url()
                if got:
                    return str(got)
            if isinstance(url, str) and url:
                return url
        except Exception:
            pass
        name = aki.akitude or "defi.png"
        if name.startswith("http"):
            return name
        return f"{AKITUDE_BASE}/{name}"

    def question_media(self, aki: Akinator, caption: str) -> InputMediaPhoto:
        return InputMediaPhoto(media=self.akitude_url(aki), caption=caption)

    def proposition_media(self, aki: Akinator, caption: str) -> InputMediaPhoto:
        photo = aki.photo or str(self.asset("none.jpg"))
        return InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML")

    async def start_akinator(self, session: GameSession) -> Akinator:
        """Initialise akipy Akinator for the session (solver-aware)."""
        async with self._sem:
            aki = Akinator(
                solver_url=self.settings.solver_url,
                solver_timeout=self.settings.solver_timeout_ms,
            )
            try:
                await aki.start_game(
                    language=session.language,
                    child_mode=session.child_mode,
                    game_mode=self.settings.game_theme,
                )
            except Exception:
                # Ensure client is closed on failure
                client = getattr(aki, "client", None)
                if client is not None:
                    try:
                        await client.aclose()
                    except Exception:
                        pass
                raise
        session.aki = aki
        session.phase = GamePhase.PLAYING
        session.questions = 0
        session.touch()
        logger.info(
            "game started user=%s sid=%s lang=%s child=%s",
            session.user_id,
            session.session_id,
            session.language,
            session.child_mode,
        )
        return aki

    async def answer(self, session: GameSession, choice: str) -> Akinator:
        aki = session.aki
        if aki is None:
            raise RuntimeError("No active Akinator on session")
        async with self._sem:
            if choice == "b":
                await aki.back()
            else:
                await aki.answer(choice)
        session.touch()
        if aki.win:
            session.phase = GamePhase.PROPOSITION
        return aki

    async def confirm_win(self, session: GameSession, yes: bool) -> None:
        """User confirms or rejects the proposition."""
        aki = session.aki
        if aki is None:
            return
        async with self._sem:
            try:
                if yes:
                    await aki.answer("yes")  # choose
                else:
                    await aki.answer("no")  # exclude - may continue game
            except Exception as e:
                logger.warning("confirm_win error: %s", e)
        session.touch()
        if yes or getattr(aki, "finished", False) or not aki.win:
            if yes or getattr(aki, "finished", False):
                session.phase = GamePhase.DONE
            elif not aki.win:
                # excluded and new question
                session.phase = GamePhase.PLAYING

    def map_error(self, exc: BaseException) -> str:
        if isinstance(exc, akipy.CantGoBackAnyFurther):
            return "first"
        if isinstance(exc, akipy.CloudflareBlockedError):
            return (
                "Cloudflare blocked the request. Configure SOLVER_URL "
                "(TRAWL / FlareSolverr) and try again."
            )
        if isinstance(exc, akipy.SolverError):
            return "Challenge solver failed. Please try again in a moment."
        if isinstance(exc, akipy.InvalidChoiceError):
            return "Invalid answer - try another option."
        logger.exception("Akinator error: %s", exc)
        return "Akinator timed out or failed. Please /play again."
