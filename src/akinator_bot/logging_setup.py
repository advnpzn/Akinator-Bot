"""Bounded logs with redaction applied after traceback formatting."""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from akinator_bot.config import Settings

_TOKEN = re.compile(r"\d{5,15}:[A-Za-z0-9_-]{20,}")
_NAMED = re.compile(r"(?i)(bot_token|admin_secret|password|api_key)\s*[:=]\s*\S+")


class SecretFormatter(logging.Formatter):
    def __init__(self, *args, secrets: tuple[str, ...] = (), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        output = super().format(record)
        for secret in self.secrets:
            output = output.replace(secret, "[REDACTED]")
        return _NAMED.sub("[REDACTED]", _TOKEN.sub("[REDACTED]", output))


def setup_logging(settings: Settings) -> None:
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(settings.log_level)
    formatter = SecretFormatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        secrets=(settings.bot_token, settings.admin_secret or ""),
    )
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)
    if settings.log_file:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(settings.log_file, maxBytes=5_000_000, backupCount=2)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    for name in ("httpx", "httpcore", "telegram.ext"):
        logging.getLogger(name).setLevel(logging.WARNING)
