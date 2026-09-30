import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from jiffin.core.context import Context
from jiffin.core.model import EngineBuild
from jiffin.core.records import (
    Alert,
    Answer,
    CacheEntry,
    Candidate,
    Evaluation,
    LastIds,
    Outcome,
    Reminder,
    ReminderDeleted,
    Revision,
    Silence,
    SilencesCleared,
    Snapshot,
)
from jiffin.store.store import RETENTION_MS, Store

NOW = 1_790_000_000_000
DAY = 24 * 60 * 60 * 1000
BUILD = EngineBuild(1, "0.1.0", "b11081", "79de5cb8", judge_prompt=1, rewrite_prompt=2)
FIGMA = Context("figma.exe", "Icone - Figma", None)
BANK = Context("vivaldi.exe", "Banca Rossi", "bancarossi.it")


def reminder(reminder_id: int, condition: str = "quando apro Figma") -> Reminder:
    revision = Revision(
        reminder_id * 10, reminder_id, 1, condition, "esportare le icone", "The user.", BUILD
    )
    return Reminder(reminder_id, NOW, revision)


def evaluation(number: int, at: int, context: Context, *judged: Reminder) -> Evaluation:
    candidates = tuple(Candidate(r.revision.id, 2.5, False, Outcome.ALERT) for r in judged)
    return Evaluation(number, at, context, at - 20_000, 0.97, BUILD, candidates)


def alert(number: int, of: Reminder, evaluation: Evaluation) -> Alert:
    return Alert(number, of.id, of.revision, evaluation.id, evaluation.context, 2.5, evaluation.at)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "jiffin.db"


@pytest.fixture
def store(path: Path) -> Iterator[Store]:
    store = Store.open(path)
    yield store
    store.close()


def count(path: Path, table: str, where: str = "1") -> int:
    """Rows in a table, read through a second connection."""
    with closing(sqlite3.connect(path)) as db:
        return int(db.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0])


def test_what_core_saved_comes_back(store: Store) -> None:
    figma = reminder(1)
    snoozed = replace(reminder(2, "se sono sul sito della banca"), snoozed_until=NOW + DAY)
    judged = evaluation(1, NOW, FIGMA, figma, snoozed)
    vanished = replace(alert(1, figma, judged), shown_at=NOW, vanished_at=NOW + 10_000)
    entry = CacheEntry(FIGMA, figma.revision.id, BUILD, 2.5, NOW)
    store.save(
        [figma, snoozed, judged, vanished, entry, Silence(snoozed.id, BANK), Silence(2, FIGMA)]
    )
    assert store.load() == Snapshot(
        reminders=(figma, snoozed),
        silences=(Silence(2, FIGMA), Silence(2, BANK)),
        cache=(entry,),
        last_alerts=((figma.id, NOW),),
        unseen=(vanished,),
        last_ids=LastIds(reminder=2, revision=20, evaluation=1, alert=1),
    )


def test_a_reminder_comes_back_with_its_current_revision_and_cache(store: Store) -> None:
    first = reminder(1)
    second = replace(first, revision=replace(first.revision, id=11, number=2, statement=None))
    second = replace(second, revision=replace(second.revision, statement_build=None))
    store.save([first, CacheEntry(FIGMA, first.revision.id, BUILD, 2.5, NOW), second])
    snapshot = store.load()
    assert snapshot.reminders == (second,)
    assert snapshot.cache == ()


def test_only_alerts_shown_and_unanswered_of_active_reminders_are_unseen(store: Store) -> None:
    active, done = reminder(1), replace(reminder(2), completed_at=NOW)
    judged = evaluation(1, NOW, FIGMA, active, done)
    shown = replace(alert(1, active, judged), shown_at=NOW)
    later = replace(alert(4, active, judged), shown_at=NOW, vanished_at=NOW + 5)
    store.save(
        [
            active,
            done,
            judged,
            shown,
            later,
            alert(2, active, judged),
            replace(alert(3, active, judged), shown_at=NOW, answer=Answer.USEFUL, answered_at=NOW),
            replace(alert(5, done, judged), shown_at=NOW),
        ]
    )
    assert [a.id for a in store.load().unseen] == [4, 1]


def test_silences_can_be_cleared(store: Store) -> None:
    store.save([reminder(1), Silence(1, FIGMA), Silence(1, BANK), SilencesCleared(1)])
    assert store.load().silences == ()


