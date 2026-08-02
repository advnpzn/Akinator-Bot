"""UI copy and language labels."""

from __future__ import annotations

START_MSG = (
    "Hello <b>{name}</b>!\n\n"
    "I'm <b>Akinator</b> - think of a real or fictional character and I'll try to "
    "guess who it is.\n\n"
    "- <code>/play</code> - start a game here\n"
    "- Type <code>@{bot}</code> in any chat to play via inline mode\n"
    "- <code>/language</code> | <code>/theme</code> | <code>/childmode</code> | "
    "<code>/me</code> | <code>/leaderboard</code>"
)

HELP_MSG = (
    "<b>Commands</b>\n"
    "/play - start guessing\n"
    "/me - your stats\n"
    "/leaderboard - rankings\n"
    "/language - question language\n"
    "/theme - characters, animals, or objects\n"
    "/childmode - hide NSFW content\n"
    "/cancel - abandon current game\n"
    "/help - this message\n\n"
    "<b>Inline</b>\n"
    "In any group or chat, type <code>@{bot} play</code> and pick "
    "<b>Play Akinator</b>."
)

ME_MSG = (
    "<b>Your profile</b>\n\n"
    "<b>Name</b>: <code>{name}</code>\n"
    "<b>Username</b>: <code>{username}</code>\n"
    "<b>ID</b>: <code>{user_id}</code>\n"
    "<b>Language</b>: <code>{lang}</code>\n"
    "<b>Theme</b>: <code>{theme}</code>\n"
    "<b>Child mode</b>: <code>{child}</code>\n\n"
    "<b>Games</b>: <code>{total}</code>\n"
    "Correct: <code>{correct}</code>\n"
    "Wrong: <code>{wrong}</code>\n"
    "Unfinished: <code>{unfinished}</code>\n"
    "Questions answered: <code>{questions}</code>\n"
    "Win rate: <code>{win_rate:.1f}%</code>"
)

LANG_MSG = (
    "Change Akinator <b>question language</b>.\n"
    "<i>This does not change the bot UI language.</i>\n\n"
    "<b>Current:</b> <code>{lang}</code>"
)

CHILD_MSG = (
    "<b>Child mode</b> filters NSFW characters when enabled.\n\n"
    "<b>Status:</b> <code>{status}</code>"
)

THEME_MSG = (
    "Choose what Akinator should guess.\n"
    "Availability depends on your question language.\n\n"
    "<b>Current:</b> <code>{theme}</code>"
)

LEAD_INTRO = "<b>Leaderboard</b>\nPick a category:"

LEAD_HEADER = "<b>Top {title}</b>\n\n"

FIRST_QUESTION = "This is the first question - you can't go further back!"

GAME_BUSY = "Still thinking... please wait a moment."

GAME_EXPIRED = "This game session expired. Start a new one with /play"

NOT_YOUR_GAME = (
    "This isn't your game. Only the person who started it can play. "
    "Start your own with /play or @{bot}"
)

LOADING = "Loading..."

WIN_CAPTION = (
    "I think it's <b>{name}</b>!\n"
    "<i>{desc}</i>\n\n"
    "Was I correct?"
)

CORRECT_CAPTION = (
    "Answer: <b>{name}</b>\n"
    "{desc}"
    "Result: <b>correct</b>"
)
WRONG_CAPTION = (
    "Guess: <b>{name}</b>\n"
    "{desc}"
    "Result: <b>incorrect</b>"
)
CANCEL_CAPTION = "Game cancelled. Use /play when you're ready again."

INLINE_TITLE = "Play Akinator"
INLINE_DESC = "Guess the character - works in this chat"
INLINE_START_TEXT = (
    "<b>Akinator</b>\n\n"
    "Think of a character. Tap <b>Start game</b> when ready.\n"
    "<i>Only {owner} can play this round.</i>"
)

AKI_LANG_CODE: dict[str, str] = {
    "en": "English",
    "ar": "Arabic",
    "cn": "Chinese",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
    "il": "Hebrew",
    "it": "Italian",
    "jp": "Japanese",
    "kr": "Korean",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "tr": "Turkish",
    "id": "Indonesian",
}

LEAD_TITLES: dict[str, str] = {
    "correct_guess": "Correct guesses",
    "total_guess": "Games played",
    "wrong_guess": "Wrong guesses",
    "total_questions": "Questions answered",
    "win_rate": "Win rate",
}

# Plain rank prefixes (no medal glyphs)
MEDALS = {1: "#1", 2: "#2", 3: "#3"}
