"""Game play flow: /play, answers, win confirm, cancel."""

from __future__ import annotations

import logging

from telegram import InputFile, InputMediaPhoto, Message, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from akinator_bot import strings
from akinator_bot.handlers.common import db, ensure_user, games, sessions
from akinator_bot.keyboards import play_again_keyboard, play_keyboard, win_keyboard
from akinator_bot.sessions import GamePhase, GameSession


def _file_media(path, caption: str | None = None) -> InputMediaPhoto:
    # PTB/httpx need a real file handle or path string, not pathlib.Path
    return InputMediaPhoto(
        media=InputFile(path.open("rb"), filename=path.name),
        caption=caption,
    )

logger = logging.getLogger(__name__)


def _progress_caption(question: str | None, step: str | int | None, progression: str | None) -> str:
    q = question or "..."
    try:
        prog = float(progression or 0)
    except (TypeError, ValueError):
        prog = 0.0
    step_n = int(step or 0) + 1
    bar_w = 10
    filled = max(0, min(bar_w, round(prog / 100 * bar_w)))
    bar = "[" + "#" * filled + "-" * (bar_w - filled) + "]"
    return f"<b>Q{step_n}</b>  {bar} {prog:.0f}%\n\n{q}"


async def _edit_text(
    bot,
    session: GameSession,
    text: str,
    reply_markup=None,
) -> None:
    """Edit an inline (text) message. Inline games stay text-only."""
    try:
        if session.inline_message_id:
            await bot.edit_message_text(
                text=text,
                inline_message_id=session.inline_message_id,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        elif session.chat_id and session.message_id:
            await bot.edit_message_text(
                text=text,
                chat_id=session.chat_id,
                message_id=session.message_id,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        logger.warning("edit_text failed: %s", e)


async def _edit_media(
    *,
    bot,
    session: GameSession,
    media: InputMediaPhoto,
    reply_markup=None,
) -> None:
    # Inline messages start as text articles - Telegram cannot turn them into photos.
    if session.inline_message_id:
        await _edit_text(
            bot,
            session,
            media.caption or "",
            reply_markup=reply_markup,
        )
        return
    try:
        if session.chat_id and session.message_id:
            await bot.edit_message_media(
                media=media,
                chat_id=session.chat_id,
                message_id=session.message_id,
                reply_markup=reply_markup,
            )
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        logger.warning("edit_media failed: %s", e)
        try:
            caption = media.caption or ""
            if session.chat_id and session.message_id:
                await bot.edit_message_caption(
                    chat_id=session.chat_id,
                    message_id=session.message_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )
        except BadRequest:
            pass


async def _edit_caption(
    bot,
    session: GameSession,
    caption: str,
    reply_markup=None,
) -> None:
    if session.inline_message_id:
        await _edit_text(bot, session, caption, reply_markup=reply_markup)
        return
    try:
        if session.chat_id and session.message_id:
            await bot.edit_message_caption(
                chat_id=session.chat_id,
                message_id=session.message_id,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
    except BadRequest as e:
        logger.debug("edit_caption: %s", e)


async def start_game_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user_row = await ensure_user(update, context)
    svc = games(context)
    mgr = sessions(context)

    loading = svc.loading_photo()
    msg = await update.message.reply_photo(
        photo=InputFile(loading.open("rb"), filename=loading.name),
        caption=strings.LOADING,
    )
    session = await mgr.create(
        update.effective_user.id,
        language=user_row.aki_lang,
        child_mode=user_row.child_mode,
        chat_id=msg.chat_id,
        message_id=msg.message_id,
        phase=GamePhase.PLAYING,
    )
    await _bootstrap_game(context, session, msg=msg)


async def start_game_from_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Start from menu button - send a new photo message."""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    # Prefer chat message
    chat = update.effective_chat
    if chat is None:
        await query.answer("Open a private chat with me to play.", show_alert=True)
        return
    user_row = await ensure_user(update, context)
    svc = games(context)
    mgr = sessions(context)
    loading = svc.loading_photo()
    msg = await context.bot.send_photo(
        chat_id=chat.id,
        photo=InputFile(loading.open("rb"), filename=loading.name),
        caption=strings.LOADING,
    )
    session = await mgr.create(
        update.effective_user.id,
        language=user_row.aki_lang,
        child_mode=user_row.child_mode,
        chat_id=msg.chat_id,
        message_id=msg.message_id,
        phase=GamePhase.PLAYING,
    )
    await _bootstrap_game(context, session, msg=msg)


async def _bootstrap_game(
    context: ContextTypes.DEFAULT_TYPE,
    session: GameSession,
    *,
    msg: Message | None = None,
) -> None:
    svc = games(context)
    database = db(context)
    async with session.lock:
        try:
            aki = await svc.start_akinator(session)
        except Exception as e:
            err = svc.map_error(e)
            caption = f"Error: {err}"
            if msg:
                try:
                    await msg.edit_caption(caption=caption)
                except BadRequest:
                    pass
            else:
                await _edit_caption(context.bot, session, caption)
            await sessions(context).remove(session.session_id)
            return

        await database.bump_total_guess(session.user_id, 1)
        await database.log_event("game_start", session.user_id, session.session_id)

        caption = _progress_caption(aki.question, aki.step, aki.progression)
        media = InputMediaPhoto(
            media=svc.akitude_url(aki),
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
        await _edit_media(
            bot=context.bot,
            session=session,
            media=media,
            reply_markup=play_keyboard(session.session_id),
        )


async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_game_message(update, context)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    mgr = sessions(context)
    session = mgr.get_user_session(update.effective_user.id)
    if not session:
        await update.message.reply_text("No active game.")
        return
    await mgr.remove(session.session_id)
    await db(context).log_event("game_cancel", update.effective_user.id, session.session_id)
    await update.message.reply_text(strings.CANCEL_CAPTION)


async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    # a:{sid}:{choice}
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, sid, choice = parts
    mgr = sessions(context)
    session = mgr.get(sid)
    if session is None:
        await query.answer(strings.GAME_EXPIRED, show_alert=True)
        return
    if session.user_id != update.effective_user.id:
        bot = context.bot.username or "bot"
        await query.answer(strings.NOT_YOUR_GAME.format(bot=bot), show_alert=True)
        return
    if session.phase not in (GamePhase.PLAYING,):
        await query.answer("Wait for the next prompt...")
        return

    if session.lock.locked():
        await query.answer(strings.GAME_BUSY)
        return

    async with session.lock:
        # re-check after lock
        session = mgr.get(sid)
        if session is None or session.aki is None:
            await query.answer(strings.GAME_EXPIRED, show_alert=True)
            return

        svc = games(context)
        database = db(context)

        if choice != "b":
            await database.bump_questions(session.user_id, 1)
            session.questions += 1
        else:
            # back: undo last question count if any
            if session.questions > 0:
                await database.bump_questions(session.user_id, -1)
                session.questions -= 1

        try:
            aki = await svc.answer(session, choice)
        except Exception as e:
            mapped = svc.map_error(e)
            if mapped == "first":
                await query.answer(strings.FIRST_QUESTION, show_alert=True)
                return
            await query.answer(mapped, show_alert=True)
            return

        await query.answer()

        if aki.win:
            session.phase = GamePhase.PROPOSITION
            caption = strings.WIN_CAPTION.format(
                name=aki.name_proposition or "???",
                desc=aki.description_proposition or "",
            )
            media = svc.proposition_media(aki, caption)
            await _edit_media(
                bot=context.bot,
                session=session,
                media=media,
                reply_markup=win_keyboard(session.session_id),
            )
        else:
            caption = _progress_caption(aki.question, aki.step, aki.progression)
            media = InputMediaPhoto(
                media=svc.akitude_url(aki),
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            await _edit_media(
                bot=context.bot,
                session=session,
                media=media,
                reply_markup=play_keyboard(session.session_id),
            )


async def win_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, sid, ans = parts
    mgr = sessions(context)
    session = mgr.get(sid)
    if session is None:
        await query.answer(strings.GAME_EXPIRED, show_alert=True)
        return
    if session.user_id != update.effective_user.id:
        bot = context.bot.username or "bot"
        await query.answer(
            strings.NOT_YOUR_GAME.format(bot=bot),
            show_alert=True,
        )
        return
    if session.phase != GamePhase.PROPOSITION:
        await query.answer()
        return
    if session.lock.locked():
        await query.answer(strings.GAME_BUSY)
        return

    async with session.lock:
        session = mgr.get(sid)
        if session is None:
            await query.answer(strings.GAME_EXPIRED, show_alert=True)
            return
        svc = games(context)
        database = db(context)
        yes = ans == "y"

        try:
            await svc.confirm_win(session, yes=yes)
        except Exception as e:
            logger.warning("confirm_win: %s", e)

        aki = session.aki
        # Continue game after wrong exclude
        if not yes and aki is not None and not aki.win and not getattr(aki, "finished", False):
            session.phase = GamePhase.PLAYING
            await query.answer("Hmm, let me try again...")
            caption = _progress_caption(aki.question, aki.step, aki.progression)
            media = InputMediaPhoto(
                media=svc.akitude_url(aki),
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            await _edit_media(
                bot=context.bot,
                session=session,
                media=media,
                reply_markup=play_keyboard(session.session_id),
            )
            return

        await query.answer()
        if yes:
            await database.record_correct(session.user_id)
            await database.log_event("game_win", session.user_id, session.session_id)
            photo = svc.win_photo()
            caption = strings.CORRECT_CAPTION
        else:
            await database.record_wrong(session.user_id)
            await database.log_event("game_lose", session.user_id, session.session_id)
            photo = svc.defeat_photo()
            caption = strings.WRONG_CAPTION

        media = _file_media(photo, caption) if photo.exists() else InputMediaPhoto(
            media="https://en.akinator.com/assets/img/akitudes_670x1096/triomphe.png",
            caption=caption,
        )
        await _edit_media(
            bot=context.bot,
            session=session,
            media=media,
            reply_markup=play_again_keyboard() if not session.is_inline else None,
        )
        session.phase = GamePhase.DONE
        await mgr.remove(session.session_id)


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    sid = query.data.split(":", 1)[1]
    mgr = sessions(context)
    session = mgr.get(sid)
    if session is None:
        await query.answer(strings.GAME_EXPIRED, show_alert=True)
        return
    if session.user_id != update.effective_user.id:
        bot = context.bot.username or "bot"
        await query.answer(
            strings.NOT_YOUR_GAME.format(bot=bot),
            show_alert=True,
        )
        return
    await mgr.remove(sid)
    await db(context).log_event("game_cancel", update.effective_user.id, sid)
    await query.answer("Cancelled")
    svc = games(context)
    photo = svc.defeat_photo()
    media = (
        _file_media(photo, strings.CANCEL_CAPTION)
        if photo.exists()
        else InputMediaPhoto(
            media="https://en.akinator.com/assets/img/akitudes_670x1096/deception.png",
            caption=strings.CANCEL_CAPTION,
        )
    )
    session.inline_message_id = session.inline_message_id  # keep targets
    # session already removed - use saved targets
    try:
        if session.inline_message_id:
            await context.bot.edit_message_media(
                media=media,
                inline_message_id=session.inline_message_id,
            )
        elif session.chat_id and session.message_id:
            await context.bot.edit_message_media(
                media=media,
                chat_id=session.chat_id,
                message_id=session.message_id,
                reply_markup=play_again_keyboard(),
            )
    except BadRequest:
        pass


def register(app: Application) -> None:
    app.add_handler(CommandHandler("play", cmd_play))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(answer_callback, pattern=r"^a:"))
    app.add_handler(CallbackQueryHandler(win_callback, pattern=r"^w:"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern=r"^x:"))
