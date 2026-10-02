from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from akipy.async_akinator import Akinator

from akinator_bot.config import Settings
from akinator_bot.controller import GameController
from akinator_bot.db import Database
from akinator_bot.game import GameService
from akinator_bot.sessions import GamePhase, SessionManager


@pytest.fixture
def settings(tmp_path):
    return Settings(
        bot_token="123456:offline-test-fixture",
        solver_url=None,
        solver_timeout_ms=60000,
        database_path=tmp_path / "bot.db",
        assets_dir=Path(__file__).parents[1] / "assets" / "aki_pics",
        admin_ids=frozenset({1}),
        admin_secret=None,
        log_level="WARNING",
        log_file=None,
        session_ttl_seconds=1200,
        max_concurrent_games=100,
        max_concurrent_aki_calls=4,
        game_theme="c",
        default_language="en",
        default_child_mode=True,
        health_path=tmp_path / "health",
    )


@pytest.fixture
async def database(settings):
    database = Database(settings.database_path)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def game(settings, database):
    await database.upsert_user(1, first_name="Player")
    manager = SessionManager()
    session = await manager.create(1, language="en", child_mode=True, phase=GamePhase.PLAYING)
    aki = Akinator()
    aki.uri = "https://en.akinator.com"
    aki.session = "session"
    aki.identifiant = "identifier"
    aki.theme = 1
    aki.question = "Current question?"
    aki.step = 0
    aki.progression = "0"
    aki._answer_depth = 0
    aki.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    session.aki = aki
    await database.start_game(session.session_id, 1)
    renderer = SimpleNamespace(settings=settings, edit=AsyncMock())
    controller = GameController(database, manager, GameService(settings), renderer)
    yield SimpleNamespace(
        session=session,
        aki=aki,
        manager=manager,
        db=database,
        controller=controller,
        renderer=renderer,
    )
    await manager.close()
    await aki.close()


@pytest.fixture
def upstream(monkeypatch):
    def configure(data, status=200):
        request = AsyncMock(
            return_value=httpx.Response(
                status,
                json=data,
                request=httpx.Request("POST", "https://en.akinator.com/answer"),
            )
        )
        monkeypatch.setattr("akipy.async_akinator.async_request_handler", request)
        return request

    return configure


@pytest.fixture(autouse=True)
def forbid_live_network(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must use mocked network transports")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
