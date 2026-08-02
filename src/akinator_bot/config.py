"""Environment-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Package root -> project root (.../Akinator-Bot)
_PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _PACKAGE_DIR.parent.parent
DEFAULT_ASSETS = PROJECT_ROOT / "assets" / "aki_pics"


def _parse_admin_ids(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return frozenset(ids)


def _bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    solver_url: str | None
    solver_timeout_ms: int
    database_path: Path
    assets_dir: Path
    admin_ids: frozenset[int]
    admin_secret: str | None
    log_level: str
    log_file: Path | None
    session_ttl_seconds: int
    max_concurrent_games: int
    max_concurrent_aki_calls: int
    game_theme: str  # c=characters, a=animals, o=objects
    default_language: str
    default_child_mode: bool

    @classmethod
    def from_env(cls) -> Settings:
        token = (os.getenv("BOT_TOKEN") or os.getenv("bot_token") or "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is required (set it in .env)")

        db = os.getenv("DATABASE_PATH", "data/akinator.db")
        assets = os.getenv("ASSETS_DIR")
        log_file = os.getenv("LOG_FILE")
        solver = (
            os.getenv("AKIPY_SOLVER_URL")
            or os.getenv("SOLVER_URL")
            or os.getenv("AKIPY_FLARESOLVERR_URL")
            or ""
        ).strip() or None

        return cls(
            bot_token=token,
            solver_url=solver,
            solver_timeout_ms=int(os.getenv("SOLVER_TIMEOUT_MS", "90000")),
            database_path=Path(db),
            assets_dir=Path(assets) if assets else DEFAULT_ASSETS,
            admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS")),
            admin_secret=(os.getenv("ADMIN_SECRET") or "").strip() or None,
            log_level=(os.getenv("LOG_LEVEL") or "INFO").upper(),
            log_file=Path(log_file) if log_file else None,
            session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "1800")),
            max_concurrent_games=int(os.getenv("MAX_CONCURRENT_GAMES", "500")),
            max_concurrent_aki_calls=int(os.getenv("MAX_CONCURRENT_AKI_CALLS", "32")),
            game_theme=(os.getenv("GAME_THEME") or "c").strip().lower()[:1],
            default_language=(os.getenv("DEFAULT_LANGUAGE") or "en").strip().lower(),
            default_child_mode=_bool(os.getenv("DEFAULT_CHILD_MODE"), True),
        )


# Lazy singleton for simple imports
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
