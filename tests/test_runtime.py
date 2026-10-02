import asyncio
import logging
import os
import sqlite3
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from akinator_bot.app import _post_init, _post_shutdown, build_app, maintenance
from akinator_bot.backup import backup
from akinator_bot.config import Settings
from akinator_bot.health import healthy
from akinator_bot.logging_setup import SecretFormatter
from akinator_bot.processing import OrderedUpdateProcessor
from akinator_bot.sessions import CapacityError, GamePhase, SessionManager


async def test_capacity_does_not_evict_live_games():
    manager = SessionManager(max_sessions=1)
    first = await manager.create(1, language="en", child_mode=True)
    with pytest.raises(CapacityError):
        await manager.create(2, language="en", child_mode=True)
    assert manager.get(first.session_id) is first
    with pytest.raises(CapacityError):
        await manager.create(1, language="en", child_mode=True)
    assert manager.active_count == 1
    await manager.close()


async def test_expiry_does_not_close_active_request():
    manager = SessionManager(ttl_seconds=1)
    session = await manager.create(1, language="en", child_mode=True)
    session.last_active -= 2
    async with session.lock:
        assert await manager.cleanup_expired() == []
    expired = await manager.cleanup_expired()
    assert expired == [session]
    assert manager.active_count == 0


async def test_processor_orders_one_user_and_runs_other_users_concurrently():
    processor = OrderedUpdateProcessor(4)
    entered, release, other_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    order = []

    async def first():
        order.append("first")
        entered.set()
        await release.wait()
        order.append("first-done")

    async def second():
        order.append("second")

    async def other():
        other_done.set()

    updates = [
        SimpleNamespace(update_id=i, effective_user=SimpleNamespace(id=user))
        for i, user in [(1, 1), (2, 1), (3, 2)]
    ]
    a = asyncio.create_task(processor.process_update(updates[0], first()))
    await entered.wait()
    b = asyncio.create_task(processor.process_update(updates[1], second()))
    c = asyncio.create_task(processor.process_update(updates[2], other()))
    await asyncio.wait_for(other_done.wait(), 1)
    assert order == ["first"]
    release.set()
    await asyncio.gather(a, b, c)
    assert order == ["first", "first-done", "second"]


async def test_processor_suppresses_duplicate_update_without_leaking_coroutine():
    processor = OrderedUpdateProcessor(2)
    callback = AsyncMock()
    update = SimpleNamespace(update_id=1, effective_user=SimpleNamespace(id=1))
    await processor.process_update(update, callback())
    await processor.process_update(update, callback())
    callback.assert_awaited_once()
    await processor.shutdown()
    assert not processor._seen


async def test_processor_bounds_seen_ids():
    processor = OrderedUpdateProcessor(2)
    callback = AsyncMock()
    for i in range(4200):
        await processor.process_update(
            SimpleNamespace(update_id=i, effective_user=None), callback()
        )
    assert len(processor._seen) == 4096


@pytest.mark.parametrize(
    "name",
    [
        "MAX_CONCURRENT_GAMES",
        "MAX_CONCURRENT_AKI_CALLS",
        "MAX_CONCURRENT_UPDATES",
        "MEDIA_CACHE_BYTES",
        "SESSION_TTL_SECONDS",
    ],
)
def test_configuration_rejects_unbounded_or_invalid_values(monkeypatch, name):
    monkeypatch.setenv("BOT_TOKEN", "123456:fixture")
    monkeypatch.setenv(name, "0")
    with pytest.raises(ValueError, match=name):
        Settings.from_env()


def test_token_file_is_supported(monkeypatch, tmp_path):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("bot_token", raising=False)
    token = tmp_path / "token"
    token.write_text("123456:fixture\n")
    monkeypatch.setenv("BOT_TOKEN_FILE", str(token))
    assert Settings.from_env().bot_token == "123456:fixture"


def test_logging_redacts_secrets_in_urls_and_tracebacks():
    token = "123456789:abcdefghijklmnopqrstuvwxyz_12345"
    formatter = SecretFormatter("%(message)s", secrets=(token, "private-secret"))
    try:
        raise RuntimeError("https://api.telegram.org/bot" + token + "/getMe private-secret")
    except RuntimeError as exc:
        record = logging.LogRecord(
            "test", logging.ERROR, "", 1, "failure", (), (type(exc), exc, exc.__traceback__)
        )
    text = formatter.format(record)
    assert token not in text
    assert "private-secret" not in text
    assert "[REDACTED]" in text


