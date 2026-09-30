import sqlite3


def test_sqlite_is_past_the_wal_reset_bug() -> None:
    # SQLite 3.7.0 to 3.51.2 can corrupt a WAL database (ADR-0013).
    assert sqlite3.sqlite_version_info >= (3, 51, 3)
