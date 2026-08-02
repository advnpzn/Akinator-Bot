"""Akinator theme helpers (characters / animals / objects)."""

from __future__ import annotations

from akipy.dicts import THEMES

THEME_LABELS: dict[str, str] = {
    "c": "Characters",
    "a": "Animals",
    "o": "Objects",
}

ALL_THEMES = ("c", "a", "o")


def themes_for_language(lang: str) -> list[str]:
    """Themes available for an Akinator language code."""
    codes = THEMES.get(lang) or THEMES.get("en") or ["c"]
    return [t for t in codes if t in THEME_LABELS]


def normalize_theme(theme: str | None, lang: str = "en") -> str:
    """Return a valid theme for the language (default characters)."""
    available = themes_for_language(lang)
    t = (theme or "c").strip().lower()[:1]
    if t in available:
        return t
    return available[0] if available else "c"


def theme_label(theme: str) -> str:
    return THEME_LABELS.get(theme, theme)
