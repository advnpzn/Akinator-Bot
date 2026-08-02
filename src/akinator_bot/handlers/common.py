"""Shared handler helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram import Update, User
from telegram.ext import ContextTypes

from akinator_bot.config import Settings
from akinator_bot.db import Database
from akinator_bot.game import GameService
from akinator_bot.sessions import SessionManager

if TYPE_CHECKING:
    pass


def db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def sessions(context: ContextTypes.DEFAULT_TYPE) -> SessionManager:
    return context.application.bot_data["sessions"]


def games(context: ContextTypes.DEFAULT_TYPE) -> GameService:
    return context.application.bot_data["games"]


def settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


async def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        raise RuntimeError("No effective user")
    cfg = settings(context)
    return await db(context).ensure_user(
        user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        language_code=user.language_code,
        default_aki_lang=cfg.default_language,
        default_child_mode=cfg.default_child_mode,
    )


def display_name(user: User | None) -> str:
    if user is None:
        return "player"
    return user.first_name or user.username or str(user.id)
