"""Each migration, on a synthetic database of the version before (ADR-0013). Tests never touch the
owner's database."""

import sqlite3
from contextlib import closing
from pathlib import Path

from jiffin.core.context import Context
from jiffin.store.migrate import migrate, migrations
from jiffin.store.store import Store

T0 = 1_790_000_000_000
T1 = T0 + 3_600_000

VERSION_0_1 = f"""
INSERT INTO reminder (id, created_at, completed_at, snoozed_until) VALUES
    (1, {T0}, NULL, NULL),
    (2, {T0 + 1}, {T1}, NULL);
INSERT INTO engine_build VALUES (1, 1, '0.1.0', 'b11081', '79de5cb8', 1, 2);
INSERT INTO revision (id, reminder, number, condition, action, statement, statement_build) VALUES
    (10, 1, 1, 'quando apro Figma', 'esportare le icone', 'The user opens Figma.', 1),
    (11, 1, 2, 'quando disegno icone', 'esportarle', 'The user draws icons.', 1),
    (20, 2, 1, 'se sono sul sito della banca', 'pagare il bollo', 'The user banks.', 1);
INSERT INTO context (id, app, title, address) VALUES
    (1, 'figma.exe', 'Icone - Figma', NULL),
    (2, 'vivaldi.exe', 'Banca Rossi', 'bancarossi.it');
INSERT INTO evaluation (id, at, context, context_since, outcome, threshold, engine_build) VALUES
    (1, {T1}, 1, {T1 - 20_000}, 'ok', 0.97, 1),
    (2, {T1 + 60_000}, 2, {T1 + 40_000}, 'error', 0.97, NULL);
INSERT INTO candidate (evaluation, revision, d, from_cache, outcome) VALUES
    (1, 11, 2.5, 0, 'held_back'),
    (1, 20, 0.1, 1, 'below_threshold');
INSERT INTO alert (id, revision, evaluation, context, d, created_at, shown_at, vanished_at,
    seen_at, answer, answered_at) VALUES
    (1, 11, 1, 1, 2.5, {T1}, {T1}, {T1 + 10_000}, NULL, NULL, NULL),
    (2, 20, NULL, 2, 1.5, {T0}, {T0}, NULL, NULL, 'utile', {T0 + 5_000});
INSERT INTO silence (reminder, context) VALUES (1, 2);
INSERT INTO judgement (context, revision, engine_build, d, last_used) VALUES (1, 11, 1, 2.5, {T1});
INSERT INTO setting (key, value) VALUES ('material', '"B"');
"""


def version_0_1(path: Path) -> None:
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        migrate(db, path, migrations()[:1])
        db.executescript(f"BEGIN; {VERSION_0_1} COMMIT;")


def rows(path: Path, sql: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as db:
        return db.execute(sql).fetchall()


def test_version_0_1_migrates_to_0_2_keeping_every_row(tmp_path: Path) -> None:
    path = tmp_path / "jiffin.db"
    version_0_1(path)
    Store.open(path).close()
    assert rows(path, "PRAGMA user_version") == [(2,)]
    assert not list(tmp_path.glob("*backup*"))
    # Reminders without time, whose remainder is the condition; the first revision was made with
    # its reminder, and when the others were made is not known.
    assert rows(
        path,
        """SELECT id, remainder = condition, schedule, written_at, perennial, created_at
        FROM revision ORDER BY id""",
    ) == [(10, 1, None, None, 0, T0), (11, 1, None, None, 0, None), (20, 1, None, None, 0, T0 + 1)]
    assert rows(path, "SELECT id, context_until, return_pause FROM evaluation ORDER BY id") == [
        (1, None, None),
        (2, None, None),
    ]
    assert rows(path, "SELECT evaluation, revision, outcome FROM candidate ORDER BY revision") == [
        (1, 11, "held_back"),
        (1, 20, "below_threshold"),
    ]
    # An alert was due when its context came; without its evaluation, when it was made.
    assert rows(
        path, "SELECT id, evaluation, d, due_at, answer, snooze FROM alert ORDER BY id"
    ) == [
        (1, 1, 2.5, T1 - 20_000, None, None),
        (2, None, 1.5, T0, "utile", None),
    ]
    assert rows(path, "SELECT count(*) FROM silence") == [(1,)]
    assert rows(path, "SELECT count(*) FROM judgement") == [(1,)]
    assert rows(path, "SELECT value FROM setting WHERE key = 'material'") == [('"B"',)]
    indexes = {row[0] for row in rows(path, "SELECT name FROM sqlite_schema WHERE type = 'index'")}
    assert {
        "candidate_revision",
        "alert_revision",
        "alert_evaluation",
        "alert_context",
        "alert_created_at",
    } <= indexes


def test_a_migrated_database_takes_what_0_2_writes(tmp_path: Path) -> None:
    path = tmp_path / "jiffin.db"
    version_0_1(path)
    Store.open(path).close()
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT INTO candidate VALUES (2, 10, 2.5, 0, 'same_occasion'), (2, 11, 3, 1, "
            "'outside_time')"
        )
        db.execute(
            f"""INSERT INTO alert (id, revision, evaluation, context, d, created_at, due_at,
                answer, snooze) VALUES (3, 10, NULL, 1, NULL, {T1}, {T1}, 'chiuso', 'next_time')"""
        )
    assert rows(path, "SELECT count(*) FROM candidate") == [(4,)]
    assert rows(path, "SELECT count(*) FROM alert WHERE d IS NULL") == [(1,)]


def test_a_migrated_database_loads_and_logs(tmp_path: Path) -> None:
    path = tmp_path / "jiffin.db"
    version_0_1(path)
    store = Store.open(path)
    try:
        snapshot, log = store.load(), store.log()
    finally:
        store.close()
    figma, bank = snapshot.reminders
    assert (figma.revision.id, figma.revision.remainder) == (11, "quando disegno icone")
    assert bank.completed_at == T1
    assert snapshot.last_alerts == ((1, 1, T1), (2, 2, T0))
    [unseen] = snapshot.unseen
    assert (unseen.id, unseen.due_at) == (1, T1 - 20_000)
    assert unseen.context == Context("figma.exe", "Icone - Figma", None)
    assert [alert.id for alert in log.alerts] == [1]  # the other one's evaluation expired
    assert [evaluation.return_pause for evaluation in log.evaluations] == [None, None]
    assert log.left == ()
