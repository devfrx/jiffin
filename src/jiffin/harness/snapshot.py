"""`snapshot` and `forget`: the copies of the app's log in the data folder (ADR-0013, ADR-0017).

A copy goes through SQLite's backup API, from a read-only connection, so it can be made while
the app runs. It holds titles, addresses and reminder texts, and it keeps what the user deletes
in the app afterwards: `forget` deletes the copies once the analysis is done.
"""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from jiffin.harness.errors import HarnessError
from jiffin.store.migrate import StoreError
from jiffin.store.store import Log, Store

PATTERN = "log-*.db"


def snapshot(database: Path, folder: Path, now: datetime) -> Path:
    if not database.is_file():
        raise HarnessError(f"there is no database at {database}: pass --database")
    copy = folder / f"log-{now:%Y%m%d-%H%M%S}.db"
    source = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    with closing(source), closing(sqlite3.connect(copy)) as target:
        source.backup(target)
        # One file, with no write-ahead log beside it, is one file to delete.
        target.execute("PRAGMA journal_mode=DELETE")
    return copy


def latest(folder: Path) -> Path:
    copies = sorted(folder.glob(PATTERN))
    if not copies:
        raise HarnessError(f"there is no copy of the log in {folder}: run snapshot first")
    return copies[-1]


def read(copy: Path) -> Log:
    """The whole log of a copy; a copy of an older app is migrated first, as the app would."""
    if not copy.is_file():
        raise HarnessError(f"there is no copy at {copy}")
    try:
        store = Store.open(copy)
    except (StoreError, sqlite3.Error) as error:
        raise HarnessError(f"{copy.name}: {error}") from None
    try:
        return store.log()
    finally:
        store.close()


def forget(folder: Path) -> list[Path]:
    """Delete every copy in the folder, with the files SQLite may leave beside it."""
    copies = sorted(folder.glob(PATTERN))
    for copy in copies:
        for suffix in ("", "-wal", "-shm", "-journal"):
            copy.with_name(copy.name + suffix).unlink(missing_ok=True)
    return copies
