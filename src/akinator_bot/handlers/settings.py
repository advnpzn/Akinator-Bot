"""Language, child mode, /me."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from akinator_bot import strings
from akinator_bot.handlers.common import db, ensure_user
from akinator_bot.keyboards import childmode_keyboard, language_keyboard

logger = logging.getLogger(__name__)


async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_me(update, context, edit=False)


async def send_me(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool
) -> None:
    user_row = await ensure_user(update, context)
    text = strings.ME_MSG.format(
        name=user_row.first_name or "-",
        username=user_row.username or "-",
        user_id=user_row.user_id,
        lang=strings.AKI_LANG_CODE.get(user_row.aki_lang, user_row.aki_lang),
        child="Enabled" if user_row.child_mode else "Disabled",
        total=user_row.total_guess,
        correct=user_row.correct_guess,
        wrong=user_row.wrong_guess,
        unfinished=user_row.unfinished_guess,
        questions=user_row.total_questions,
        win_rate=user_row.win_rate,
    )
    if edit and update.callback_query and update.callback_query.message:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML
        )
    elif update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    elif update.callback_query:
        await update.callback_query.message.reply_text(  # type: ignore[union-attr]
            text, parse_mode=ParseMode.HTML
        )


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_language(update, context, edit=False)


async def show_language(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool
) -> None:
    user_row = await ensure_user(update, context)
    text = strings.LANG_MSG.format(
        lang=strings.AKI_LANG_CODE.get(user_row.aki_lang, user_row.aki_lang)
    )
    markup = language_keyboard(user_row.aki_lang)
    if edit and update.callback_query and update.callback_query.message:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    elif update.message:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )


async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    lang = query.data.split(":", 1)[1]
    if lang not in strings.AKI_LANG_CODE:
        await query.answer("Unknown language", show_alert=True)
        return
    await ensure_user(update, context)
    await db(context).set_language(update.effective_user.id, lang)
    await query.answer(f"Language: {strings.AKI_LANG_CODE[lang]}")
    if query.message:
        await query.edit_message_text(
            f"Language set to <b>{strings.AKI_LANG_CODE[lang]}</b>",
            parse_mode=ParseMode.HTML,
        )


async def cmd_childmode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_childmode(update, context, edit=False)


async def show_childmode(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool
) -> None:
    user_row = await ensure_user(update, context)
    status = "enabled" if user_row.child_mode else "disabled"
    text = strings.CHILD_MSG.format(status=status)
    markup = childmode_keyboard(user_row.child_mode)
    if edit and update.callback_query and update.callback_query.message:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    elif update.message:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )


async def set_childmode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    enabled = query.data.endswith(":1")
    await ensure_user(update, context)
    await db(context).set_child_mode(update.effective_user.id, enabled)
    await query.answer("Child mode " + ("enabled" if enabled else "disabled"))
    if query.message:
        await query.edit_message_text(
            f"Child mode is now <b>{'enabled' if enabled else 'disabled'}</b>.",
            parse_mode=ParseMode.HTML,
        )


def register(app: Application) -> None:
    app.add_handler(CommandHandler("me", cmd_me))
    app.add_handler(CommandHandler("language", cmd_language))
    app.add_handler(CommandHandler("lang", cmd_language))
    app.add_handler(CommandHandler("childmode", cmd_childmode))
    app.add_handler(CallbackQueryHandler(set_language, pattern=r"^lang:"))
    app.add_handler(CallbackQueryHandler(set_childmode, pattern=r"^child:"))
