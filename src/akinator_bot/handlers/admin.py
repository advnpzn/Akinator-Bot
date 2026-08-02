"""Admin panel - secret-gated overview, users, events."""

from __future__ import annotations

import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from akinator_bot.handlers.common import db, sessions, settings

logger = logging.getLogger(__name__)

PAGE = 10


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    cfg = settings(context)
    if user.id in cfg.admin_ids:
        return True
    # One-shot secret unlock stored in user_data for the process lifetime
    return bool(context.user_data.get("admin_unlocked"))


def _kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Overview", callback_data="adm:ov"),
                InlineKeyboardButton("Users", callback_data="adm:users:0"),
            ],
            [
                InlineKeyboardButton("Events", callback_data="adm:ev:0"),
                InlineKeyboardButton("Sessions", callback_data="adm:sess"),
            ],
            [InlineKeyboardButton("Close", callback_data="adm:close")],
        ]
    )


def _kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("< Admin", callback_data="adm:menu")]]
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    cfg = settings(context)
    args = context.args or []

    # Secret unlock: /admin <secret>
    if args and cfg.admin_secret and args[0] == cfg.admin_secret:
        context.user_data["admin_unlocked"] = True
        await update.message.reply_text(
            "Admin unlocked for this session.\n"
            "Secrets are never written to logs.",
        )
        logger.info("admin secret unlock user=%s", update.effective_user.id)
        args = []

    if not _is_admin(update, context):
        await update.message.reply_text("Unknown command. Try /help")
        return

    await update.message.reply_text(
        "<b>Admin panel</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_main(),
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    if not _is_admin(update, context):
        await query.answer("Nope.", show_alert=True)
        return
    await query.answer()

    data = query.data
    if data == "adm:close":
        if query.message:
            await query.message.delete()
        return
    if data == "adm:menu":
        if query.message:
            await query.edit_message_text(
                "<b>Admin panel</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=_kb_main(),
            )
        return
    if data == "adm:ov":
        await _overview(query, context)
        return
    if data == "adm:sess":
        n = sessions(context).active_count
        if query.message:
            await query.edit_message_text(
                f"<b>Active game sessions:</b> <code>{n}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=_kb_back(),
            )
        return
    if data.startswith("adm:users:"):
        page = int(data.rsplit(":", 1)[-1])
        await _users(query, context, page)
        return
    if data.startswith("adm:ev:"):
        page = int(data.rsplit(":", 1)[-1])
        await _events(query, context, page)
        return


async def _overview(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    database = db(context)
    users = await database.total_users()
    games = await database.total_games()
    active = sessions(context).active_count
    cfg = settings(context)
    text = (
        "<b>Overview</b>\n\n"
        f"Users: <code>{users}</code>\n"
        f"Games started: <code>{games}</code>\n"
        f"Live sessions: <code>{active}</code>\n"
        f"Solver: <code>{html.escape(cfg.solver_url or 'none')}</code>\n"
        f"DB: <code>{html.escape(str(cfg.database_path))}</code>"
    )
    if query.message:
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=_kb_back()
        )


async def _users(query, context: ContextTypes.DEFAULT_TYPE, page: int) -> None:
    rows = await db(context).list_users(offset=page * PAGE, limit=PAGE + 1)
    has_more = len(rows) > PAGE
    rows = rows[:PAGE]
    lines = ["<b>Recent users</b>\n"]
    for u in rows:
        name = html.escape(u.display_name)
        lines.append(
            f"- <code>{u.user_id}</code> {name} - "
            f"{u.correct_guess}W/{u.total_guess}G\n"
        )
    if not rows:
        lines.append("<i>empty</i>")
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"adm:users:{page - 1}"))
    if has_more:
        nav.append(InlineKeyboardButton("Next", callback_data=f"adm:users:{page + 1}"))
    rows_kb = [nav] if nav else []
    rows_kb.append([InlineKeyboardButton("< Admin", callback_data="adm:menu")])
    if query.message:
        await query.edit_message_text(
            "".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows_kb),
        )


async def _events(query, context: ContextTypes.DEFAULT_TYPE, page: int) -> None:
    events = await db(context).recent_events(limit=20)
    lines = ["<b>Recent events</b>\n"]
    for e in events:
        uid = e.get("user_id") or "-"
        uname = e.get("username") or e.get("first_name") or ""
        lines.append(
            f"<code>{html.escape(str(e['ts']))}</code> "
            f"<b>{html.escape(e['event_type'])}</b> "
            f"{uid} {html.escape(str(uname))}\n"
        )
    if not events:
        lines.append("<i>none</i>")
    if query.message:
        await query.edit_message_text(
            "".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=_kb_back(),
        )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Public-ish lightweight stats; live sessions only for admins."""
    if not update.message:
        return
    database = db(context)
    users = await database.total_users()
    games_n = await database.total_games()
    text = f"Users: <b>{users}</b> | Games: <b>{games_n}</b>"
    if _is_admin(update, context):
        text += f" | Live: <b>{sessions(context).active_count}</b>"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


def register(app: Application) -> None:
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))
