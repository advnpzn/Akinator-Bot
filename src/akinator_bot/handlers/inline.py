"""Inline mode - text-only play in any group/chat (no images)."""

from __future__ import annotations

import html
import logging
import uuid

from telegram import (
    InlineQueryResultArticle,
    InlineQueryResultsButton,
    InputTextMessageContent,
    LinkPreviewOptions,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChosenInlineResultHandler,
    ContextTypes,
    InlineQueryHandler,
)

from akinator_bot import strings
from akinator_bot.handlers.common import ensure_user, sessions
from akinator_bot.handlers.play import _bootstrap_game, _edit_inline_text
from akinator_bot.keyboards import inline_start_keyboard
from akinator_bot.sessions import GamePhase
from akinator_bot.themes import normalize_theme

logger = logging.getLogger(__name__)

_PENDING: dict[str, dict] = {}


def _owner_label(user) -> str:
    if user.username:
        return f"@{html.escape(user.username)}"
    name = html.escape(user.first_name or "player")
    return name


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query
    if not query or not update.effective_user:
        return

    owner = update.effective_user
    result_id = f"play:{uuid.uuid4().hex[:12]}"
    _PENDING[result_id] = {"user_id": owner.id}
    if len(_PENDING) > 2000:
        for k in list(_PENDING.keys())[:1000]:
            _PENDING.pop(k, None)

    results = [
        InlineQueryResultArticle(
            id=result_id,
            title=strings.INLINE_TITLE,
            description=strings.INLINE_DESC,
            input_message_content=InputTextMessageContent(
                message_text=strings.INLINE_START_TEXT.format(
                    owner=_owner_label(owner)
                ),
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            ),
            reply_markup=inline_start_keyboard("pending", owner.id),
        )
    ]

    await query.answer(
        results,
        cache_time=5,
        is_personal=True,
        button=InlineQueryResultsButton(
            text="Open bot",
            start_parameter="inline",
        ),
    )


async def chosen_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chosen = update.chosen_inline_result
    if not chosen or not update.effective_user:
        return
    meta = _PENDING.pop(chosen.result_id, None)
    if meta is None or meta["user_id"] != update.effective_user.id:
        return
    if not chosen.inline_message_id:
        logger.warning("chosen_inline without inline_message_id")
        return

    user_row = await ensure_user(update, context)
    mgr = sessions(context)
    session = await mgr.create(
        update.effective_user.id,
        language=user_row.aki_lang,
        theme=normalize_theme(user_row.aki_theme, user_row.aki_lang),
        child_mode=user_row.child_mode,
        inline_message_id=chosen.inline_message_id,
        phase=GamePhase.PENDING,
    )

    try:
        await context.bot.edit_message_text(
            text=strings.INLINE_START_TEXT.format(
                owner=_owner_label(update.effective_user)
            ),
            inline_message_id=chosen.inline_message_id,
            parse_mode=ParseMode.HTML,
            reply_markup=inline_start_keyboard(session.session_id, session.user_id),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception as e:
        logger.warning("failed to bind inline session: %s", e)


async def inline_start_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer("Invalid button.", show_alert=True)
        return
    _, sid, owner_raw = parts
    try:
        owner_id = int(owner_raw)
    except ValueError:
        await query.answer("Invalid button.", show_alert=True)
        return

    clicker = update.effective_user
    bot = context.bot.username or "bot"
    if clicker.id != owner_id:
        await query.answer(strings.NOT_YOUR_GAME.format(bot=bot), show_alert=True)
        return

    mgr = sessions(context)
    session = mgr.get(sid) if sid != "pending" else None

    if session is None:
        if not query.inline_message_id:
            await query.answer(strings.GAME_EXPIRED, show_alert=True)
            return
        user_row = await ensure_user(update, context)
        session = await mgr.create(
            owner_id,
            language=user_row.aki_lang,
            theme=normalize_theme(user_row.aki_theme, user_row.aki_lang),
            child_mode=user_row.child_mode,
            inline_message_id=query.inline_message_id,
            phase=GamePhase.PENDING,
        )
    elif session.user_id != owner_id or session.user_id != clicker.id:
        await query.answer(strings.NOT_YOUR_GAME.format(bot=bot), show_alert=True)
        return

    if session.phase not in (GamePhase.PENDING,):
        await query.answer("Game already started.")
        return
    if session.lock.locked():
        await query.answer(strings.GAME_BUSY)
        return

    if query.inline_message_id and not session.inline_message_id:
        session.inline_message_id = query.inline_message_id

    await query.answer()
    await _edit_inline_text(context.bot, session, strings.LOADING)
    session.phase = GamePhase.PLAYING
    await _bootstrap_game(context, session)


def register(app: Application) -> None:
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(ChosenInlineResultHandler(chosen_inline))
    app.add_handler(CallbackQueryHandler(inline_start_callback, pattern=r"^is:"))
