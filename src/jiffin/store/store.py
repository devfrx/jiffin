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
    Evaluation,
    Here,
    LastIds,
    Left,
    Outcome,
    Record,
    Reminder,
    ReminderDeleted,
    Revision,
    Silence,
    Snapshot,
    Snooze,
)
from jiffin.core.situations import SituationStretch
from jiffin.store import schedules
from jiffin.store.database import open_database

log = logging.getLogger(__name__)

RETENTION_MS = 30 * 24 * 60 * 60 * 1000
"""Evaluations, unanswered alerts and unused cache entries are kept for 30 days."""

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]

# The current revision of each reminder: the one with the highest number.
_CURRENT = (
    "revision.number = (SELECT max(number) FROM revision AS r WHERE r.reminder = revision.reminder)"
)
# The columns of a revision, in the order `Store._revision` reads them.
_REVISION = """revision.id, revision.reminder, revision.number, revision.condition, revision.action,
    revision.remainder, revision.statement, revision.statement_build, revision.schedule,
    revision.written_at, revision.perennial, revision.created_at"""
# The latest alert of the reminder of `revision`, among those `which` keeps.
_LAST_ALERT = """(SELECT max(a.id) FROM alert AS a JOIN revision AS r ON r.id = a.revision
    WHERE r.reminder = revision.reminder AND {which})"""


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
    with only a time, which has none, is not."""
    silences: tuple[Silence, ...]
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
        """Save what `core` changed, all or nothing."""
        deleted = False
        with self._transaction():
            for record in records:
                match record:
                    case Reminder():
                        self._save_reminder(record)
                    case ReminderDeleted():
                        self._delete_reminder(record.reminder_id)
                        deleted = True
                    # Until migration 0003 gives the answers per place their table (#150),
                    # `silence` holds the places whose last answer is Not here: Remind here and
                    # the withdrawals only take a silence away.
                    case ContextAnswer(here=Here.NO):
                        self._db.execute(
                            "INSERT OR IGNORE INTO silence (reminder, context) VALUES (?, ?)",
                            (record.reminder_id, self._context_id(record.context)),
                        )
                    case ContextAnswer():
                        context = record.context
                        self._db.execute(
                            """DELETE FROM silence WHERE reminder = ? AND context IN (
                                SELECT id FROM context WHERE app = ? AND title = ?
                                AND ifnull(address, '') = ifnull(?, ''))""",
                            (record.reminder_id, context.app, context.title, context.address),
                        )
                    case CacheEntry():
                        self._save_cache_entry(record)
                    case Evaluation():
                        self._save_evaluation(record)
                    case Left():
                        self._save_left(record)
                    case SituationStretch():
                        pass  # until migration 0003 gives them their table, `situation` (#150)
                    case Alert():
                        self._save_alert(record)
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
            silences = self._silences()
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
                reminders, silences, cache, last_alerts, self._unseen(builds), self._last_ids()
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
                    """SELECT alert.id, revision, evaluation, app, title, address, d, created_at,
                        due_at, shown_at, vanished_at, seen_at, answer, answered_at, snooze
                    FROM alert JOIN context ON context.id = alert.context
                    WHERE evaluation IS NOT NULL OR d IS NULL ORDER BY created_at, alert.id"""
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
            return Log(reminders, revisions, evaluations, alerts, self._silences(), left)

    def cleanup(self, now: int) -> None:
        """Delete what the retention rules of ADR-0014 no longer keep, at startup and daily."""
        cutoff = now - RETENTION_MS
        with self._transaction():
            evaluations = self._delete("DELETE FROM evaluation WHERE at < ?", cutoff)
            alerts = self._delete(
                "DELETE FROM alert WHERE answer IS NULL AND created_at < ?", cutoff
            )
            entries = self._delete("DELETE FROM judgement WHERE last_used < ?", cutoff)
            contexts = self._delete_orphan_contexts()
        self._checkpoint(optimize=True)
        log.info(
            "cleanup deleted %d evaluations, %d alerts, %d cache entries and %d contexts",
            evaluations,
            alerts,
            entries,
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
                statement, statement_build, schedule, written_at, perennial, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        # Until migration 0003 adds `outside_situation` to the outcomes of `candidate` (#150),
        # a reminder outside its situation leaves no row: its d is in the cache.
        self._db.executemany(
            """INSERT INTO candidate (evaluation, revision, d, from_cache, outcome)
            VALUES (?, ?, ?, ?, ?)""",
            [
                (evaluation.id, c.revision_id, c.d, int(c.from_cache), c.outcome.value)
                for c in evaluation.candidates
                if c.outcome is not Outcome.OUTSIDE_SITUATION
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

    def _save_alert(self, alert: Alert) -> None:
        # An alert the daily cleanup deleted while `core` kept it unseen comes back without its
        # evaluation, which expired with it: as the cleanup leaves an answered alert.
        self._db.execute(
            """INSERT INTO alert (id, revision, evaluation, context, d, created_at, due_at,
                shown_at, vanished_at, seen_at, answer, snooze, answered_at)
            VALUES (?, ?, (SELECT id FROM evaluation WHERE id = ?), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def _silences(self) -> tuple[Silence, ...]:
        return tuple(
            Silence(row[0], Context(*row[1:]))
            for row in self._db.execute(
                """SELECT reminder, app, title, address
                FROM silence JOIN context ON context.id = silence.context
                ORDER BY reminder, context.id"""
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
        )

    @staticmethod
    def _alert(row: Sequence[Any], revision: Revision) -> Alert:
        """An alert from its columns: id, revision, evaluation, app, title, address, d,
        created_at, due_at, shown_at, vanished_at, seen_at, answer, answered_at, snooze."""
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
        )

    def _unseen(self, builds: Mapping[int, EngineBuild]) -> tuple[Alert, ...]:
        """Alerts shown and never answered, the last of their active reminder, the latest to
        vanish first: the tray list keeps one per reminder (ADR-0021)."""
        last = _LAST_ALERT.format(which="1")
        rows = self._db.execute(
            f"""SELECT alert.id, revision.id, alert.evaluation, app, title, address, alert.d,
                alert.created_at, due_at, shown_at, vanished_at, seen_at, answer, answered_at,
                snooze, {_REVISION}
            FROM alert
            JOIN revision ON revision.id = alert.revision
            JOIN reminder ON reminder.id = revision.reminder
            JOIN context ON context.id = alert.context
            WHERE answer IS NULL AND shown_at IS NOT NULL AND completed_at IS NULL
                AND alert.id = {last}
            ORDER BY ifnull(vanished_at, shown_at) DESC, alert.id DESC"""
        )
        return tuple(self._alert(row, self._revision(row[15:], builds)) for row in rows)

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
            AND NOT EXISTS (SELECT 1 FROM silence WHERE silence.context = context.id)
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