def test_health_requires_recent_runtime_heartbeat(tmp_path):
    path = tmp_path / "health"
    assert not healthy(path)
    path.touch()
    assert healthy(path)
    os.utime(path, (time.time() - 100, time.time() - 100))
    assert not healthy(path)


def test_backup_preserves_wal_and_does_not_overwrite(tmp_path):
    source, destination = tmp_path / "db", tmp_path / "backup"
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE records(value INTEGER)")
        conn.execute("INSERT INTO records VALUES(42)")
        conn.commit()
        backup(source, destination)
    with sqlite3.connect(destination) as conn:
        assert conn.execute("SELECT value FROM records").fetchone() == (42,)
    assert destination.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        backup(source, destination)
    with pytest.raises(ValueError):
        backup(source, source)


async def test_bootstrap_and_shutdown_close_resources_without_polling(settings):
    app = build_app(settings)
    assert isinstance(app.update_processor, OrderedUpdateProcessor)
    assert app.concurrent_updates == 16
    app.bot_data["db"].connect = AsyncMock()
    app.bot_data["db"].close = AsyncMock()
    bot = SimpleNamespace(
        get_me=AsyncMock(return_value=SimpleNamespace(username="fixture")),
        set_my_commands=AsyncMock(),
    )
    app.bot = bot
    await _post_init(app)
    bot.get_me.assert_awaited_once()
    bot.set_my_commands.assert_not_awaited()
    await _post_shutdown(app)
    app.bot_data["db"].close.assert_awaited_once()
    assert not settings.health_path.exists()


async def test_maintenance_drops_unused_framework_state_and_writes_health(settings):
    app = SimpleNamespace(
        running=True,
        user_data={1: {}},
        chat_data={2: {}},
        drop_user_data=lambda key: app.user_data.pop(key),
        drop_chat_data=lambda key: app.chat_data.pop(key),
        bot_data={
            "settings": settings,
            "controller": SimpleNamespace(cleanup=AsyncMock()),
            "db": SimpleNamespace(prune=AsyncMock(), ping=AsyncMock()),
        },
    )
    task = asyncio.create_task(maintenance(app))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not app.user_data and not app.chat_data
    assert healthy(settings.health_path)


async def test_start_failure_closes_allocated_client(game, monkeypatch):
    from akipy.async_akinator import Akinator

    from akinator_bot.game import GameService

    session = game.session
    old = session.aki
    await old.close()
    monkeypatch.setattr(Akinator, "start_game", AsyncMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        await GameService(game.renderer.settings).start_akinator(session)
    assert session.aki is None


async def test_admission_timeout_does_not_allocate_or_send_upstream(game, monkeypatch):
    from akipy.async_akinator import Akinator

    from akinator_bot.game import GameService, UpstreamBusy

    service = GameService(
        replace(game.renderer.settings, max_concurrent_aki_calls=1, admission_timeout_seconds=0.01)
    )
    start = AsyncMock()
    monkeypatch.setattr(Akinator, "start_game", start)
    await service._sem.acquire()
    with pytest.raises(UpstreamBusy):
        await service.start_akinator(game.session)
    service._sem.release()
    start.assert_not_awaited()


async def test_shutdown_closes_all_session_clients(game):
    await game.manager.close()
    assert game.aki.client is None
    assert game.session.phase == GamePhase.DONE


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DEFAULT_LANGUAGE", "unsupported"),
        ("GAME_THEME", "bad"),
        ("ADMIN_IDS", "-1"),
        ("SOLVER_URL", "file:///tmp/solver"),
        ("DEFAULT_CHILD_MODE", "maybe"),
    ],
)
def test_invalid_settings_fail_early(monkeypatch, name, value):
    monkeypatch.setenv("BOT_TOKEN", "123456:fixture")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        Settings.from_env()


def test_polling_entrypoint_owns_explicit_loop_and_retains_updates(settings, monkeypatch):
    from unittest.mock import Mock

    from akinator_bot import app as module

    monkeypatch.setattr(module, "get_settings", lambda: settings)
    app = Mock()

    def polling(**kwargs):
        assert asyncio.get_event_loop() is not None
        assert kwargs["drop_pending_updates"] is False
        assert kwargs["close_loop"] is False

    app.run_polling.side_effect = polling
    monkeypatch.setattr(module, "build_app", lambda config: app)
    module.run()
    app.run_polling.assert_called_once()
