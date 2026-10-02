"""SQLite online backup; safe while the bot is writing to its WAL."""

import argparse
import os
import sqlite3
from pathlib import Path


def backup(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("Backup destination must differ from the database")
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects existing backups; permissions protect profiles.
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src:
            with sqlite3.connect(destination) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Backup integrity check failed")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--source", type=Path, default=Path(os.getenv("DATABASE_PATH", "data/akinator.db"))
    )
    args = parser.parse_args()
    backup(args.source, args.destination)


if __name__ == "__main__":
    main()
