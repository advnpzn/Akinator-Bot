"""Telegram handlers package."""

from __future__ import annotations

from telegram.ext import Application

from akinator_bot.handlers import admin, inline, leaderboard, play, settings, start


def register_handlers(app: Application) -> None:
    start.register(app)
    settings.register(app)
    play.register(app)
    leaderboard.register(app)
    inline.register(app)
    admin.register(app)
