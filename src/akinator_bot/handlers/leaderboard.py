"""Modern leaderboard with categories and pagination."""

from __future__ import annotations

import html
import logging

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from akinator_bot import strings
from akinator_bot.db import LeadColumn
from akinator_bot.handlers.common import db
from akinator_bot.keyboards import leaderboard_keyboard, leaderboard_page_keyboard

logger = logging.getLogger(__name__)

PAGE_SIZE = 10
VALID: set[str] = {
    "correct_guess",
    "total_guess",
    "wrong_guess",
    "total_questions",
    "win_rate",
}


def _bar(pct: float, width: int = 8) -> str:
    filled = max(0, min(width, round(pct / 100 * width)))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def format_leaderboard(
    category: str,
    entries,
    page: int,
) -> str:
    title = strings.LEAD_TITLES.get(category, category)
    lines = [strings.LEAD_HEADER.format(title=title)]
    if not entries:
        lines.append("<i>No scores yet - be the first with /play!</i>")
        return "".join(lines)

    for e in entries:
        medal = strings.MEDALS.get(e.rank, f"{e.rank}.")
        name = html.escape(e.display_name)
        if category == "win_rate":
            val = f"{e.value:.1f}% {_bar(e.value)} ({e.correct}W)"
        elif category == "total_questions":
            val = f"{int(e.value):,} q"
        else:
            val = f"{int(e.value):,}"
        lines.append(f"{medal} <b>{name}</b> - <code>{val}</code>\n")

    lines.append(f"\n<i>Page {page + 1}</i>")
    return "".join(lines)


async def show_leaderboard_intro(message: Message, *, edit: bool = False) -> None:
    if edit:
        await message.edit_text(
            strings.LEAD_INTRO,
            parse_mode=ParseMode.HTML,
            reply_markup=leaderboard_keyboard(),
        )
    else:
        await message.reply_text(
            strings.LEAD_INTRO,
            parse_mode=ParseMode.HTML,
            reply_markup=leaderboard_keyboard(),
        )


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await show_leaderboard_intro(update.message)


async def lead_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    parts = query.data.split(":")
    # lead:category:page
    if len(parts) < 3:
        return
    category = parts[1]
    try:
        page = int(parts[2])
    except ValueError:
        page = 0
    if category not in VALID:
        return

    offset = page * PAGE_SIZE
    entries = await db(context).leaderboard(
        category,  # type: ignore[arg-type]
        limit=PAGE_SIZE + 1,
        offset=offset,
        min_games=3 if category == "win_rate" else 1,
    )
    has_more = len(entries) > PAGE_SIZE
    entries = entries[:PAGE_SIZE]
    text = format_leaderboard(category, entries, page)
    if query.message:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=leaderboard_page_keyboard(category, page, has_more),
        )


def register(app: Application) -> None:
    app.add_handler(CommandHandler(["leaderboard", "lead", "top"], cmd_leaderboard))
    app.add_handler(CallbackQueryHandler(lead_callback, pattern=r"^lead:"))
