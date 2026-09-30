"""Numbered SQL migrations, applied in order with `PRAGMA user_version` (ADR-0013)."""

import logging
import sqlite3
from contextlib import closing
from importlib import resources
from pathlib import Path

log = logging.getLogger(__name__)


class StoreError(Exception):
    """The database cannot be used as it is."""


def migrations() -> list[str]:
    """The SQL of every migration, the first one first: `migrations/0001_init.sql`, …"""
    files = sorted(
        (entry.name, entry)
        for entry in (resources.files("jiffin.store") / "migrations").iterdir()
        if entry.name.endswith(".sql")
    )
    numbers = [int(name[:4]) for name, _ in files]
    if numbers != list(range(1, len(files) + 1)):
        raise StoreError(f"migrations must be numbered from 1 without gaps, not {numbers}")
    return [entry.read_text(encoding="utf-8") for _, entry in files]


def migrate(connection: sqlite3.Connection, path: Path, steps: list[str] | None = None) -> None:
    """Bring the database to the latest version; `connection` must be in autocommit mode.

    An existing database is copied first. If a migration or the checks after it fail, the
    copy comes back and the error goes on; if they pass, the copy is deleted, since it would
    keep data deleted later.
    """
    steps = migrations() if steps is None else steps
    version: int = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > len(steps):
        raise StoreError(f"the database is at version {version}, this app knows {len(steps)}")
    if version == len(steps):
        return
    backup = path.with_name(f"{path.stem}.backup{path.suffix}") if version else None
    if backup is not None:
        _copy(connection, backup)
    try:
        for number, sql in enumerate(steps[version:], start=version + 1):
            _apply(connection, number, sql)
        check(connection)
    except Exception:
        if backup is not None:
            _restore(backup, connection)
            log.error("migration from version %d failed; the database was restored", version)
        raise
    if backup is not None:
        backup.unlink()
    log.info("database migrated from version %d to %d", version, len(steps))


def check(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise StoreError("the integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise StoreError("the foreign key check failed")


def _apply(connection: sqlite3.Connection, number: int, sql: str) -> None:
    """One migration and its version, in one transaction."""
    try:
        connection.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
    except sqlite3.Error:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def _copy(connection: sqlite3.Connection, backup: Path) -> None:
    with closing(sqlite3.connect(backup)) as target:
        connection.backup(target)


def _restore(backup: Path, connection: sqlite3.Connection) -> None:
    with closing(sqlite3.connect(backup)) as source:
        source.backup(connection)
    backup.unlink()
