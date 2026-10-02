"""Telegram transport for the shared game controller."""

from __future__ import annotations

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from akinator_bot.handlers.common import db, ensure_user, sessions
from akinator_bot.sessions import CapacityError, GamePhase
from akinator_bot.themes import normalize_theme


def controller(context):
    return context.application.bot_data["controller"]


async def start_game_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user:
        return
    user = await ensure_user(update, context)
    ctl = controller(context)
    # Retire expired entries before deciding admission; never evict live games.
    await ctl.cleanup()
    try:
        session = await sessions(context).create(
            user.user_id,
            language=user.aki_lang,
            child_mode=user.child_mode,
            theme=normalize_theme(user.aki_theme, user.aki_lang),
            chat_id=update.effective_chat.id,
            phase=GamePhase.STARTING,
        )
    except CapacityError as exc:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=str(exc))
        return
    try:
        message = await ctl.renderer.send_loading(context.bot, update.effective_chat.id)
        session.message_id = message.message_id
        await ctl.start(context.bot, session)
    except BaseException:
        # Sending/rendering may fail even when starting the remote game worked.
        # Retire it rather than leave an unreachable live client behind.
        await sessions(context).remove(session.session_id)
        await db(context).finish_game(session.session_id, "failed")
        raise


async def start_game_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_game_message(update, context)


async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_game_message(update, context)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    session = sessions(context).get_user_session(update.effective_user.id)
    if session is None:
        await update.message.reply_text("No active game.")
        return
    await controller(context).cancel(context.bot, session)
    await update.message.reply_text("Game cancelled.")


def owned_session(update: Update, context):
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return None
    parts = query.data.split(":")
    session = sessions(context).get(parts[1]) if len(parts) > 1 else None
    if session is None or session.user_id != update.effective_user.id:
        return None
    # A copied button must never redirect a game to another message.
    if session.is_inline:
        if query.inline_message_id != session.inline_message_id:
            return None
    elif not query.message or (query.message.chat_id, query.message.message_id) != (
        session.chat_id,
        session.message_id,
    ):
        return None
    return session


async def action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    parts = query.data.split(":")
    session = owned_session(update, context)
    if session is None or len(parts) != 4:
        await query.answer("This game expired or belongs to another player.", show_alert=True)
        return
    try:
        revision = int(parts[2])
    except ValueError:
        await query.answer("Invalid button.", show_alert=True)
        return
    allowed = {"y", "n"} if parts[0] == "w" else {"0", "1", "2", "3", "4", "b"}
    if parts[3] not in allowed:
        await query.answer("Invalid button.", show_alert=True)
        return
    # Stop the spinner before upstream calls; subsequent errors appear in the
    # shared game screen rather than trying to answer an expired callback.
    await query.answer()
    await controller(context).action(
        context.bot, session, revision, parts[3], confirm=parts[0] == "w"
    )


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    session = owned_session(update, context)
    if session is None:
        await query.answer("This game expired or belongs to another player.", show_alert=True)
        return
    await query.answer()
    await controller(context).cancel(context.bot, session)


def register(app: Application) -> None:
    app.add_handler(CommandHandler("play", cmd_play))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(action_callback, pattern=r"^[aw]:"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern=r"^x:"))
