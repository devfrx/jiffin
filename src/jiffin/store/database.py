"""The one connection to the database, opened in the order ADR-0013 requires."""

import sqlite3
from pathlib import Path

from jiffin.store.migrate import StoreError, migrate

PRAGMAS = ("synchronous=NORMAL", "foreign_keys=ON", "secure_delete=ON", "optimize=0x10002")


def open_database(path: Path) -> sqlite3.Connection:
    """Open, migrate, then switch to PEP 249 transactions.

    In that order: with transactions from the start, `foreign_keys` would stay off and the
    switch to WAL would fail.
    """
    connection = sqlite3.connect(path, autocommit=True, timeout=5)
    try:
        if connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
            raise StoreError("the database cannot use write-ahead logging")
        for pragma in PRAGMAS:
            connection.execute(f"PRAGMA {pragma}")
        migrate(connection, path)
    except BaseException:
        connection.close()
        raise
    connection.autocommit = False
    return connection
