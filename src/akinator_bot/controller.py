"""Game workflows: upstream effects, atomic records, then presentation."""

from __future__ import annotations

import logging

from akinator_bot.db import Database
from akinator_bot.game import GameService
from akinator_bot.keyboards import play_again_keyboard
from akinator_bot.presentation import Renderer, Screen, game_screen
from akinator_bot.sessions import GamePhase, GameSession, SessionManager

logger = logging.getLogger(__name__)


class GameController:
    def __init__(
        self, database: Database, sessions: SessionManager, games: GameService, renderer: Renderer
    ) -> None:
        self.db = database
        self.sessions = sessions
        self.games = games
        self.renderer = renderer

    async def render(self, bot, session: GameSession) -> None:
        await self.renderer.edit(
            bot, session, game_screen(session, self.renderer.settings.assets_dir)
        )

    async def _close(self, session: GameSession, outcome: str) -> None:
        try:
            await self.db.finish_game(session.session_id, outcome)
        finally:
            await self.sessions.remove(session.session_id, locked=True)

    async def _error(self, bot, session: GameSession, exc: Exception) -> None:
        message = self.games.map_error(exc)
        if self.games.recoverable(exc) and session.aki is not None:
            screen = game_screen(session, self.renderer.settings.assets_dir)
            await self.renderer.edit(
                bot, session, Screen(message + "\n\n" + screen.text, screen.image, screen.keyboard)
            )
            return
        try:
            await self.renderer.edit(bot, session, Screen(message, keyboard=play_again_keyboard()))
        finally:
            await self._close(session, "failed")

    async def start(self, bot, session: GameSession) -> None:
        async with session.lock:
            if self.sessions.get(session.session_id) is not session or session.phase not in {
                GamePhase.PENDING,
                GamePhase.STARTING,
            }:
                return
            session.phase = GamePhase.STARTING
            try:
                await self.games.start_akinator(session)
                if not await self.db.start_game(session.session_id, session.user_id):
                    raise RuntimeError("Game was already started")
            except Exception as exc:
                await self._error(bot, session, exc)
                return
            if session.phase == GamePhase.DONE:
                await self._complete(bot, session)
            else:
                await self.render(bot, session)

    @staticmethod
    def outcome(session: GameSession) -> str:
        aki = session.aki
        if aki.child_mode_blocked:
            return "blocked"
        if aki.soundlike:
            return "soundlike"
        return "correct" if aki.win else "wrong"

    async def _complete(self, bot, session: GameSession) -> None:
        outcome = self.outcome(session)
        try:
            await self.db.finish_game(session.session_id, outcome)
            await self.render(bot, session)
        finally:
            await self.sessions.remove(session.session_id, locked=True)

    async def action(
        self, bot, session: GameSession, revision: int, choice: str, *, confirm: bool = False
    ) -> bool:
        async with session.lock:
            if self.sessions.get(session.session_id) is not session or session.aki is None:
                return False
            expected_phase = GamePhase.PROPOSITION if confirm else GamePhase.PLAYING
            if revision != session.revision or session.phase != expected_phase:
                # A previous action may have succeeded while its Telegram edit
                # failed. Re-render its latest revision without sending again.
                await self.render(bot, session)
                return False
            try:
                if confirm:
                    if choice not in {"y", "n"}:
                        return False
                    await self.games.confirm_win(session, yes=choice == "y")
                    delta = 0
                else:
                    await self.games.answer(session, choice)
                    delta = -1 if choice == "b" and session.questions else 0 if choice == "b" else 1
                if not await self.db.record_action(
                    session.session_id,
                    revision,
                    delta,
                    session.phase.value,
                    self.outcome(session) if session.phase == GamePhase.DONE else None,
                ):
                    raise RuntimeError("Game revision could not be committed")
                session.revision += 1
                session.questions += delta
            except Exception as exc:
                await self._error(bot, session, exc)
                return False
            if session.phase == GamePhase.DONE:
                await self._complete(bot, session)
            else:
                await self.render(bot, session)
            return True

    async def cancel(self, bot, session: GameSession) -> None:
        async with session.lock:
            if self.sessions.get(session.session_id) is not session:
                return
            try:
                await self.db.finish_game(session.session_id, "cancelled")
                await self.renderer.edit(
                    bot,
                    session,
                    Screen(
                        "Game cancelled. Use /play to start again.",
                        self.renderer.settings.assets_dir / "aki_defeat.png",
                        play_again_keyboard(),
                    ),
                )
            finally:
                await self.sessions.remove(session.session_id, locked=True)

    async def cleanup(self) -> None:
        for session in await self.sessions.cleanup_expired():
            await self.db.finish_game(session.session_id, "expired")
