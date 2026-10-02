from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from telegram import Chat, Message, PhotoSize
from telegram.error import BadRequest

from akinator_bot.keyboards import play_keyboard, win_keyboard
from akinator_bot.presentation import Renderer, Screen, game_screen


def test_question_and_proposition_rendering_escape_upstream_text(game):
    game.aki.question = '<a href="bad">Question & answer</a>'
    screen = game_screen(game.session, game.renderer.settings.assets_dir)
    assert "&lt;a" in screen.text and "&amp;" in screen.text
    assert screen.image == game.aki.akinator_image_url


@pytest.mark.parametrize("keyboard", [play_keyboard, win_keyboard])
def test_callbacks_fit_telegram_budget_and_include_revision(keyboard):
    markup = keyboard("0123456789abcdef", 123456789)
    for row in markup.inline_keyboard:
        for button in row:
            assert len(button.callback_data.encode()) <= 64
            if button.callback_data.startswith(("a:", "w:")):
                assert ":123456789:" in button.callback_data


async def test_inline_render_never_uploads_or_downloads_media(settings):
    renderer = Renderer(settings)
    from akinator_bot.sessions import GameSession

    session = GameSession("sid", 1, inline_message_id="inline")
    bot = AsyncMock()
    await renderer.edit(bot, session, Screen("question", "https://en.akinator.com/image.png"))
    bot.edit_message_text.assert_awaited_once()
    bot.edit_message_media.assert_not_awaited()
    assert renderer._http is None


async def test_successful_remote_media_does_not_eagerly_download(settings):
    renderer = Renderer(settings)
    from akinator_bot.sessions import GameSession

    bot = AsyncMock()
    session = GameSession("sid", 1, chat_id=1, message_id=1)
    await renderer.edit(bot, session, Screen("question", "https://en.akinator.com/image.png"))
    assert renderer._http is None


async def test_remote_failure_falls_back_only_when_needed(settings):
    renderer = Renderer(settings)
    from akinator_bot.sessions import GameSession

    bot = AsyncMock()
    bot.edit_message_media.side_effect = [BadRequest("URL unavailable"), True]
    renderer.download = AsyncMock(return_value=b"image-data")
    session = GameSession("sid", 1, chat_id=1, message_id=1)
    await renderer.edit(bot, session, Screen("question", "https://en.akinator.com/image.png"))
    renderer.download.assert_awaited_once()
    assert bot.edit_message_media.await_count == 2


async def test_file_ids_are_reused(settings):
    renderer = Renderer(settings)
    source = settings.assets_dir / "aki_01.png"
    message = Message(
        1, datetime.now(UTC), Chat(1, "private"), photo=[PhotoSize("file-id", "unique", 10, 10)]
    )
    renderer.remember(source, message)
    assert renderer.photo(source) == "file-id"


async def test_download_is_byte_bounded_and_rejects_internal_urls(settings):
    from dataclasses import replace

    renderer = Renderer(replace(settings, media_max_bytes=10, media_cache_bytes=12))
    calls = []

    def request(req):
        calls.append(str(req.url))
        return httpx.Response(200, content=b"12345678901", headers={"content-type": "image/png"})

    renderer._http = httpx.AsyncClient(transport=httpx.MockTransport(request))
    assert await renderer.download("http://127.0.0.1/image") is None
    assert await renderer.download("https://example.com/image") is None
    assert not calls
    assert await renderer.download("https://en.akinator.com/image") is None
    assert not renderer._bytes
    await renderer.close()


async def test_image_cache_evicts_by_total_bytes(settings):
    from dataclasses import replace

    renderer = Renderer(replace(settings, media_cache_bytes=12))
    renderer._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200, content=b"12345678", headers={"content-type": "image/png"}
            )
        )
    )
    await renderer.download("https://en.akinator.com/a")
    await renderer.download("https://en.akinator.com/b")
    assert len(renderer._bytes) == 1
    assert renderer._cache_size == 8
    await renderer.close()


async def test_redirect_is_not_followed(settings):
    renderer = Renderer(settings)
    calls = []

    def response(req):
        calls.append(req.url)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    renderer._http = httpx.AsyncClient(
        transport=httpx.MockTransport(response), follow_redirects=False
    )
    assert await renderer.download("https://en.akinator.com/image") is None
    assert len(calls) == 1
    await renderer.close()


@pytest.mark.parametrize(
    "url", ["https://en.akinator.com:bad/image", "https://user:password@en.akinator.com/image"]
)
async def test_malformed_or_authenticated_media_url_is_not_downloaded(settings, url):
    renderer = Renderer(settings)
    assert await renderer.download(url) is None
    assert renderer._http is None
