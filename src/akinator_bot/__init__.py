"""Modern concurrent Telegram Akinator bot."""

from __future__ import annotations

__version__ = "2.0.0"


def main() -> None:
    from akinator_bot.app import run

    run()
