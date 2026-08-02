"""Akinator API wrapper with concurrency limits and media helpers."""

from __future__ import annotations

import asyncio
import io
import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING

import akipy
import httpx
from akipy.async_akinator import Akinator
from telegram import InputFile, InputMediaPhoto

from akinator_bot.sessions import GamePhase, GameSession

if TYPE_CHECKING:
    from akinator_bot.config import Settings

logger = logging.getLogger(__name__)

# Bundled expression frames used while asking questions (direct /play only).
_QUESTION_ASSETS = (
    "aki_01.png",
    "aki_02.png",
    "aki_03.png",
    "aki_04.png",
    "aki_05.png",
)


class GameService:
    """Creates and drives async Akinator instances behind a semaphore."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sem = asyncio.Semaphore(settings.max_concurrent_aki_calls)
        self.assets = settings.assets_dir
        # url -> image bytes (character photos from Akinator)
        self._image_cache: dict[str, bytes] = {}
        self._http: httpx.AsyncClient | None = None
        # sid -> last question asset name (avoid back-to-back duplicates)
        self._last_question_asset: dict[str, str] = {}

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
                follow_redirects=True,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    def asset(self, name: str) -> Path:
        return self.assets / name

    def loading_photo(self) -> Path:
        p = self.asset("aki_01.png")
        return p if p.exists() else self.asset("none.jpg")

    def win_photo(self) -> Path:
        return self.asset("aki_win.png")

    def defeat_photo(self) -> Path:
        return self.asset("aki_defeat.png")

    def _local_question_pool(self) -> list[Path]:
        paths = [self.asset(n) for n in _QUESTION_ASSETS if self.asset(n).exists()]
        if not paths:
            fallback = self.loading_photo()
            if fallback.exists():
                paths = [fallback]
        return paths

    def pick_question_asset(self, session_id: str | None = None) -> Path:
        """Random local expression; avoid repeating the previous pick for this game."""
        pool = self._local_question_pool()
        if not pool:
            return self.loading_photo()
        if len(pool) == 1:
            chosen = pool[0]
        else:
            last = self._last_question_asset.get(session_id or "")
            choices = [p for p in pool if p.name != last] or pool
            chosen = random.choice(choices)
        if session_id:
            self._last_question_asset[session_id] = chosen.name
        return chosen

    def local_media(self, path: Path, caption: str) -> InputMediaPhoto:
        return InputMediaPhoto(
            media=InputFile(path.open("rb"), filename=path.name),
            caption=caption,
            parse_mode="HTML",
        )

    async def fetch_image(self, url: str) -> bytes | None:
        """Download a remote image (cached). Used for character photos only."""
        if not url:
            return None
        cached = self._image_cache.get(url)
        if cached is not None:
            return cached
        try:
            client = await self._client()
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning("image fetch %s -> %s", url, resp.status_code)
                return None
            data = resp.content
            if not data or len(data) < 100:
                return None
            if len(self._image_cache) > 64:
                for k in list(self._image_cache.keys())[:32]:
                    self._image_cache.pop(k, None)
            self._image_cache[url] = data
            return data
        except Exception as e:
            logger.warning("image fetch failed %s: %s", url, e)
            return None

    async def media_from_url(
        self,
        url: str,
        caption: str,
        *,
        filename: str = "image.png",
    ) -> InputMediaPhoto | None:
        data = await self.fetch_image(url)
        if not data:
            return None
        return InputMediaPhoto(
            media=InputFile(io.BytesIO(data), filename=filename),
            caption=caption,
            parse_mode="HTML",
        )

    async def question_media(
        self,
        aki: Akinator,
        caption: str,
        *,
        session_id: str | None = None,
    ) -> InputMediaPhoto:
        """Random bundled Akinator face for the current question."""
        path = self.pick_question_asset(session_id)
        return self.local_media(path, caption)

    async def proposition_media(self, aki: Akinator, caption: str) -> InputMediaPhoto:
        """Character photo for a win proposition (remote), else local confiant-ish frame."""
        photo = aki.photo or ""
        if photo:
            media = await self.media_from_url(
                photo, caption, filename="character.jpg"
            )
            if media is not None:
                return media
        # No remote character art: use a random local expression
        return await self.question_media(aki, caption)

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
            "game started user=%s sid=%s lang=%s child=%s prog=%s",
            session.user_id,
            session.session_id,
            session.language,
            session.child_mode,
            aki.progression,
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
                self._last_question_asset.pop(session.session_id, None)
            elif not aki.win:
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
