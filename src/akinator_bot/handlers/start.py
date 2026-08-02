""" /start /help and main menu callbacks. """

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from akinator_bot import strings
from akinator_bot.handlers.common import db, display_name, ensure_user, settings
from akinator_bot.keyboards import start_keyboard

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    await ensure_user(update, context)
    bot_user = context.bot.username or "bot"
    await update.message.reply_text(
        strings.START_MSG.format(
            name=display_name(update.effective_user),
            bot=bot_user,
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=start_keyboard(bot_user),
    )
    # deep-link: /start play
    if context.args and context.args[0].lower() in {"play", "game"}:
        from akinator_bot.handlers.play import start_game_message

        await start_game_message(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    bot_user = context.bot.username or "bot"
    await update.message.reply_text(
        strings.HELP_MSG.format(bot=bot_user),
        parse_mode=ParseMode.HTML,
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    action = query.data.split(":", 1)[-1]
    await query.answer()

    if action == "play":
        from akinator_bot.handlers.play import start_game_from_callback

        await start_game_from_callback(update, context)
        return
    if action == "lead":
        from akinator_bot.handlers.leaderboard import show_leaderboard_intro

        if query.message:
            await show_leaderboard_intro(query.message, edit=True)
        return
    if action == "me":
        from akinator_bot.handlers.settings import send_me

        await send_me(update, context, edit=True)
        return
    if action == "lang":
        from akinator_bot.handlers.settings import show_language

        await show_language(update, context, edit=True)
        return
    if action == "theme":
        from akinator_bot.handlers.settings import show_theme

        await show_theme(update, context, edit=True)
        return
    if action == "child":
        from akinator_bot.handlers.settings import show_childmode

        await show_childmode(update, context, edit=True)
        return


def register(app: Application) -> None:
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu:"))
