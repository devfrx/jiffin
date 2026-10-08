"""The records of `core`, saved in SQLite and loaded back (ADR-0013, ADR-0014).

Logs from here hold ids and numbers only: no titles, addresses or reminder texts.
"""

import json
import logging
import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, assert_never

from jiffin.core.context import Context
from jiffin.core.model import EngineBuild
from jiffin.core.records import (
    Alert,
    Answer,
    CacheEntry,
    Candidate,
    ContextAnswer,
    EngineSleep,
    Evaluation,
    Here,
    LastIds,
    Left,
    Outcome,
    Record,
    Reminder,
    ReminderDeleted,
    Revision,
    Snapshot,
    Snooze,
)
from jiffin.core.situations import SituationStretch
from jiffin.store import schedules, terms
from jiffin.store.database import open_database

log = logging.getLogger(__name__)

RETENTION_MS = 30 * 24 * 60 * 60 * 1000
"""Evaluations, unanswered alerts, unused cache entries, the stretches of the situations and the
engine's sleeps are kept for 30 days."""

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]

# The current revision of each reminder: the one with the highest number.
_CURRENT = (
    "revision.number = (SELECT max(number) FROM revision AS r WHERE r.reminder = revision.reminder)"
)
# The columns of a revision, in the order `Store._revision` reads them.
_REVISION = """revision.id, revision.reminder, revision.number, revision.condition, revision.action,
    revision.remainder, revision.statement, revision.statement_build, revision.schedule,
    revision.written_at, revision.perennial, revision.created_at, revision.situations"""
# The columns of an alert and its context, in the order `Store._alert` reads them.
_ALERT = """alert.id, alert.revision, alert.evaluation, context.app, context.title,
    context.address, alert.d, alert.created_at, alert.due_at, alert.shown_at, alert.vanished_at,
    alert.seen_at, alert.answer, alert.answered_at, alert.snooze, alert.requested"""
# The latest alert of the reminder of `revision`, among those `which` keeps.
_LAST_ALERT = """(SELECT max(a.id) FROM alert AS a JOIN revision AS r ON r.id = a.revision
    WHERE r.reminder = revision.reminder AND {which})"""
# The last answer of a reminder in a context: the one that counts there (ADR-0029).
_LAST_ANSWER = """context_answer.id = (SELECT max(a.id) FROM context_answer AS a
    WHERE a.reminder = context_answer.reminder AND a.context = context_answer.context)"""


@dataclass(frozen=True, slots=True)
class Log:
    """Everything the database holds about judging, for the harness (ADR-0017)."""

    reminders: tuple[Reminder, ...]
    """With their current revision."""
    revisions: dict[int, Revision]
    """Every revision by id, the old ones too."""
    evaluations: tuple[Evaluation, ...]
    """The oldest first, with their candidates."""
    alerts: tuple[Alert, ...]
    """The oldest first. An alert whose evaluation has expired is left out; one of a reminder
    with only a time, or asked for with Remind here, which have none, is not."""
    answers: tuple[ContextAnswer, ...]
    """Every answer per place and every withdrawal, the oldest first (ADR-0029)."""
    left: tuple[Left, ...]
    """When each evaluated context left the foreground, the earliest first: none for the one
    still in front, and none in version 0.1."""


class Store:
    """The database, used by the worker thread that owns `core` (ADR-0012)."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    @classmethod
    def open(cls, path: Path) -> "Store":
        return cls(open_database(path))

    def close(self) -> None:
        """A last checkpoint, then the connection closes: the write-ahead log is left empty even
        while the harness reads the file, and SQLite would not checkpoint then on its own."""
        try:
            self._checkpoint()
        finally:
            self._db.close()

    def save(self, records: Iterable[Record]) -> None:
        """Save what `core` changed and the engine's sleeps, all or nothing."""
        deleted = False
        with self._transaction():
            for record in records:
                match record:
                    case Reminder():
                        self._save_reminder(record)
                    case ReminderDeleted():
                        self._delete_reminder(record.reminder_id)
                        deleted = True
                    case ContextAnswer():
                        self._save_context_answer(record)
                    case CacheEntry():
                        self._save_cache_entry(record)
                    case Evaluation():
                        self._save_evaluation(record)
                    case Left():
                        self._save_left(record)
                    case SituationStretch():
                        self._save_stretch(record)
                    case Alert():
                        self._save_alert(record)
                    case EngineSleep():
                        self._save_sleep(record)
                    case _:
                        assert_never(record)
        if deleted:
            self._checkpoint()  # so that deleted content leaves the WAL too

    def load(self) -> Snapshot:
        """What `core` needs to go on where it stopped."""
        with self._transaction():
            builds = self._builds()
            reminders = tuple(
                Reminder(row[0], row[1], self._revision(row[4:], builds), row[2], row[3])
                for row in self._db.execute(
                    f"""SELECT reminder.id, reminder.created_at, completed_at, snoozed_until,
                        {_REVISION}
                    FROM reminder JOIN revision ON revision.reminder = reminder.id
                    WHERE {_CURRENT} ORDER BY reminder.id"""
                )
            )
            # The answer that counts in each place, unless it was withdrawn (ADR-0029).
            answers = self._answers(
                builds, f"{_LAST_ANSWER} AND here IS NOT '{Here.WITHDRAWN.value}'"
            )
            cache = tuple(
                CacheEntry(Context(*row[:3]), row[3], builds[row[4]], row[5], row[6])
                for row in self._db.execute(
                    f"""SELECT app, title, address, revision, engine_build, d, last_used
                    FROM judgement JOIN context ON context.id = judgement.context
                    WHERE revision IN (SELECT id FROM revision WHERE {_CURRENT})
                    ORDER BY revision, context.id, engine_build"""
                )
            )
            # The alert that counts in each reminder's unit: Not here takes it back (ADR-0021).
            counted = _LAST_ALERT.format(which=f"a.answer IS NOT '{Answer.NOT_HERE.value}'")
            last_alerts = tuple(
                (row[0], row[1], row[2])
                for row in self._db.execute(
                    f"""SELECT revision.reminder, alert.id, alert.created_at
                    FROM alert JOIN revision ON revision.id = alert.revision
                    WHERE alert.id = {counted} ORDER BY revision.reminder"""
                )
            )
            return Snapshot(
                reminders, answers, cache, last_alerts, self._unseen(builds), self._last_ids()
            )

    def log(self) -> Log:
        """The whole history the database keeps: the harness reads it from a copy."""
        with self._transaction():
            builds = self._builds()
            revisions = {
                row[0]: self._revision(row, builds)
                for row in self._db.execute(f"SELECT {_REVISION} FROM revision ORDER BY id")
            }
            reminders = tuple(
                Reminder(row[0], row[1], revisions[row[4]], row[2], row[3])
                for row in self._db.execute(
                    f"""SELECT reminder.id, reminder.created_at, completed_at, snoozed_until,
                        revision.id
                    FROM reminder JOIN revision ON revision.reminder = reminder.id
                    WHERE {_CURRENT} ORDER BY reminder.id"""
                )
            )
            candidates: dict[int, list[Candidate]] = {}
            for row in self._db.execute(
                """SELECT evaluation, revision, d, from_cache, outcome FROM candidate
                ORDER BY evaluation, revision"""
            ):
                candidates.setdefault(row[0], []).append(
                    Candidate(row[1], row[2], bool(row[3]), Outcome(row[4]))
                )
            evaluations = tuple(
                Evaluation(
                    row[0],
                    row[1],
                    Context(*row[2:5]),
                    row[5],
                    row[7],
                    None if row[8] is None else builds[row[8]],
                    tuple(candidates.get(row[0], ())),
                    failed=row[6] == "error",
                    return_pause=row[9],
                )
                for row in self._db.execute(
                    """SELECT evaluation.id, at, app, title, address, context_since, outcome,
                        threshold, engine_build, return_pause
                    FROM evaluation JOIN context ON context.id = evaluation.context
                    ORDER BY at, evaluation.id"""
                )
            )
            alerts = tuple(
                self._alert(row, revisions[row[1]])
                for row in self._db.execute(
                    f"""SELECT {_ALERT} FROM alert JOIN context ON context.id = alert.context
                    WHERE evaluation IS NOT NULL OR d IS NULL OR requested
                    ORDER BY created_at, alert.id"""
                )
            )
            left = tuple(
                Left(Context(*row[:3]), row[3], row[4])
                for row in self._db.execute(
                    """SELECT DISTINCT app, title, address, context_since, context_until
                    FROM evaluation JOIN context ON context.id = evaluation.context
                    WHERE context_until IS NOT NULL ORDER BY context_since, context_until"""
                )
            )
            answers = self._answers(builds, "1")
            return Log(reminders, revisions, evaluations, alerts, answers, left)

    def cleanup(self, now: int) -> None:
        """Delete what the retention rules of ADR-0014 no longer keep, at startup and daily."""
        cutoff = now - RETENTION_MS
        with self._transaction():
            evaluations = self._delete("DELETE FROM evaluation WHERE at < ?", cutoff)
            alerts = self._delete(
                "DELETE FROM alert WHERE answer IS NULL AND created_at < ?", cutoff
            )
            entries = self._delete("DELETE FROM judgement WHERE last_used < ?", cutoff)
            stretches = self._delete("DELETE FROM situation WHERE until < ?", cutoff)
            sleeps = self._delete("DELETE FROM engine_sleep WHERE slept_at < ?", cutoff)
            contexts = self._delete_orphan_contexts()
        self._checkpoint(optimize=True)
        log.info(
            "cleanup deleted %d evaluations, %d alerts, %d cache entries, %d situation stretches, "
            "%d engine sleeps and %d contexts",
            evaluations,
            alerts,
            entries,
            stretches,
            sleeps,
            contexts,
        )

    def setting(self, key: str) -> Json:
        """The value of a setting, or None when it has never been set."""
        with self._transaction():
            row = self._db.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
        return None if row is None else json.loads(row[0])

    def set_setting(self, key: str, value: Json) -> None:
        with self._transaction():
            self._db.execute(
                """INSERT INTO setting (key, value) VALUES (?, ?)
                ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
                (key, json.dumps(value)),
            )

    # Saving

    def _save_reminder(self, reminder: Reminder) -> None:
        self._db.execute(
            """INSERT INTO reminder (id, created_at, completed_at, snoozed_until)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE
            SET completed_at = excluded.completed_at, snoozed_until = excluded.snoozed_until""",
            (reminder.id, reminder.created_at, reminder.completed_at, reminder.snoozed_until),
        )
        revision = reminder.revision
        self._db.execute(
            """INSERT INTO revision (id, reminder, number, condition, action, remainder,
                statement, statement_build, schedule, written_at, perennial, created_at,
                situations)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE
            SET statement = excluded.statement, statement_build = excluded.statement_build""",
            (
                revision.id,
                revision.reminder_id,
                revision.number,
                revision.condition,
                revision.action,
                revision.remainder,
                revision.statement,
                self._build_id(revision.statement_build),
                None if revision.schedule is None else schedules.dumps(revision.schedule),
                revision.written_at,
                int(revision.perennial),
                revision.created_at,
                terms.dumps(revision.situations),
            ),
        )

    def _delete_reminder(self, reminder_id: int) -> None:
        """The reminder cascades; then the evaluations it leaves empty and unused contexts go."""
        judged = [
            row[0]
            for row in self._db.execute(
                """SELECT DISTINCT evaluation FROM candidate
                JOIN revision ON revision.id = candidate.revision WHERE revision.reminder = ?""",
                (reminder_id,),
            )
        ]
        self._db.execute("DELETE FROM reminder WHERE id = ?", (reminder_id,))
        self._db.executemany(
            """DELETE FROM evaluation WHERE id = ?
            AND NOT EXISTS (SELECT 1 FROM candidate WHERE candidate.evaluation = evaluation.id)""",
            [(evaluation,) for evaluation in judged],
        )
        self._delete_orphan_contexts()
        log.info("reminder %d deleted", reminder_id)

    def _save_context_answer(self, answer: ContextAnswer) -> None:
        """Every answer and every withdrawal is a row: the last of a place counts (ADR-0029)."""
        self._db.execute(
            """INSERT INTO context_answer (reminder, context, here, d, engine_build, at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                answer.reminder_id,
                self._context_id(answer.context),
                answer.here.value,
                answer.d,
                self._build_id(answer.build),
                answer.at,
            ),
        )

    def _save_cache_entry(self, entry: CacheEntry) -> None:
        self._db.execute(
            """INSERT INTO judgement (context, revision, engine_build, d, last_used)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (context, revision, engine_build) DO UPDATE
            SET d = excluded.d, last_used = excluded.last_used""",
            (
                self._context_id(entry.context),
                entry.revision_id,
                self._build_id(entry.build),
                entry.d,
                entry.last_used,
            ),
        )

    def _save_evaluation(self, evaluation: Evaluation) -> None:
        self._db.execute(
            """INSERT INTO evaluation
            (id, at, context, context_since, outcome, threshold, engine_build, return_pause)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                evaluation.id,
                evaluation.at,
                self._context_id(evaluation.context),
                evaluation.context_since,
                "error" if evaluation.failed else "ok",
                evaluation.threshold,
                self._build_id(evaluation.build),
                evaluation.return_pause,
            ),
        )
        self._db.executemany(
            """INSERT INTO candidate (evaluation, revision, d, from_cache, outcome)
            VALUES (?, ?, ?, ?, ?)""",
            [
                (evaluation.id, c.revision_id, c.d, int(c.from_cache), c.outcome.value)
                for c in evaluation.candidates
            ],
        )

    def _save_left(self, left: Left) -> None:
        """When the context left goes on the evaluations of its stretch in front (ADR-0021)."""
        self._db.execute(
            """UPDATE evaluation SET context_until = ?
            WHERE context_since = ? AND context_until IS NULL AND context = (
                SELECT id FROM context
                WHERE app = ? AND title = ? AND ifnull(address, '') = ifnull(?, '')
            )""",
            (left.until, left.since, left.context.app, left.context.title, left.context.address),
        )

    def _save_stretch(self, stretch: SituationStretch) -> None:
        self._db.execute(
            "INSERT INTO situation (kind, value, since, until) VALUES (?, ?, ?, ?)",
            (stretch.situation.value, stretch.value, stretch.since, stretch.until),
        )

    def _save_alert(self, alert: Alert) -> None:
        # An alert the daily cleanup deleted while `core` kept it unseen comes back without its
        # evaluation, which expired with it: as the cleanup leaves an answered alert.
        self._db.execute(
            """INSERT INTO alert (id, revision, evaluation, context, d, created_at, due_at,
                shown_at, vanished_at, seen_at, answer, snooze, answered_at, requested)
            VALUES (
                ?, ?, (SELECT id FROM evaluation WHERE id = ?), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT (id) DO UPDATE
            SET shown_at = excluded.shown_at, vanished_at = excluded.vanished_at,
                seen_at = excluded.seen_at, answer = excluded.answer, snooze = excluded.snooze,
                answered_at = excluded.answered_at""",
            (
                alert.id,
                alert.revision.id,
                alert.evaluation_id,
                self._context_id(alert.context),
                alert.d,
                alert.created_at,
                alert.due_at,
                alert.shown_at,
                alert.vanished_at,
                alert.seen_at,
                None if alert.answer is None else alert.answer.value,
                None if alert.snooze is None else alert.snooze.value,
                alert.answered_at,
                int(alert.requested),
            ),
        )

    def _save_sleep(self, sleep: EngineSleep) -> None:
        """A sleep comes when it starts, then again when it ends: the end replaces its row, so an
        app that dies while the engine sleeps still leaves the start (ADR-0027)."""
        self._db.execute(
            """INSERT INTO engine_sleep (slept_at, reason, woken_at, woken_by, ready_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (slept_at) DO UPDATE
            SET reason = excluded.reason, woken_at = excluded.woken_at,
                woken_by = excluded.woken_by, ready_at = excluded.ready_at""",
            (
                sleep.slept_at,
                sleep.reason.value,
                sleep.woken_at,
                None if sleep.woken_by is None else sleep.woken_by.value,
                sleep.ready_at,
            ),
        )

    def _context_id(self, context: Context) -> int:
        values = (context.app, context.title, context.address)
        self._db.execute(
            "INSERT OR IGNORE INTO context (app, title, address) VALUES (?, ?, ?)", values
        )
        row = self._db.execute(
            """SELECT id FROM context
            WHERE app = ? AND title = ? AND ifnull(address, '') = ifnull(?, '')""",
            values,
        ).fetchone()
        return int(row[0])

    def _build_id(self, build: EngineBuild | None) -> int | None:
        if build is None:
            return None
        values = (
            build.protocol,
            build.engine_version,
            build.llama_cpp_build,
            build.model_sha256,
            build.judge_prompt,
            build.rewrite_prompt,
        )
        self._db.execute(
            """INSERT OR IGNORE INTO engine_build (protocol, engine_version, llama_cpp_build,
                model_sha256, judge_prompt, rewrite_prompt)
            VALUES (?, ?, ?, ?, ?, ?)""",
            values,
        )
        row = self._db.execute(
            """SELECT id FROM engine_build WHERE protocol = ? AND engine_version = ?
            AND llama_cpp_build = ? AND model_sha256 = ? AND judge_prompt = ?
            AND rewrite_prompt = ?""",
            values,
        ).fetchone()
        return int(row[0])

    # Loading

    def _builds(self) -> dict[int, EngineBuild]:
        return {
            row[0]: EngineBuild(*row[1:])
            for row in self._db.execute(
                """SELECT id, protocol, engine_version, llama_cpp_build, model_sha256,
                    judge_prompt, rewrite_prompt
                FROM engine_build"""
            )
        }

    def _answers(self, builds: Mapping[int, EngineBuild], which: str) -> tuple[ContextAnswer, ...]:
        """The answers per place that `which` keeps, the oldest first."""
        return tuple(
            ContextAnswer(
                row[0],
                Context(*row[1:4]),
                Here(row[4]),
                row[5],
                None if row[6] is None else builds[row[6]],
                row[7],
            )
            for row in self._db.execute(
                f"""SELECT reminder, app, title, address, here, d, engine_build, at
                FROM context_answer JOIN context ON context.id = context_answer.context
                WHERE {which} ORDER BY context_answer.id"""
            )
        )

    @staticmethod
    def _revision(row: Sequence[Any], builds: Mapping[int, EngineBuild]) -> Revision:
        """A revision from the columns of `_REVISION`."""
        return Revision(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            statement=row[6],
            statement_build=None if row[7] is None else builds[row[7]],
            schedule=None if row[8] is None else schedules.loads(row[8]),
            written_at=row[9],
            perennial=bool(row[10]),
            created_at=row[11],
            situations=terms.loads(row[12]),
        )

    @staticmethod
    def _alert(row: Sequence[Any], revision: Revision) -> Alert:
        """An alert from the columns of `_ALERT`."""
        return Alert(
            row[0],
            revision.reminder_id,
            revision,
            row[2],
            Context(*row[3:6]),
            d=row[6],
            created_at=row[7],
            due_at=row[8],
            shown_at=row[9],
            vanished_at=row[10],
            seen_at=row[11],
            answer=None if row[12] is None else Answer(row[12]),
            answered_at=row[13],
            snooze=None if row[14] is None else Snooze(row[14]),
            requested=bool(row[15]),
        )

    def _unseen(self, builds: Mapping[int, EngineBuild]) -> tuple[Alert, ...]:
        """Alerts shown and never answered, the last of their active reminder, the latest to
        vanish first: the tray list keeps one per reminder (ADR-0021)."""
        last = _LAST_ALERT.format(which="1")
        rows = self._db.execute(
            f"""SELECT {_ALERT}, {_REVISION}
            FROM alert
            JOIN revision ON revision.id = alert.revision
            JOIN reminder ON reminder.id = revision.reminder
            JOIN context ON context.id = alert.context
            WHERE answer IS NULL AND shown_at IS NOT NULL AND completed_at IS NULL
                AND alert.id = {last}
            ORDER BY ifnull(vanished_at, shown_at) DESC, alert.id DESC"""
        )
        return tuple(self._alert(row, self._revision(row[16:], builds)) for row in rows)

    def _last_ids(self) -> LastIds:
        row = self._db.execute(
            """SELECT (SELECT ifnull(max(id), 0) FROM reminder),
                (SELECT ifnull(max(id), 0) FROM revision),
                (SELECT ifnull(max(id), 0) FROM evaluation),
                (SELECT ifnull(max(id), 0) FROM alert)"""
        ).fetchone()
        return LastIds(*row)

    # Deleting and maintenance

    def _delete(self, sql: str, cutoff: int) -> int:
        return self._db.execute(sql, (cutoff,)).rowcount

    def _delete_orphan_contexts(self) -> int:
        return self._db.execute(
            """DELETE FROM context
            WHERE NOT EXISTS (SELECT 1 FROM evaluation WHERE evaluation.context = context.id)
            AND NOT EXISTS (SELECT 1 FROM alert WHERE alert.context = context.id)
            AND NOT EXISTS (
                SELECT 1 FROM context_answer WHERE context_answer.context = context.id
            )
            AND NOT EXISTS (SELECT 1 FROM judgement WHERE judgement.context = context.id)"""
        ).rowcount

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Committed at the end, also after reads, so that no snapshot holds the WAL back."""
        try:
            yield
        except BaseException:
            self._db.rollback()
            raise
        self._db.commit()

    def _checkpoint(self, *, optimize: bool = False) -> None:
        """Empty the WAL into the database, outside any transaction."""
        self._db.autocommit = True
        try:
            if optimize:
                self._db.execute("PRAGMA optimize")
            self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            self._db.autocommit = False
