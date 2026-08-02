"""Inline mode - play Akinator in any group/chat."""

from __future__ import annotations

import logging
import uuid

from telegram import (
    InlineQueryResultArticle,
    InputTextMessageContent,
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
from akinator_bot.handlers.common import db, ensure_user, games, sessions
from akinator_bot.handlers.play import _bootstrap_game, _edit_caption
from akinator_bot.keyboards import inline_start_keyboard
from akinator_bot.sessions import GamePhase

logger = logging.getLogger(__name__)

# result_id prefix -> pending inline start payload stored briefly
_PENDING: dict[str, dict] = {}


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query
    if not query or not update.effective_user:
        return

    # Always show Play; optional filter by query text
    q = (query.query or "").strip().lower()
    results: list[InlineQueryResultArticle] = []

    if not q or q in {"play", "game", "aki", "start"} or "play" in q or "aki" in q:
        result_id = f"play:{uuid.uuid4().hex[:12]}"
        _PENDING[result_id] = {
            "user_id": update.effective_user.id,
        }
        # prune
        if len(_PENDING) > 2000:
            for k in list(_PENDING.keys())[:1000]:
                _PENDING.pop(k, None)

        results.append(
            InlineQueryResultArticle(
                id=result_id,
                title=strings.INLINE_TITLE,
                description=strings.INLINE_DESC,
                thumbnail_url="https://en.akinator.com/assets/img/akitudes_670x1096/defi.png",
                input_message_content=InputTextMessageContent(
                    message_text=strings.INLINE_START_TEXT,
                    parse_mode=ParseMode.HTML,
                ),
                # placeholder keyboard; replaced on chosen_inline_result with real session
                reply_markup=inline_start_keyboard("pending"),
            )
        )

    await query.answer(
        results,
        cache_time=5,
        is_personal=True,
        switch_pm_text="Open bot settings",
        switch_pm_parameter="inline",
    )


async def chosen_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create a real session bound to the inline message once the user picks a result."""
    chosen = update.chosen_inline_result
    if not chosen or not update.effective_user:
        return
    result_id = chosen.result_id
    meta = _PENDING.pop(result_id, None)
    if meta is None:
        return
    if meta["user_id"] != update.effective_user.id:
        return

    inline_message_id = chosen.inline_message_id
    if not inline_message_id:
        # Some clients omit this without reply_markup from bot - we set markup so it should exist
        logger.warning("chosen_inline without inline_message_id")
        return

    user_row = await ensure_user(update, context)
    mgr = sessions(context)
    session = await mgr.create(
        update.effective_user.id,
        language=user_row.aki_lang,
        child_mode=user_row.child_mode,
        inline_message_id=inline_message_id,
        phase=GamePhase.PENDING,
    )

    # Attach real start button with session id
    try:
        await context.bot.edit_message_text(
            text=strings.INLINE_START_TEXT,
            inline_message_id=inline_message_id,
            parse_mode=ParseMode.HTML,
            reply_markup=inline_start_keyboard(session.session_id),
        )
    except Exception as e:
        logger.warning("failed to bind inline session: %s", e)


async def inline_start_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """User tapped Start on an inline message."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    sid = query.data.split(":", 1)[1]
    mgr = sessions(context)
    session = mgr.get(sid) if sid != "pending" else None

    # Create session on first tap when chosen_inline feedback is off or still pending
    if session is None:
        if not query.inline_message_id:
            await query.answer(strings.GAME_EXPIRED, show_alert=True)
            return
        user_row = await ensure_user(update, context)
        session = await mgr.create(
            update.effective_user.id,
            language=user_row.aki_lang,
            child_mode=user_row.child_mode,
            inline_message_id=query.inline_message_id,
            phase=GamePhase.PENDING,
        )

    if session.user_id != update.effective_user.id:
        bot = context.bot.username or "bot"
        await query.answer(strings.NOT_YOUR_GAME.format(bot=bot), show_alert=True)
        return

    if session.phase not in (GamePhase.PENDING,):
        await query.answer("Game already started.")
        return

    if session.lock.locked():
        await query.answer(strings.GAME_BUSY)
        return

    # Bind inline id if chosen_inline already created the session without it
    if query.inline_message_id and not session.inline_message_id:
        session.inline_message_id = query.inline_message_id

    await query.answer()
    from telegram import InputMediaPhoto

    loading_url = "https://en.akinator.com/assets/img/akitudes_670x1096/defi.png"
    try:
        await context.bot.edit_message_media(
            media=InputMediaPhoto(media=loading_url, caption=strings.LOADING),
            inline_message_id=session.inline_message_id,
        )
    except Exception:
        await _edit_caption(context.bot, session, strings.LOADING)

    session.phase = GamePhase.PLAYING
    await _bootstrap_game(context, session)


def register(app: Application) -> None:
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(ChosenInlineResultHandler(chosen_inline))
    app.add_handler(CallbackQueryHandler(inline_start_callback, pattern=r"^is:"))
