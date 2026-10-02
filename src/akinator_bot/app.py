"""Single-process polling runtime for low-resource hosts."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path

from telegram import BotCommand, Update
from telegram.ext import AIORateLimiter, Application, ContextTypes

from akinator_bot.config import Settings, get_settings
from akinator_bot.controller import GameController
from akinator_bot.db import Database
from akinator_bot.game import GameService
from akinator_bot.handlers import register_handlers
from akinator_bot.logging_setup import setup_logging
from akinator_bot.presentation import Renderer
from akinator_bot.processing import OrderedUpdateProcessor
from akinator_bot.sessions import SessionManager

logger = logging.getLogger(__name__)


async def maintenance(app: Application) -> None:
    settings: Settings = app.bot_data["settings"]
    ticks = 0
    while True:
        if app.running:
            await app.bot_data["controller"].cleanup()
            await app.bot_data["db"].ping()
            # No handler keeps user/chat state in PTB's process dictionaries.
            for user_id in list(app.user_data):
                app.drop_user_data(user_id)
            for chat_id in list(app.chat_data):
                app.drop_chat_data(chat_id)
            if ticks % 120 == 0:
                await app.bot_data["db"].prune(settings.event_retention_days)
            # A local health check: event loop + maintenance/database readiness.
            # It deliberately does not imply upstream service availability.
            settings.health_path.touch()
            ticks += 1
        await asyncio.sleep(30)


async def _post_init(app: Application) -> None:
    settings: Settings = app.bot_data["settings"]
    try:
        await app.bot_data["db"].connect()
        me = await app.bot.get_me()
        app.bot_data["bot_username"] = me.username
        if settings.register_commands:
            await app.bot.set_my_commands(
                [
                    BotCommand(name, description)
                    for name, description in (
                        ("play", "Start a game"),
                        ("cancel", "Cancel current game"),
                        ("me", "Your stats"),
                        ("leaderboard", "Rankings"),
                        ("language", "Question language"),
                        ("theme", "Characters, animals, or objects"),
                        ("childmode", "NSFW filter"),
                        ("help", "How to play"),
                        ("stats", "Global counters"),
                    )
                ]
            )
        app.bot_data["maintenance"] = asyncio.create_task(maintenance(app), name="maintenance")
        logger.info(
            "Bot online as @%s; max games=%s, upstream concurrency=%s",
            me.username,
            settings.max_concurrent_games,
            settings.max_concurrent_aki_calls,
        )
    except BaseException:
        await app.bot_data["db"].close()
        raise


async def _post_stop(app: Application) -> None:
    task = app.bot_data.pop("maintenance", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            try:
                await task
            except Exception:
                logger.exception("Maintenance task failed")


async def _post_shutdown(app: Application) -> None:
    await _post_stop(app)
    try:
        await app.bot_data["sessions"].close()
        await app.bot_data["renderer"].close()
    finally:
        await app.bot_data["db"].close()
        app.bot_data["settings"].health_path.unlink(missing_ok=True)
    logger.info("Shutdown complete")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # The formatter redacts secrets in exception tracebacks as well as messages.
    error = context.error
    logger.error(
        "Update failed: %s",
        type(error).__name__,
        exc_info=(type(error), error, error.__traceback__),
    )


def build_app(settings: Settings | None = None) -> Application:
    settings = settings or get_settings()
    setup_logging(settings)
    if settings.admin_secret:
        logger.warning("ADMIN_SECRET unlock is disabled; configure ADMIN_IDS instead.")
    database = Database(settings.database_path)
    sessions = SessionManager(
        ttl_seconds=settings.session_ttl_seconds, max_sessions=settings.max_concurrent_games
    )
    games = GameService(settings)
    renderer = Renderer(settings)
    app = (
        Application.builder()
        .token(settings.bot_token)
        .concurrent_updates(OrderedUpdateProcessor(settings.max_concurrent_updates))
        .update_queue(asyncio.Queue(maxsize=settings.max_concurrent_updates * 4))
        .job_queue(None)
        .connection_pool_size(settings.telegram_pool_size)
        .pool_timeout(10)
        .connect_timeout(10)
        .read_timeout(20)
        .write_timeout(20)
        .rate_limiter(
            AIORateLimiter(overall_max_rate=settings.telegram_requests_per_second, max_retries=1)
        )
        .post_init(_post_init)
        .post_stop(_post_stop)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data.update(
        settings=settings,
        db=database,
        sessions=sessions,
        games=games,
        renderer=renderer,
        controller=GameController(database, sessions, games, renderer),
    )
    register_handlers(app)
    app.add_error_handler(on_error)
    return app


def run() -> None:
    import fcntl

    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(settings.database_path) + ".lock")
    # Hold the descriptor for the whole process. Protect startup reconciliation
    # and the SQLite deployment from a second poller using the same data volume.
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another bot process is using this database.") from exc
        settings.health_path.unlink(missing_ok=True)
        # Python 3.14 no longer creates an implicit loop in get_event_loop().
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            app = build_app(settings)
            app.run_polling(
                allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY, Update.INLINE_QUERY],
                drop_pending_updates=False,
                close_loop=False,
            )
        finally:
            loop.close()
            asyncio.set_event_loop(None)
