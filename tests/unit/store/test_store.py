import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import date, time
from pathlib import Path

import pytest

from jiffin.core.context import Context
from jiffin.core.model import EngineBuild
from jiffin.core.records import (
    Alert,
    Answer,
    CacheEntry,
    Candidate,
    ContextAnswer,
    Evaluation,
    Here,
    LastIds,
    Left,
    Outcome,
    Reminder,
    ReminderDeleted,
    Revision,
    Silence,
    Snapshot,
    Snooze,
)
from jiffin.core.schedule import Moment, OnDate, Period, Schedule, Slot, Weekdays
from jiffin.store.store import RETENTION_MS, Store

NOW = 1_790_000_000_000
DAY = 24 * 60 * 60 * 1000
BUILD = EngineBuild(1, "0.1.0", "b11081", "79de5cb8", judge_prompt=1, rewrite_prompt=2)
FIGMA = Context("figma.exe", "Icone - Figma", None)
BANK = Context("vivaldi.exe", "Banca Rossi", "bancarossi.it")


def reminder(reminder_id: int, condition: str = "quando apro Figma") -> Reminder:
    revision = Revision(
        reminder_id * 10,
        reminder_id,
        1,
        condition,
        "esportare le icone",
        condition,
        "The user.",
        BUILD,
        written_at=NOW,
        created_at=NOW,
    )
    return Reminder(reminder_id, NOW, revision)


def evaluation(number: int, at: int, context: Context, *judged: Reminder) -> Evaluation:
    candidates = tuple(Candidate(r.revision.id, 2.5, False, Outcome.ALERT) for r in judged)
    return Evaluation(
        number, at, context, at - 20_000, 0.97, BUILD, candidates, return_pause=120_000
    )


def alert(number: int, of: Reminder, evaluation: Evaluation) -> Alert:
    context, since = evaluation.context, evaluation.context_since
    return Alert(number, of.id, of.revision, evaluation.id, context, 2.5, evaluation.at, since)


def on_time(number: int, of: Reminder, at: int, context: Context = FIGMA) -> Alert:
    """An alert of a reminder with only a time: no evaluation, no d."""
    return Alert(number, of.id, of.revision, None, context, None, at, at - 1_000)


