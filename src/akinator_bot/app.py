"""Application bootstrap."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ContextTypes

from akinator_bot.config import Settings, get_settings
from akinator_bot.db import Database
from akinator_bot.game import GameService
from akinator_bot.handlers import register_handlers
from akinator_bot.logging_setup import setup_logging
from akinator_bot.sessions import SessionManager

logger = logging.getLogger(__name__)


async def _post_init(app: Application) -> None:
    from telegram import BotCommand

    settings: Settings = app.bot_data["settings"]
    database: Database = app.bot_data["db"]
    await database.connect()

    me = await app.bot.get_me()
    app.bot_data["bot_username"] = me.username
    logger.info(
        "Bot online as @%s (id=%s) | solver=%s | db=%s",
        me.username,
        me.id,
        settings.solver_url or "direct",
        settings.database_path,
    )

    try:
        await app.bot.set_my_commands(
            [
                BotCommand("play", "Start a game"),
                BotCommand("cancel", "Cancel current game"),
                BotCommand("me", "Your stats"),
                BotCommand("leaderboard", "Rankings"),
                BotCommand("language", "Question language"),
                BotCommand("theme", "Characters, animals, or objects"),
                BotCommand("childmode", "NSFW filter on/off"),
                BotCommand("help", "How to play"),
                BotCommand("stats", "Global counters"),
            ]
        )
    except Exception as e:
        logger.warning("set_my_commands failed: %s", e)

    # Session TTL sweeper
    if app.job_queue is not None:
        async def _sweep(context: ContextTypes.DEFAULT_TYPE) -> None:
            mgr: SessionManager = context.application.bot_data["sessions"]
            await mgr.cleanup_expired()

        app.job_queue.run_repeating(_sweep, interval=60, first=60, name="session_sweep")


async def _post_shutdown(app: Application) -> None:
    database: Database = app.bot_data.get("db")  # type: ignore[assignment]
    mgr: SessionManager | None = app.bot_data.get("sessions")
    if mgr is not None:
        # best-effort close all
        for sid in list(mgr._sessions.keys()):  # noqa: SLF001
            await mgr.remove(sid)
    if database is not None:
        await database.close()
    logger.info("Shutdown complete")


def build_app(settings: Settings | None = None) -> Application:
    settings = settings or get_settings()
    setup_logging(settings)

    database = Database(settings.database_path)
    session_mgr = SessionManager(
        ttl_seconds=settings.session_ttl_seconds,
        max_sessions=settings.max_concurrent_games,
    )
    game_svc = GameService(settings)

    app = (
        Application.builder()
        .token(settings.bot_token)
        .concurrent_updates(True)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.bot_data["settings"] = settings
    app.bot_data["db"] = database
    app.bot_data["sessions"] = session_mgr
    app.bot_data["games"] = game_svc
    app.bot_data["admin_ids"] = settings.admin_ids

    register_handlers(app)
    return app


def run() -> None:
    settings = get_settings()
    app = build_app(settings)
    logger.info("Starting polling...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )
