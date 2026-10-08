"""Each migration, on a synthetic database of the version before (ADR-0013). Tests never touch the
owner's database."""

import sqlite3
from contextlib import closing
from pathlib import Path

from jiffin.core.context import Context
from jiffin.core.model import EngineBuild
from jiffin.core.records import Answer, ContextAnswer, Here
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

EVENING = (
    '{"days": {"weekdays": [0, 1, 2, 3, 4, 5, 6]}, "hours": {"slot": ["18:00", "23:00"]}, '
    '"period": null, "frequency": null}'
)
AT_THREE = (
    '{"days": {"date": "2026-09-21"}, "hours": {"moment": "15:00"}, "period": null, '
    '"frequency": null}'
)
VERSION_0_2 = f"""
INSERT INTO reminder (id, created_at, completed_at, snoozed_until) VALUES
    (1, {T0}, NULL, {T1 + 903_000}),
    (2, {T0}, NULL, NULL),
    (3, {T0}, {T1 + 700_000}, NULL);
INSERT INTO engine_build VALUES (1, 1, '0.2.0', 'b11081', '79de5cb8', 1, 2);
INSERT INTO revision (id, reminder, number, condition, action, remainder, statement,
    statement_build, schedule, written_at, perennial, created_at) VALUES
    (10, 1, 1, 'quando apro Figma', 'esportare le icone', 'quando apro Figma',
        'The user opens Figma.', 1, NULL, {T0}, 0, {T0}),
    (20, 2, 1, 'se sono sul sito della banca la sera', 'pagare il bollo',
        'se sono sul sito della banca', 'The user banks.', 1, '{EVENING}', {T0}, 1, {T0}),
    (30, 3, 1, 'alle 15', 'chiamare Mario', '', NULL, NULL, '{AT_THREE}', {T0}, 0, {T0});
INSERT INTO context (id, app, title, address) VALUES
    (1, 'figma.exe', 'Icone - Figma', NULL),
    (2, 'vivaldi.exe', 'Banca Rossi', 'bancarossi.it'),
    (3, 'olk.exe', 'Posta in arrivo - Outlook', NULL);
INSERT INTO evaluation (id, at, context, context_since, outcome, threshold, engine_build,
    context_until, return_pause) VALUES
    (1, {T1}, 1, {T1 - 20_000}, 'ok', 0.97, 1, {T1 + 60_000}, 120000),
    (2, {T1 + 600_000}, 2, {T1 + 580_000}, 'ok', 0.97, 1, NULL, 120000),
    (3, {T1 + 900_000}, 3, {T1 + 880_000}, 'ok', 0.97, 1, NULL, 120000);
INSERT INTO candidate (evaluation, revision, d, from_cache, outcome) VALUES
    (1, 10, 2.5, 0, 'alert'),
    (1, 20, 1.9, 0, 'outside_time'),
    (2, 20, 2.0, 0, 'alert'),
    (2, 10, -2.0, 1, 'below_threshold'),
    (3, 10, 2.6, 0, 'alert'),
    (3, 20, 2.1, 1, 'same_occasion');
INSERT INTO alert (id, revision, evaluation, context, d, created_at, due_at, shown_at,
    vanished_at, seen_at, answer, snooze, answered_at) VALUES
    (1, 10, NULL, 2, 1.5, {T0}, {T0}, {T0}, NULL, NULL, 'utile', NULL, {T0 + 5_000}),
    (2, 20, NULL, 1, 2.2, {T0}, {T0}, {T0}, NULL, NULL, 'non_qui', NULL, {T0 + 1_000}),
    (3, 10, NULL, 3, 1.0, {T0 + 2_000}, {T0 + 2_000}, {T0 + 2_000}, NULL, NULL, 'non_qui',
        NULL, {T0 + 6_000}),
    (4, 10, 1, 1, 2.5, {T1}, {T1 - 20_000}, {T1}, NULL, NULL, 'rimanda', 'quarter_hour',
        {T1 + 3_000}),
    (5, 20, 2, 2, 2.0, {T1 + 600_000}, {T1 + 580_000}, {T1 + 600_000}, NULL, NULL, 'fatto',
        NULL, {T1 + 601_000}),
    (6, 30, NULL, 2, NULL, {T1 + 650_000}, {T1 + 650_000}, {T1 + 650_000}, {T1 + 660_000},
        NULL, NULL, NULL, NULL),
    (7, 30, NULL, 1, NULL, {T1 + 700_000}, {T1 + 700_000}, {T1 + 700_000}, NULL, NULL,
        'chiuso', NULL, {T1 + 702_000}),
    (8, 10, 3, 3, 2.6, {T1 + 900_000}, {T1 + 880_000}, {T1 + 900_000}, NULL, NULL, 'non_qui',
        NULL, {T1 + 905_000});
INSERT INTO silence (reminder, context) VALUES (1, 3), (2, 1);
INSERT INTO judgement (context, revision, engine_build, d, last_used) VALUES (1, 10, 1, 2.5, {T1});
INSERT INTO setting (key, value) VALUES ('material', '"B"');
"""
UNCHANGED_IN_0_3 = ("reminder", "engine_build", "context", "evaluation", "judgement", "setting")
"""The tables migration 0003 leaves as they are."""
ALERT_0_2 = """id, revision, evaluation, context, d, created_at, due_at, shown_at, vanished_at,
    seen_at, snooze, answered_at"""
"""The columns of `alert` migration 0003 leaves as they are."""


def version(path: Path, number: int, rows: str = "") -> None:
    """The database at `path` brought to version `number`, then `rows` written into it."""
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        migrate(db, path, migrations()[:number])
        if rows:
            db.executescript(f"BEGIN; {rows} COMMIT;")


def rows(path: Path, sql: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as db:
        return db.execute(sql).fetchall()


def test_version_0_1_migrates_to_0_2_keeping_every_row(tmp_path: Path) -> None:
    path = tmp_path / "jiffin.db"
    version(path, 1, VERSION_0_1)
    version(path, 2)
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


def test_a_database_migrated_to_0_2_takes_what_0_2_writes(tmp_path: Path) -> None:
    path = tmp_path / "jiffin.db"
    version(path, 1, VERSION_0_1)
    version(path, 2)
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


def test_a_database_of_0_1_loads_and_logs(tmp_path: Path) -> None:
    path = tmp_path / "jiffin.db"
    version(path, 1, VERSION_0_1)
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
    # Its silence has no alert answered Not here: it is as old as its reminder.
    bank_site = Context("vivaldi.exe", "Banca Rossi", "bancarossi.it")
    assert (
        snapshot.answers == log.answers == (ContextAnswer(1, bank_site, Here.NO, None, None, T0),)
    )
    assert rows(path, "SELECT id, answer FROM alert ORDER BY id") == [(1, None), (2, "useful")]


def test_version_0_2_migrates_to_0_3_keeping_every_row(tmp_path: Path) -> None:
    path = tmp_path / "jiffin.db"
    version(path, 2, VERSION_0_2)
    before = {
        table: rows(path, f"SELECT * FROM {table} ORDER BY 1, 2") for table in UNCHANGED_IN_0_3
    }
    candidates = rows(path, "SELECT * FROM candidate ORDER BY evaluation, revision")
    alerts = rows(path, f"SELECT {ALERT_0_2} FROM alert ORDER BY id")
    revisions = rows(path, "SELECT * FROM revision ORDER BY id")
    Store.open(path).close()
    assert rows(path, "PRAGMA user_version") == [(3,)]
    assert not list(tmp_path.glob("*backup*"))
    for table, kept in before.items():
        assert rows(path, f"SELECT * FROM {table} ORDER BY 1, 2") == kept, table
    assert rows(path, "SELECT * FROM candidate ORDER BY evaluation, revision") == candidates
    # A revision gains its situations, none before 0.3.
    assert rows(path, "SELECT * FROM revision ORDER BY id") == [(*r, "[]") for r in revisions]
    # The answers in English, and no alert asked for.
    assert rows(path, f"SELECT {ALERT_0_2} FROM alert ORDER BY id") == alerts
    assert rows(path, "SELECT id, answer, requested FROM alert ORDER BY id") == [
        (1, "useful", 0),
        (2, "not_here", 0),
        (3, "not_here", 0),
        (4, "snooze", 0),
        (5, "done", 0),
        (6, None, 0),
        (7, "closed", 0),
        (8, "not_here", 0),
    ]
    # Each silence a Not here, with the d, the build and the time of the last alert answered Not
    # here in its place: no build for an alert whose evaluation expired.
    assert rows(path, "SELECT * FROM context_answer ORDER BY id") == [
        (1, 2, 1, "not_here", 2.2, None, T0 + 1_000),
        (2, 1, 3, "not_here", 2.6, 1, T1 + 905_000),
    ]
    tables = {row[0] for row in rows(path, "SELECT name FROM sqlite_schema WHERE type = 'table'")}
    assert "silence" not in tables
    assert rows(path, "SELECT count(*) FROM situation") == [(0,)]
    assert rows(path, "SELECT count(*) FROM engine_sleep") == [(0,)]
    indexes = {row[0] for row in rows(path, "SELECT name FROM sqlite_schema WHERE type = 'index'")}
    assert {
        "candidate_revision",
        "alert_revision",
        "alert_evaluation",
        "alert_context",
        "alert_created_at",
        "context_answer_place",
        "context_answer_context",
        "context_answer_engine_build",
        "situation_until",
    } <= indexes
    assert "silence_context" not in indexes


def test_a_database_of_0_2_loads_and_logs_its_answers_in_english(tmp_path: Path) -> None:
    path = tmp_path / "jiffin.db"
    version(path, 2, VERSION_0_2)
    store = Store.open(path)
    try:
        snapshot, log = store.load(), store.log()
    finally:
        store.close()
    build = EngineBuild(1, "0.2.0", "b11081", "79de5cb8", 1, 2)
    mail = Context("olk.exe", "Posta in arrivo - Outlook", None)
    figma = Context("figma.exe", "Icone - Figma", None)
    assert snapshot.answers == (
        ContextAnswer(2, figma, Here.NO, 2.2, None, T0 + 1_000),
        ContextAnswer(1, mail, Here.NO, 2.6, build, T1 + 905_000),
    )
    assert log.answers == snapshot.answers
    # The alerts answered Not here do not count in their unit, in English as in Italian.
    assert snapshot.last_alerts == ((1, 4, T1), (2, 5, T1 + 600_000), (3, 7, T1 + 700_000))
    assert all(reminder.revision.situations == () for reminder in snapshot.reminders)
    assert [(alert.id, alert.answer) for alert in log.alerts] == [
        (4, Answer.SNOOZE),
        (5, Answer.DONE),
        (6, None),
        (7, Answer.CLOSED),
        (8, Answer.NOT_HERE),
    ]
    assert not any(alert.requested for alert in log.alerts)