def said(reminder_id: int, context: Context, here: Here = Here.NO) -> ContextAnswer:
    """An answer in a place, where the cache knew no d."""
    return ContextAnswer(reminder_id, context, here, None, None, NOW)


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
    store.save([figma, snoozed, judged, vanished, entry, said(snoozed.id, BANK), said(2, FIGMA)])
    assert store.load() == Snapshot(
        reminders=(figma, snoozed),
        silences=(Silence(2, FIGMA), Silence(2, BANK)),
        cache=(entry,),
        last_alerts=((figma.id, vanished.id, NOW),),
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


def test_the_unseen_are_the_last_alerts_of_active_reminders_shown_and_unanswered(
    store: Store,
) -> None:
    figma, bank, call = reminder(1), reminder(2, "se sono sul sito della banca"), reminder(3, "")
    done = replace(reminder(4), completed_at=NOW)
    judged = evaluation(1, NOW, FIGMA, figma, bank, done)
    store.save(
        [
            figma,
            bank,
            call,
            done,
            judged,
            replace(alert(1, figma, judged), shown_at=NOW, vanished_at=NOW + 10_000),
            replace(alert(2, figma, judged), shown_at=NOW + 200_000),
            replace(alert(3, bank, judged), shown_at=NOW, vanished_at=NOW + 10_000),
            replace(alert(4, bank, judged), shown_at=NOW, answer=Answer.DONE, answered_at=NOW),
            replace(on_time(5, call, NOW + 300_000), shown_at=NOW + 300_000),
            alert(6, figma, judged),  # still waiting for a place on screen
            replace(alert(7, done, judged), shown_at=NOW),
        ]
    )
    assert [a.id for a in store.load().unseen] == [5]
    store.save([replace(alert(6, figma, judged), shown_at=NOW + 400_000)])
    assert [a.id for a in store.load().unseen] == [6, 5]


def test_the_alert_that_counts_is_the_last_not_answered_not_here(store: Store) -> None:
    figma = reminder(1)
    judged = evaluation(1, NOW, FIGMA, figma)
    counted = replace(alert(1, figma, judged), shown_at=NOW, answer=Answer.DONE)
    taken_back = replace(alert(2, figma, judged), created_at=NOW + 5, answer=Answer.NOT_HERE)
    store.save([figma, judged, counted, taken_back])
    assert store.load().last_alerts == ((figma.id, 1, NOW),)


def test_a_revision_keeps_its_time_and_ogni_volta(store: Store) -> None:
    figma = reminder(1, "quando apro Figma la sera fino a domenica")
    timed = replace(
        figma.revision,
        remainder="quando apro Figma",
        schedule=Schedule(
            Weekdays(frozenset({0, 4})),
            Slot(time(18), time(23)),
            Period(date(2026, 10, 2), date(2026, 10, 4)),
        ),
        perennial=True,
    )
    call = reminder(2, "domani alle 15")
    only_time = replace(
        call.revision,
        remainder="",
        statement=None,
        statement_build=None,
        schedule=Schedule(OnDate(date(2026, 10, 3)), Moment(time(15))),
    )
    saved = [replace(figma, revision=timed), replace(call, revision=only_time)]
    store.save(saved)
    assert store.load().reminders == tuple(saved)
    assert list(store.log().revisions.values()) == [timed, only_time]


def test_a_context_that_left_ends_its_stretch_on_its_evaluations(store: Store, path: Path) -> None:
    figma = reminder(1)
    first = evaluation(1, NOW, FIGMA, figma)
    again = replace(evaluation(2, NOW + 900_000, FIGMA, figma), context_since=first.context_since)
    bank = evaluation(3, NOW + 2_000_000, BANK, figma)
    store.save([figma, first, again, bank, Left(FIGMA, first.context_since, NOW + 1_000_000)])
    assert count(path, "evaluation", f"context_until = {NOW + 1_000_000}") == 2
    assert count(path, "evaluation", "context_until IS NULL") == 1
    assert store.log().left == (Left(FIGMA, first.context_since, NOW + 1_000_000),)


def test_alerts_without_a_judgement_and_the_kind_of_a_rimanda_are_kept(store: Store) -> None:
    figma, call = reminder(1), reminder(2, "alle 15")
    judged = evaluation(1, NOW, FIGMA, figma)
    later = replace(
        alert(1, figma, judged),
        shown_at=NOW,
        answer=Answer.SNOOZE,
        answered_at=NOW + 3_000,
        snooze=Snooze.NEXT_TIME,
    )
    closed = replace(on_time(2, call, NOW + 60_000), shown_at=NOW + 60_000, answer=Answer.CLOSED)
    store.save([figma, call, judged, later, closed])
    assert store.log().alerts == (later, closed)


def test_remind_here_and_a_withdrawal_take_a_silence_away(store: Store) -> None:
    store.save([reminder(1), said(1, FIGMA), said(1, BANK)])
    store.save([said(1, FIGMA, Here.YES), said(1, BANK, Here.WITHDRAWN)])
    assert store.load().silences == ()
    store.save([said(1, BANK)])
    assert store.load().silences == (Silence(1, BANK),)


def test_an_answer_that_takes_no_silence_away_adds_no_context(store: Store, path: Path) -> None:
    store.save([reminder(1), said(1, FIGMA, Here.YES), said(1, BANK, Here.WITHDRAWN)])
    assert count(path, "context") == 0


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


def test_an_alert_answered_after_the_cleanup_took_it_comes_back_without_its_evaluation(
    store: Store, path: Path
) -> None:
    # A running app keeps an unseen alert in memory while the daily cleanup deletes its row.
    figma = reminder(1)
    expired = evaluation(1, NOW - RETENTION_MS - 1, FIGMA, figma)
    unseen = replace(alert(1, figma, expired), shown_at=expired.at, vanished_at=expired.at)
    store.save([figma, expired, unseen])
    store.cleanup(NOW)
    assert count(path, "alert") == 0
    store.save([replace(figma, completed_at=NOW), replace(unseen, answer=Answer.DONE)])
    assert count(path, "alert", "answer = 'fatto' AND evaluation IS NULL") == 1
    assert count(path, "reminder", "completed_at IS NOT NULL") == 1


def test_contexts_nothing_uses_are_deleted(store: Store, path: Path) -> None:
    kept = reminder(1)
    store.save([kept, evaluation(1, NOW - RETENTION_MS - 1, FIGMA, kept), said(1, BANK)])
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
            said(gone.id, FIGMA),
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


def test_closing_empties_the_write_ahead_log_while_the_harness_reads(path: Path) -> None:
    store = Store.open(path)
    store.save([reminder(1)])
    with closing(sqlite3.connect(path)) as reader:
        assert reader.execute("SELECT count(*) FROM reminder").fetchall() == [(1,)]
        store.close()
        assert path.with_name(f"{path.name}-wal").stat().st_size == 0
        assert reader.execute("SELECT count(*) FROM reminder").fetchall() == [(1,)]


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
    revised = Revision(
        11, 1, 2, "quando disegno icone", "esportarle", "quando disegno icone", "The user draws."
    )
    revised = replace(revised, statement_build=BUILD)
    edited = replace(figma, revision=revised)
    first = evaluation(1, NOW, FIGMA, figma, bank)
    failed = Evaluation(
        2, NOW + 60_000, BANK, NOW + 40_000, 0.97, None, (), failed=True, return_pause=120_000
    )
    later = evaluation(3, NOW + 120_000, FIGMA, edited)
    answered = replace(
        alert(1, figma, first), shown_at=NOW, answer=Answer.USEFUL, answered_at=NOW + 5_000
    )
    store.save([figma, bank, first, failed, answered, edited, later, said(2, FIGMA)])
    log = store.log()
    assert log.reminders == (edited, bank)
    assert log.revisions == {10: figma.revision, 11: revised, 20: bank.revision}
    assert log.evaluations == (first, failed, later)
    assert log.alerts == (answered,)
    assert log.silences == (Silence(2, FIGMA),)
    assert log.left == ()


def test_the_log_leaves_out_alerts_whose_evaluation_expired(store: Store) -> None:
    figma = reminder(1)
    old = evaluation(1, NOW - RETENTION_MS - 1, FIGMA, figma)
    answered = replace(alert(1, figma, old), answer=Answer.DONE, answered_at=old.at)
    store.save([figma, old, answered])
    store.cleanup(NOW)
    assert store.log().alerts == ()
