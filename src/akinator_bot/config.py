"""Environment-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from akipy.dicts import THEMES
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
            user_id = int(part)
            if user_id <= 0:
                raise ValueError
            ids.add(user_id)
        except ValueError as exc:
            raise ValueError("ADMIN_IDS must contain positive Telegram user IDs") from exc
    return frozenset(ids)


def _bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if value not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        raise ValueError("Boolean settings must be true or false")
    return value in {"1", "true", "yes", "on"}


def _integer(name: str, default: int, maximum: int = 1_000_000) -> int:
    value = int(os.getenv(name, str(default)))
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


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
    max_concurrent_updates: int = 16
    action_timeout_seconds: int = 120
    admission_timeout_seconds: int = 2
    telegram_pool_size: int = 16
    telegram_requests_per_second: int = 20
    media_cache_bytes: int = 4 * 1024 * 1024
    media_max_bytes: int = 2 * 1024 * 1024
    event_retention_days: int = 30
    health_path: Path = Path("/tmp/akinator-bot.health")
    register_commands: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        token = (os.getenv("BOT_TOKEN") or os.getenv("bot_token") or "").strip()
        if not token and os.getenv("BOT_TOKEN_FILE"):
            token = Path(os.environ["BOT_TOKEN_FILE"]).read_text().strip()
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
        if solver:
            parsed = urlsplit(solver)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("SOLVER_URL must be an HTTP(S) URL")
        language = (os.getenv("DEFAULT_LANGUAGE") or "en").strip().lower()
        theme = (os.getenv("GAME_THEME") or "c").strip().lower()
        if language not in THEMES:
            raise ValueError("DEFAULT_LANGUAGE is not supported by akipy")
        if theme not in THEMES[language]:
            raise ValueError("GAME_THEME is not available for DEFAULT_LANGUAGE")

        return cls(
            bot_token=token,
            solver_url=solver,
            solver_timeout_ms=_integer("SOLVER_TIMEOUT_MS", 60000, 120000),
            database_path=Path(db),
            assets_dir=Path(assets) if assets else DEFAULT_ASSETS,
            admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS")),
            admin_secret=(os.getenv("ADMIN_SECRET") or "").strip() or None,
            log_level=(os.getenv("LOG_LEVEL") or "INFO").upper(),
            log_file=Path(log_file) if log_file else None,
            session_ttl_seconds=_integer("SESSION_TTL_SECONDS", 1200, 86400),
            max_concurrent_games=_integer("MAX_CONCURRENT_GAMES", 100, 10000),
            max_concurrent_aki_calls=_integer("MAX_CONCURRENT_AKI_CALLS", 4, 128),
            game_theme=theme,
            default_language=language,
            default_child_mode=_bool(os.getenv("DEFAULT_CHILD_MODE"), True),
            max_concurrent_updates=_integer("MAX_CONCURRENT_UPDATES", 16, 256),
            action_timeout_seconds=_integer("ACTION_TIMEOUT_SECONDS", 120, 300),
            admission_timeout_seconds=_integer("ADMISSION_TIMEOUT_SECONDS", 2, 10),
            telegram_pool_size=_integer("TELEGRAM_POOL_SIZE", 16, 256),
            telegram_requests_per_second=_integer("TELEGRAM_REQUESTS_PER_SECOND", 20, 30),
            media_cache_bytes=_integer("MEDIA_CACHE_BYTES", 4 * 1024 * 1024, 64 * 1024 * 1024),
            media_max_bytes=_integer("MEDIA_MAX_BYTES", 2 * 1024 * 1024, 10 * 1024 * 1024),
            event_retention_days=_integer("EVENT_RETENTION_DAYS", 30, 365),
            health_path=Path(os.getenv("HEALTH_PATH", "/tmp/akinator-bot.health")),
            register_commands=_bool(os.getenv("REGISTER_COMMANDS"), False),
        )


# Lazy singleton for simple imports
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
