"""Akinator API wrapper with concurrency limits and media helpers."""

from __future__ import annotations

import asyncio
import io
import logging
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

AKITUDE_BASE = "https://en.akinator.com/assets/img/akitudes_670x1096"

# Akinator's /answer JSON no longer includes `akitude` (always None / stale defi.png).
# defi.png is also 404 on the CDN now. Map progression -> live expression assets.
# Thresholds are min progression (0-100) for that face.
_PROGRESSION_AKITUDES: list[tuple[float, str]] = [
    (0.0, "mobile.png"),                 # low confidence / thinking
    (12.0, "concentration.png"),
    (28.0, "inspiration_legere.png"),
    (45.0, "confiant.png"),
    (65.0, "inspiration_forte.png"),
    (82.0, "surprise.png"),
    (92.0, "inquiet.png"),               # very high - almost sure
]

# Filenames known to 404 or that are useless defaults from old API
_BAD_AKITUDES = frozenset({"", "defi.png", "none.png", "none.jpg"})


class GameService:
    """Creates and drives async Akinator instances behind a semaphore."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sem = asyncio.Semaphore(settings.max_concurrent_aki_calls)
        self.assets = settings.assets_dir
        # filename or url -> image bytes (Telegram cannot reliably fetch Akinator CDN)
        self._image_cache: dict[str, bytes] = {}
        self._http: httpx.AsyncClient | None = None

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

    @staticmethod
    def progression_value(aki: Akinator) -> float:
        try:
            return float(aki.progression or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def resolve_akitude_name(self, aki: Akinator) -> str:
        """Pick a CDN akitude filename for the current game state."""
        if aki.win and not getattr(aki, "finished", False):
            # Proposition phase - expression is less important; confiant works
            return "confiant.png"
        if getattr(aki, "finished", False) and not aki.win:
            return "deception.png"

        raw = (aki.akitude or "").strip()
        # Prefer API value only when it is a known-good filename
        if raw and raw not in _BAD_AKITUDES and not raw.startswith("http"):
            return raw

        prog = self.progression_value(aki)
        name = _PROGRESSION_AKITUDES[0][1]
        for threshold, fname in _PROGRESSION_AKITUDES:
            if prog >= threshold:
                name = fname
        return name

    def akitude_url(self, aki: Akinator) -> str:
        name = self.resolve_akitude_name(aki)
        if name.startswith("http"):
            return name
        return f"{AKITUDE_BASE}/{name}"

    async def fetch_image(self, url: str) -> bytes | None:
        """Download an image (cached). Returns None on failure."""
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
            # Cap cache size
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

    async def question_media(self, aki: Akinator, caption: str) -> InputMediaPhoto:
        """Akitude photo for the current question (downloaded, not URL-by-Telegram)."""
        name = self.resolve_akitude_name(aki)
        url = f"{AKITUDE_BASE}/{name}" if not name.startswith("http") else name
        media = await self.media_from_url(url, caption, filename=name)
        if media is not None:
            return media
        # Fallback: local loading asset
        path = self.loading_photo()
        return InputMediaPhoto(
            media=InputFile(path.open("rb"), filename=path.name),
            caption=caption,
            parse_mode="HTML",
        )

    async def proposition_media(self, aki: Akinator, caption: str) -> InputMediaPhoto:
        """Character photo for a win proposition."""
        photo = aki.photo or ""
        if photo:
            media = await self.media_from_url(
                photo, caption, filename="character.jpg"
            )
            if media is not None:
                return media
        # Fallback confiant akitude
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
        # Normalize default akitude; API no longer sends useful values
        if not aki.akitude or aki.akitude in _BAD_AKITUDES:
            aki.akitude = self.resolve_akitude_name(aki)
        session.aki = aki
        session.phase = GamePhase.PLAYING
        session.questions = 0
        session.touch()
        logger.info(
            "game started user=%s sid=%s lang=%s child=%s akitude=%s prog=%s",
            session.user_id,
            session.session_id,
            session.language,
            session.child_mode,
            aki.akitude,
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
        # Refresh expression from progression when API omits akitude
        if not aki.akitude or aki.akitude in _BAD_AKITUDES:
            aki.akitude = self.resolve_akitude_name(aki)
        else:
            # Still overlay progression mapping if API keeps a stale default
            mapped = self.resolve_akitude_name(aki)
            if aki.akitude in _BAD_AKITUDES:
                aki.akitude = mapped
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
                session.phase = GamePhase.PLAYING
                if not aki.akitude or aki.akitude in _BAD_AKITUDES:
                    aki.akitude = self.resolve_akitude_name(aki)

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
