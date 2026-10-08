import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from jiffin.store.database import open_database
from jiffin.store.migrate import StoreError, check, migrate, migrations

TABLES = {
    "reminder",
    "revision",
    "context",
    "engine_build",
    "evaluation",
    "candidate",
    "alert",
    "context_answer",
    "judgement",
    "setting",
    "situation",
    "engine_sleep",
}


def test_an_empty_file_becomes_the_latest_schema(tmp_path: Path) -> None:
    with closing(open_database(tmp_path / "jiffin.db")) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
        tables = {
            row[0]: row[1]
            for row in db.execute(
                "SELECT name, strict FROM pragma_table_list WHERE schema = 'main'"
            )
            if not row[0].startswith("sqlite_")
        }
        assert tables == dict.fromkeys(TABLES, 1)


def test_the_connection_is_opened_as_adr_0013_says(tmp_path: Path) -> None:
    with closing(open_database(tmp_path / "jiffin.db")) as db:
        pragmas = [
            db.execute(f"PRAGMA {name}").fetchone()[0]
            for name in ("journal_mode", "synchronous", "foreign_keys", "secure_delete")
        ]
        assert pragmas == ["wal", 1, 1, 1]
        assert db.autocommit is False


def test_opening_again_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "jiffin.db"
    open_database(path).close()
    with closing(open_database(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
    assert not list(tmp_path.glob("*backup*"))


def test_a_database_from_a_newer_app_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "jiffin.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute(f"PRAGMA user_version = {len(migrations()) + 1}")
    with pytest.raises(StoreError, match="newer|knows"):
        open_database(path)


def test_a_failed_migration_restores_the_database(tmp_path: Path) -> None:
    path = tmp_path / "jiffin.db"
    first = ["CREATE TABLE note (id INTEGER PRIMARY KEY, text TEXT NOT NULL) STRICT;"]
    broken = [
        *first,
        "INSERT INTO note (id, text) VALUES (2, 'b'); INSERT INTO missing VALUES (1);",
    ]
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        migrate(db, path, first)
        db.execute("INSERT INTO note (id, text) VALUES (1, 'a')")
        with pytest.raises(sqlite3.OperationalError):
            migrate(db, path, broken)
        assert db.execute("SELECT id FROM note").fetchall() == [(1,)]
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
    assert not (tmp_path / "jiffin.backup.db").exists()


def test_a_migration_that_passes_deletes_the_copy(tmp_path: Path) -> None:
    path = tmp_path / "jiffin.db"
    steps = [
        "CREATE TABLE note (id INTEGER PRIMARY KEY) STRICT;",
        "ALTER TABLE note ADD COLUMN text TEXT;",
    ]
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        migrate(db, path, steps[:1])
        migrate(db, path, steps)
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    assert not (tmp_path / "jiffin.backup.db").exists()


def test_the_checks_find_a_broken_foreign_key(tmp_path: Path) -> None:
    with closing(sqlite3.connect(tmp_path / "broken.db", autocommit=True)) as db:
        db.executescript(
            """CREATE TABLE parent (id INTEGER PRIMARY KEY);
            CREATE TABLE child (parent INTEGER REFERENCES parent (id));
            INSERT INTO child VALUES (7);"""
        )
        with pytest.raises(StoreError, match="foreign key"):
            check(db)
