"""Inline keyboards."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from akinator_bot.strings import AKI_LANG_CODE


def start_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Play", callback_data="menu:play"),
                InlineKeyboardButton("Leaderboard", callback_data="menu:lead"),
            ],
            [
                InlineKeyboardButton("Me", callback_data="menu:me"),
                InlineKeyboardButton(
                    "Play in another chat",
                    switch_inline_query="play",
                ),
            ],
            [
                InlineKeyboardButton("Language", callback_data="menu:lang"),
                InlineKeyboardButton("Theme", callback_data="menu:theme"),
            ],
            [
                InlineKeyboardButton("Child mode", callback_data="menu:child"),
            ],
        ]
    )


def theme_keyboard(available: list[str], current: str) -> InlineKeyboardMarkup:
    from akinator_bot.themes import THEME_LABELS

    row: list[InlineKeyboardButton] = []
    for code in available:
        label = THEME_LABELS.get(code, code)
        if code == current:
            label = f"* {label}"
        row.append(InlineKeyboardButton(label, callback_data=f"theme:{code}"))
    # single row is fine (at most 3 themes)
    return InlineKeyboardMarkup([row] if row else [[]])


def language_keyboard(current: str) -> InlineKeyboardMarkup:
    codes = list(AKI_LANG_CODE.keys())
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code in codes:
        label = AKI_LANG_CODE[code]
        if code == current:
            label = f"* {label}"
        row.append(InlineKeyboardButton(label, callback_data=f"lang:{code}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def childmode_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "[on] Enable" if enabled else "Enable",
                    callback_data="child:1",
                ),
                InlineKeyboardButton(
                    "[on] Disable" if not enabled else "Disable",
                    callback_data="child:0",
                ),
            ]
        ]
    )


def play_keyboard(session_id: str) -> InlineKeyboardMarkup:
    s = session_id
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes", callback_data=f"a:{s}:0"),
                InlineKeyboardButton("No", callback_data=f"a:{s}:1"),
                InlineKeyboardButton("Probably", callback_data=f"a:{s}:3"),
            ],
            [
                InlineKeyboardButton("I don't know", callback_data=f"a:{s}:2"),
                InlineKeyboardButton("Probably not", callback_data=f"a:{s}:4"),
            ],
            [
                InlineKeyboardButton("Back", callback_data=f"a:{s}:b"),
                InlineKeyboardButton("Cancel", callback_data=f"x:{s}"),
            ],
        ]
    )


def win_keyboard(session_id: str) -> InlineKeyboardMarkup:
    s = session_id
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes", callback_data=f"w:{s}:y"),
                InlineKeyboardButton("No", callback_data=f"w:{s}:n"),
            ]
        ]
    )


def leaderboard_keyboard(active: str | None = None) -> InlineKeyboardMarkup:
    def label(key: str, text: str) -> str:
        return f"[{text}]" if active == key else text

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label("correct_guess", "Correct"),
                    callback_data="lead:correct_guess:0",
                ),
                InlineKeyboardButton(
                    label("win_rate", "Win rate"),
                    callback_data="lead:win_rate:0",
                ),
            ],
            [
                InlineKeyboardButton(
                    label("total_guess", "Games"),
                    callback_data="lead:total_guess:0",
                ),
                InlineKeyboardButton(
                    label("total_questions", "Questions"),
                    callback_data="lead:total_questions:0",
                ),
            ],
            [
                InlineKeyboardButton(
                    label("wrong_guess", "Wrong"),
                    callback_data="lead:wrong_guess:0",
                ),
            ],
        ]
    )


def leaderboard_page_keyboard(
    category: str, page: int, has_more: bool
) -> InlineKeyboardMarkup:
    base = leaderboard_keyboard(active=category)
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton("Prev", callback_data=f"lead:{category}:{page - 1}")
        )
    if has_more:
        nav.append(
            InlineKeyboardButton("Next", callback_data=f"lead:{category}:{page + 1}")
        )
    rows = list(base.inline_keyboard)
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(rows)


def inline_start_keyboard(session_id: str, owner_id: int) -> InlineKeyboardMarkup:
    """Start button encodes the owner so others cannot hijack a pending game.

    callback_data budget is 64 bytes; sid is 8 hex chars, owner fits easily.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Start game",
                    callback_data=f"is:{session_id}:{owner_id}",
                )
            ]
        ]
    )


def play_again_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Play again", callback_data="menu:play"),
                InlineKeyboardButton(
                    "Share",
                    switch_inline_query="play",
                ),
            ]
        ]
    )
