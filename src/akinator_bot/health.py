"""Local runtime health probe, without credentials or network requests."""

import os
import sys
import time
from pathlib import Path


def healthy(path: Path, max_age: int = 90) -> bool:
    try:
        return 0 <= time.time() - path.stat().st_mtime < max_age
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(0 if healthy(Path(os.getenv("HEALTH_PATH", "/tmp/akinator-bot.health"))) else 1)
