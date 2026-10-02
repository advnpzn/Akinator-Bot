"""Inline invitations are stateless; a session is allocated only on Start."""

from __future__ import annotations

import uuid

from telegram import (
    InlineQueryResultArticle,
    InlineQueryResultsButton,
    InputTextMessageContent,
    LinkPreviewOptions,
    Update,
)
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, InlineQueryHandler

from akinator_bot import strings
from akinator_bot.handlers.common import ensure_user, sessions
from akinator_bot.handlers.play import controller
from akinator_bot.keyboards import inline_start_keyboard
from akinator_bot.presentation import Screen, escaped
from akinator_bot.sessions import CapacityError, GamePhase
from akinator_bot.themes import normalize_theme


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query
    owner = update.effective_user
    if not query or not owner:
        return
    label = (
        "@" + escaped(owner.username) if owner.username else escaped(owner.first_name or "player")
    )
    await query.answer(
        [
            InlineQueryResultArticle(
                id=uuid.uuid4().hex,
                title=strings.INLINE_TITLE,
                description=strings.INLINE_DESC,
                input_message_content=InputTextMessageContent(
                    strings.INLINE_START_TEXT.format(owner=label),
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                ),
                reply_markup=inline_start_keyboard("pending", owner.id),
            )
        ],
        cache_time=5,
        is_personal=True,
        button=InlineQueryResultsButton(text="Open bot", start_parameter="inline"),
    )


async def inline_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user or not query.inline_message_id:
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer("Invalid button.")
        return
    try:
        owner_id = int(parts[2])
    except ValueError:
        await query.answer("Invalid button.")
        return
    if owner_id != update.effective_user.id:
        await query.answer("Only the player who shared this game can start it.", show_alert=True)
        return
    ctl = controller(context)
    await ctl.cleanup()
    current = sessions(context).get_user_session(owner_id)
    if current:
        await query.answer("Finish or cancel your current game first.", show_alert=True)
        return
    # Only the stateless invitation creates a game. Old bound session IDs must
    # never resurrect expired games.
    if parts[1] != "pending":
        await query.answer("This invitation expired. Share a new game.", show_alert=True)
        return
    user = await ensure_user(update, context)
    try:
        session = await sessions(context).create(
            owner_id,
            language=user.aki_lang,
            child_mode=user.child_mode,
            theme=normalize_theme(user.aki_theme, user.aki_lang),
            inline_message_id=query.inline_message_id,
            phase=GamePhase.PENDING,
        )
    except CapacityError as exc:
        await query.answer(str(exc), show_alert=True)
        return
    try:
        if not await ctl.db.claim_inline(query.inline_message_id):
            await sessions(context).remove(session.session_id)
            await query.answer(
                "This invitation was already used. Share a new game.", show_alert=True
            )
            return
        await query.answer()
        # Bind before upstream work. The old invitation button is removed.
        await ctl.renderer.edit(context.bot, session, Screen("Starting your game..."))
        await ctl.start(context.bot, session)
    except BaseException:
        await sessions(context).remove(session.session_id)
        await ctl.db.finish_game(session.session_id, "failed")
        raise


def register(app: Application) -> None:
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(CallbackQueryHandler(inline_start_callback, pattern=r"^is:"))
