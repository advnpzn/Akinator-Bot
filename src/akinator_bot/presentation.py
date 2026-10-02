"""Shared safe rendering and bounded, lazy media delivery."""

from __future__ import annotations

import html
import logging
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from telegram import InputFile, InputMediaPhoto, LinkPreviewOptions, Message
from telegram.error import BadRequest

from akinator_bot.config import Settings
from akinator_bot.keyboards import play_again_keyboard, play_keyboard, win_keyboard
from akinator_bot.sessions import GamePhase, GameSession

logger = logging.getLogger(__name__)


def escaped(value: object, limit: int = 350) -> str:
    return html.escape(str(value or "")[:limit])


@dataclass(frozen=True, slots=True)
class Screen:
    text: str
    image: str | Path | None = None
    keyboard: object = None


def game_screen(session: GameSession, assets: Path) -> Screen:
    aki = session.aki
    if aki is None:
        return Screen("This game has ended. Use /play to start again.", assets / "aki_defeat.png")
    if session.phase == GamePhase.DONE:
        if aki.child_mode_blocked:
            text = "This character is hidden by child mode. Start a new game or change /childmode."
        elif aki.soundlike:
            text = "Akinator has no more guesses. Thanks for playing!"
        elif aki.win:
            text = f"Akinator guessed <b>{escaped(aki.name_proposition, 200)}</b>!"
        else:
            text = "The game has ended. Thanks for playing!"
        return Screen(
            text, assets / ("aki_win.png" if aki.win else "aki_defeat.png"), play_again_keyboard()
        )
    if session.phase == GamePhase.PROPOSITION:
        return Screen(
            f"Is it <b>{escaped(aki.name_proposition, 200)}</b>?\n"
            f"<i>{escaped(aki.description_proposition, 300)}</i>",
            aki.photo or assets / "aki_win.png",
            win_keyboard(session.session_id, session.revision),
        )
    try:
        progress = max(0, min(100, float(aki.progression or 0)))
        step = max(0, int(aki.step or 0)) + 1
    except (TypeError, ValueError):
        progress, step = 0, 1
    return Screen(
        f"<b>Q{step}</b> | {progress:.0f}%\n\n{escaped(aki.question, 500)}",
        aki.akinator_image_url or assets / "aki_01.png",
        play_keyboard(session.session_id, session.revision),
    )


class Renderer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._files: OrderedDict[str, str] = OrderedDict()
        self._bytes: OrderedDict[str, bytes] = OrderedDict()
        self._cache_size = 0
        self._http: httpx.AsyncClient | None = None

    def photo(self, source: str | Path):
        key = str(source)
        if key in self._files:
            self._files.move_to_end(key)
            return self._files[key]
        if isinstance(source, Path):
            return InputFile(source.read_bytes(), filename=source.name)
        return source

    def remember(self, source: str | Path | None, message) -> None:
        if source is not None and isinstance(message, Message) and message.photo:
            self._files[str(source)] = message.photo[-1].file_id
            self._files.move_to_end(str(source))
            while len(self._files) > 128:
                self._files.popitem(last=False)

    async def download(self, url: str) -> bytes | None:
        # Only fetch expected Akinator image hosts; never follow redirects to
        # arbitrary internal addresses returned in an upstream response.
        if url in self._bytes:
            self._bytes.move_to_end(url)
            return self._bytes[url]
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            return None
        host = parsed.hostname or ""
        allowed = any(
            host == base or host.endswith("." + base) for base in ("akinator.com", "clarinea.com")
        )
        if (
            parsed.scheme != "https"
            or not allowed
            or port not in (None, 443)
            or parsed.username
            or parsed.password
        ):
            return None
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=15,
                follow_redirects=False,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            )
        try:
            async with self._http.stream("GET", url) as response:
                if response.status_code != 200 or not response.headers.get(
                    "content-type", ""
                ).startswith("image/"):
                    return None
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    data.extend(chunk)
                    if len(data) > self.settings.media_max_bytes:
                        return None
            if not data:
                return None
            result = bytes(data)
            if len(result) <= self.settings.media_cache_bytes:
                while (
                    self._bytes and self._cache_size + len(result) > self.settings.media_cache_bytes
                ):
                    _, removed = self._bytes.popitem(last=False)
                    self._cache_size -= len(removed)
                self._bytes[url] = result
                self._cache_size += len(result)
            return result
        except httpx.HTTPError:
            return None

    async def send_loading(self, bot, chat_id: int) -> Message:
        path = self.settings.assets_dir / "aki_01.png"
        result = await bot.send_photo(
            chat_id=chat_id, photo=self.photo(path), caption="Starting your game..."
        )
        self.remember(path, result)
        return result

    async def edit(self, bot, session: GameSession, screen: Screen) -> None:
        if session.is_inline:
            try:
                await bot.edit_message_text(
                    inline_message_id=session.inline_message_id,
                    text=screen.text,
                    parse_mode="HTML",
                    reply_markup=screen.keyboard,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
            except BadRequest as exc:
                if "not modified" not in str(exc).lower():
                    raise
            return
        if not session.chat_id or not session.message_id:
            return
        target = {"chat_id": session.chat_id, "message_id": session.message_id}
        source = screen.image or self.settings.assets_dir / "aki_01.png"
        try:
            result = await bot.edit_message_media(
                **target,
                media=InputMediaPhoto(self.photo(source), caption=screen.text, parse_mode="HTML"),
                reply_markup=screen.keyboard,
            )
            self.remember(source, result)
            return
        except BadRequest as exc:
            if "not modified" in str(exc).lower():
                return
            # File IDs can become invalid. Do not reuse one indefinitely.
            self._files.pop(str(source), None)
        if isinstance(source, str):
            data = await self.download(source)
            if data:
                try:
                    result = await bot.edit_message_media(
                        **target,
                        media=InputMediaPhoto(
                            InputFile(data, filename="image.png"),
                            caption=screen.text,
                            parse_mode="HTML",
                        ),
                        reply_markup=screen.keyboard,
                    )
                    self.remember(source, result)
                    return
                except BadRequest:
                    pass
        # Keep the last image if remote media fails; preserve playable controls.
        try:
            await bot.edit_message_caption(
                **target, caption=screen.text, parse_mode="HTML", reply_markup=screen.keyboard
            )
        except BadRequest as exc:
            if "not modified" not in str(exc).lower():
                raise

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
        self._files.clear()
        self._bytes.clear()
        self._cache_size = 0