def test_retention_keeps_30_days(store: Store, path: Path) -> None:
    kept, answered = reminder(1), reminder(2)
    old = evaluation(1, NOW - RETENTION_MS - 1, FIGMA, kept, answered)
    recent = evaluation(2, NOW - RETENTION_MS, BANK, kept)
    store.save(
        [
            kept,
            answered,
            old,
            recent,
            replace(alert(1, kept, old), created_at=old.at),
            replace(alert(2, answered, old), answer=Answer.DONE, answered_at=old.at),
            CacheEntry(FIGMA, kept.revision.id, BUILD, 2.5, NOW - RETENTION_MS - 1),
            CacheEntry(BANK, kept.revision.id, BUILD, 2.5, NOW - RETENTION_MS),
        ]
    )
    store.cleanup(NOW)
    assert count(path, "evaluation") == 1
    assert count(path, "candidate") == 1
    assert count(path, "alert") == 1
    assert count(path, "alert", "evaluation IS NULL AND answer = 'fatto'") == 1
    assert count(path, "judgement") == 1
    assert count(path, "context") == 2  # the answered alert still uses FIGMA
    assert count(path, "engine_build") == 1


def test_contexts_nothing_uses_are_deleted(store: Store, path: Path) -> None:
    kept = reminder(1)
    store.save([kept, evaluation(1, NOW - RETENTION_MS - 1, FIGMA, kept), Silence(1, BANK)])
    store.cleanup(NOW)
    assert count(path, "context") == 1


def test_deleting_a_reminder_leaves_nothing_about_it(store: Store, path: Path) -> None:
    gone, other = reminder(1), reminder(2, "se sono sul sito della banca")
    alone = evaluation(1, NOW, FIGMA, gone)
    shared = evaluation(2, NOW, BANK, gone, other)
    store.save(
        [
            gone,
            other,
            alone,
            shared,
            alert(1, gone, alone),
            alert(2, other, shared),
            CacheEntry(FIGMA, gone.revision.id, BUILD, 2.5, NOW),
            Silence(gone.id, FIGMA),
        ]
    )
    store.save([ReminderDeleted(gone.id)])
    assert count(path, "reminder") == count(path, "revision") == 1
    for table in ("candidate", "alert", "judgement"):
        assert count(path, table, f"revision = {gone.revision.id}") == 0
    assert count(path, "silence") == 0
    assert count(path, "evaluation") == 1
    assert count(path, "context", "app = 'figma'") == 0


def test_a_save_is_all_or_nothing(store: Store) -> None:
    lost = reminder(1)
    orphan = alert(1, reminder(9), evaluation(1, NOW, FIGMA))
    with pytest.raises(sqlite3.IntegrityError):
        store.save([lost, orphan])
    assert store.load().reminders == ()


def test_settings_keep_json(store: Store) -> None:
    assert store.setting("material") is None
    store.set_setting("material", {"alert": "B", "tray": "A"})
    assert store.setting("material") == {"alert": "B", "tray": "A"}


def test_logs_hold_ids_and_numbers_only(store: Store, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="jiffin.store")
    secret = reminder(1, "quando lavoro al progetto Rossi")
    store.save([secret, evaluation(1, NOW - RETENTION_MS - 1, BANK, secret)])
    store.cleanup(NOW)
    store.save([ReminderDeleted(secret.id)])
    assert caplog.messages
    for text in ("Rossi", "Banca", "bancarossi", "Figma", "quando"):
        assert text not in caplog.text


def test_the_log_holds_every_evaluation_alert_and_revision(store: Store) -> None:
    figma, bank = reminder(1), reminder(2, "se sono sul sito della banca")
    revised = Revision(11, 1, 2, "quando disegno icone", "esportarle", "The user draws.", BUILD)
    edited = replace(figma, revision=revised)
    first = evaluation(1, NOW, FIGMA, figma, bank)
    failed = Evaluation(2, NOW + 60_000, BANK, NOW + 40_000, 0.97, None, (), failed=True)
    later = evaluation(3, NOW + 120_000, FIGMA, edited)
    answered = replace(
        alert(1, figma, first), shown_at=NOW, answer=Answer.USEFUL, answered_at=NOW + 5_000
    )
    store.save([figma, bank, first, failed, answered, edited, later, Silence(2, FIGMA)])
    log = store.log()
    assert log.reminders == (edited, bank)
    assert log.revisions == {10: figma.revision, 11: revised, 20: bank.revision}
    assert log.evaluations == (first, failed, later)
    assert log.alerts == (answered,)
    assert log.silences == (Silence(2, FIGMA),)


def test_the_log_leaves_out_alerts_whose_evaluation_expired(store: Store) -> None:
    figma = reminder(1)
    old = evaluation(1, NOW - RETENTION_MS - 1, FIGMA, figma)
    answered = replace(alert(1, figma, old), answer=Answer.DONE, answered_at=old.at)
    store.save([figma, old, answered])
    store.cleanup(NOW)
    assert store.log().alerts == ()
