"""The rules of the product: reminders, their judging, and their alerts (ADR-0007, ADR-0014).

The worker thread owns `Reminders` and gives it one event at a time: observations, deadlines
and the user's commands (ADR-0012). It keeps its state in memory, tells the interface about
the alerts and the reminders through two callbacks, and hands the records to save to whoever
calls `take_records`.
"""

import itertools
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import time, timedelta
from enum import Enum, auto

from jiffin.core.alerts import Alerts, AlertsView
from jiffin.core.clock import Clock
from jiffin.core.context import Context, Observation
from jiffin.core.debounce import Debounce
from jiffin.core.model import EngineBuild, Model, ModelError
from jiffin.core.records import (
    Alert,
    Answer,
    CacheEntry,
    Candidate,
    Evaluation,
    Outcome,
    Record,
    Reminder,
    ReminderDeleted,
    Revision,
    Silence,
    SilencesCleared,
    Snapshot,
)

THRESHOLD = 0.97
"""d from which a reminder alerts: the starting value of ADR-0007. It belongs to the engine's
model and prompts, and the acceptance day fixes it."""

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS

REPEAT_AFTER_MS = HOUR_MS
"""A reminder that is not completed alerts at most once an hour."""


class Snooze(Enum):
    QUARTER_HOUR = auto()
    HOUR = auto()
    TOMORROW = auto()


# "Domani" is the next day at 08:00, local time: the usual meaning in mail and reminder apps,
# at the earlier of their usual hours (8 or 9), since the alert waits for its context anyway.
# Before 04:00 the night is not over, and "domani" is 08:00 of the same day, as in Anki.
TOMORROW_AT = time(8)
DAY_STARTS_AT = time(4)


@dataclass(frozen=True, slots=True)
class ActiveReminder:
    """A reminder not completed yet, as the tray list shows it."""

    reminder: Reminder
    silences: int
    """How many contexts "Non qui" has silenced it in, until its text changes."""


@dataclass(frozen=True, slots=True)
class RemindersView:
    """What the interface shows of the reminders."""

    active: tuple[ActiveReminder, ...]
    """Newest first."""


class Reminders:
    def __init__(
        self,
        model: Model,
        clock: Clock,
        on_alerts: Callable[[AlertsView], None],
        on_reminders: Callable[[RemindersView], None],
        saved: Snapshot | None = None,
        *,
        threshold: float = THRESHOLD,
    ) -> None:
        """Start from what `store` saved, or from nothing.

        Only the harness judges at another threshold, to choose the next one (ADR-0013).
        """
        saved = saved or Snapshot()
        self._model = model
        self._threshold = threshold
        self._clock = clock
        self._on_alerts = on_alerts
        self._on_reminders = on_reminders
        self._debounce = Debounce()
        self._alerts = Alerts(saved.unseen)
        self._reminders = {reminder.id: reminder for reminder in saved.reminders}
        self._silences = {(silence.reminder_id, silence.context) for silence in saved.silences}
        self._cache = {(e.context, e.revision_id, e.build): e.d for e in saved.cache}
        self._last_alert_at = dict(saved.last_alerts)
        self._snooze_deadlines = {
            reminder.id: reminder.snoozed_until
            for reminder in saved.reminders
            if reminder.completed_at is None and reminder.snoozed_until is not None
        }
        self._records: list[Record] = []
        self._alerts_changed = bool(saved.unseen)
        self._reminders_changed = bool(saved.reminders)
        self._reminder_ids = itertools.count(saved.last_ids.reminder + 1)
        self._revision_ids = itertools.count(saved.last_ids.revision + 1)
        self._evaluation_ids = itertools.count(saved.last_ids.evaluation + 1)
        self._alert_ids = itertools.count(saved.last_ids.alert + 1)

    def take_records(self) -> list[Record]:
        """What changed since the last call, in the order `store` must save it."""
        records, self._records = self._records, []
        return records

    # Time

    @property
    def deadline(self) -> int | None:
        """When `poll` has something to do: a context becomes stable, or a snooze ends."""
        deadlines = list(self._snooze_deadlines.values())
        if self._debounce.deadline is not None:
            deadlines.append(self._debounce.deadline)
        return min(deadlines, default=None)

    def observe(self, observation: Observation) -> None:
        self._catch_up(observation.at)
        self._debounce.observe(observation)
        self._publish()

    def poll(self) -> None:
        self._catch_up(self._clock.now())
        self._publish()

    # Commands from the interface. The interface does not wait for them, so a command about a
    # reminder or an alert that is gone meanwhile does nothing.

    def create(self, condition: str, action: str) -> Reminder:
        reminder_id = next(self._reminder_ids)
        revision = Revision(next(self._revision_ids), reminder_id, 1, condition, action)
        self._save(Reminder(reminder_id, self._clock.now(), revision))
        self._write_statement(reminder_id)
        self._publish()
        return self._reminders[reminder_id]

    def edit(self, reminder_id: int, condition: str, action: str) -> None:
        """A new text is a new revision: its silences go, and it waits for a new statement."""
        reminder = self._reminders.get(reminder_id)
        if reminder is None:
            return
        old = reminder.revision
        if (condition, action) == (old.condition, old.action):
            return
        self._forget_scores(old.id)
        if any(silenced == reminder_id for silenced, _ in self._silences):
            self._silences = {s for s in self._silences if s[0] != reminder_id}
            self._records.append(SilencesCleared(reminder_id))
        revision = Revision(
            next(self._revision_ids), reminder_id, old.number + 1, condition, action
        )
        self._save(replace(reminder, revision=revision))
        self._write_statement(reminder_id)
        self._publish()

    def complete(self, reminder_id: int) -> None:
        reminder = self._reminders.get(reminder_id)
        if reminder is None or reminder.completed_at is not None:
            return
        now = self._clock.now()
        self._save(replace(reminder, completed_at=now))
        self._snooze_deadlines.pop(reminder_id, None)
        self._close_alerts(reminder_id, now)
        self._publish()

    def delete(self, reminder_id: int) -> None:
        reminder = self._reminders.pop(reminder_id, None)
        if reminder is None:
            return
        self._forget_scores(reminder.revision.id)
        self._silences = {s for s in self._silences if s[0] != reminder_id}
        self._last_alert_at.pop(reminder_id, None)
        self._snooze_deadlines.pop(reminder_id, None)
        self._close_alerts(reminder_id, self._clock.now())
        self._records.append(ReminderDeleted(reminder_id))
        self._reminders_changed = True
        self._publish()

    def done(self, alert_id: int) -> None:
        """Fatto: the reminder is completed, and the alert counts as useful."""
        alert = self._answer(alert_id, Answer.DONE)
        if alert is not None:
            self.complete(alert.reminder_id)
        self._publish()

    def useful(self, alert_id: int) -> None:
        """Utile: the reminder stays active."""
        self._answer(alert_id, Answer.USEFUL)
        self._publish()

    def not_here(self, alert_id: int) -> None:
        """Non qui: the reminder keeps quiet in this exact context until its text changes."""
        alert = self._answer(alert_id, Answer.NOT_HERE)
        if alert is not None and alert.reminder_id in self._reminders:
            self._silences.add((alert.reminder_id, alert.context))
            self._records.append(Silence(alert.reminder_id, alert.context))
            self._reminders_changed = True
        self._publish()

    def snooze(self, alert_id: int, snooze: Snooze) -> None:
        """Rimanda: when the snooze ends, the alert comes back only in a context judged true."""
        alert = self._answer(alert_id, Answer.SNOOZE)
        reminder = None if alert is None else self._reminders.get(alert.reminder_id)
        if reminder is not None:
            until = self._snooze_end(snooze)
            self._save(replace(reminder, snoozed_until=until))
            self._snooze_deadlines[reminder.id] = until
        self._publish()

    def vanished(self, alert_id: int) -> None:
        """The alert left the screen after 10 s without an answer (the timer is the interface's)."""
        self._records.extend(self._alerts.vanish(alert_id, self._clock.now()))
        self._alerts_changed = True
        self._publish()

    def seen(self) -> None:
        """The tray list is open: the alerts that vanished unanswered are seen now."""
        self._records.extend(self._alerts.see(self._clock.now()))
        self._alerts_changed = True
        self._publish()

    # Judging

    def _catch_up(self, until: int) -> None:
        """Handle every deadline up to `until`, in order."""
        while (deadline := self.deadline) is not None and deadline <= until:
            if deadline == self._debounce.deadline:
                request = self._debounce.poll(deadline)
                if request is not None:
                    self._evaluate(request.context, request.context_since, None)
                continue
            reminder_id = min(self._snooze_deadlines, key=self._snooze_deadlines.__getitem__)
            del self._snooze_deadlines[reminder_id]
            stable = self._debounce.stable
            if stable is not None:
                self._evaluate(stable.context, stable.context_since, [reminder_id])

    def _evaluate(
        self, context: Context, context_since: int, reminder_ids: Iterable[int] | None
    ) -> None:
        """Judge the reminders in a stable context: all of them, or those whose snooze ended."""
        self._write_missing_statements()
        if reminder_ids is None:
            reminder_ids = list(self._reminders)
        judged = [
            reminder
            for reminder_id in reminder_ids
            if (reminder := self._reminders.get(reminder_id)) is not None
            and reminder.completed_at is None
            and reminder.revision.statement is not None
        ]
        evaluation_id = next(self._evaluation_ids)
        try:
            build, candidates = self._judge(context, judged)
        except ModelError:
            now = self._clock.now()
            self._records.append(
                Evaluation(
                    evaluation_id,
                    now,
                    context,
                    context_since,
                    self._threshold,
                    None,
                    (),
                    failed=True,
                )
            )
            return
        now = self._clock.now()
        self._records.append(
            Evaluation(
                evaluation_id, now, context, context_since, self._threshold, build, candidates
            )
        )
        for reminder, candidate in zip(judged, candidates, strict=True):
            if reminder.snoozed_until is not None and reminder.snoozed_until <= now:
                # Its snooze is over, and it has now been checked against the current context.
                self._snooze_deadlines.pop(reminder.id, None)
            if candidate.outcome is Outcome.ALERT:
                self._alert(reminder, evaluation_id, context, candidate.d, now)

    def _judge(
        self, context: Context, judged: list[Reminder]
    ) -> tuple[EngineBuild | None, tuple[Candidate, ...]]:
        """Score the reminders, from the cache or the model, and give each one its outcome."""
        if not judged:
            return None, ()
        build = self._model.build()
        scores, fresh = self._scores(context, judged, build)
        now = self._clock.now()
        candidates = []
        for reminder in judged:
            revision_id = reminder.revision.id
            d = scores[revision_id]
            self._records.append(CacheEntry(context, revision_id, build, d, now))
            outcome = self._outcome(reminder, context, d, now)
            candidates.append(Candidate(revision_id, d, revision_id not in fresh, outcome))
        return build, tuple(candidates)

    def _scores(
        self, context: Context, judged: list[Reminder], build: EngineBuild
    ) -> tuple[dict[int, float], set[int]]:
        """d for every judged revision, with the ids of those the model has just scored."""
        scores: dict[int, float] = {}
        missing: dict[int, str] = {}
        for reminder in judged:
            revision = reminder.revision
            cached = self._cache.get((context, revision.id, build))
            if cached is not None:
                scores[revision.id] = cached
            elif revision.statement is not None:
                missing[revision.id] = revision.statement
        if missing:
            fresh = self._model.judge(context, missing)
            if fresh.keys() != missing.keys():
                raise ModelError("the model must score every statement it is given")
            for revision_id, d in fresh.items():
                self._cache[(context, revision_id, build)] = d
            scores.update(fresh)
        return scores, set(missing)

    def _outcome(self, reminder: Reminder, context: Context, d: float, now: int) -> Outcome:
        if d < self._threshold:
            return Outcome.BELOW_THRESHOLD
        if (reminder.id, context) in self._silences:
            return Outcome.SILENCED
        snoozed_until = reminder.snoozed_until
        if snoozed_until is not None and now < snoozed_until:
            return Outcome.SNOOZED
        last = self._last_alert_at.get(reminder.id)
        if snoozed_until is None and last is not None and now - last < REPEAT_AFTER_MS:
            return Outcome.HELD_BACK
        return Outcome.ALERT

    def _alert(
        self, reminder: Reminder, evaluation_id: int, context: Context, d: float, now: int
    ) -> None:
        alert = Alert(
            next(self._alert_ids), reminder.id, reminder.revision, evaluation_id, context, d, now
        )
        self._last_alert_at[reminder.id] = now
        if reminder.snoozed_until is not None:
            self._save(replace(reminder, snoozed_until=None))
        self._records.append(self._alerts.add(alert, now))
        self._alerts_changed = True

    # Helpers

    def _save(self, reminder: Reminder) -> None:
        self._reminders[reminder.id] = reminder
        self._records.append(reminder)
        self._reminders_changed = True

    def _write_statement(self, reminder_id: int) -> None:
        reminder = self._reminders[reminder_id]
        try:
            statement = self._model.rewrite(reminder.revision.condition)
            build = self._model.build()
        except ModelError:
            return  # it is tried again before the next evaluation
        revision = replace(reminder.revision, statement=statement, statement_build=build)
        self._save(replace(reminder, revision=revision))

    def _write_missing_statements(self) -> None:
        for reminder in list(self._reminders.values()):
            if reminder.completed_at is None and reminder.revision.statement is None:
                self._write_statement(reminder.id)

    def _forget_scores(self, revision_id: int) -> None:
        self._cache = {key: d for key, d in self._cache.items() if key[1] != revision_id}

    def _answer(self, alert_id: int, answer: Answer) -> Alert | None:
        alert = self._alerts.find(alert_id)
        if alert is None:
            return None
        now = self._clock.now()
        answered = replace(alert, answer=answer, answered_at=now)
        self._records.append(answered)
        self._records.extend(self._alerts.close(alert_id, now))
        self._alerts_changed = True
        return answered

    def _close_alerts(self, reminder_id: int, now: int) -> None:
        for alert in self._alerts.of(reminder_id):
            self._records.extend(self._alerts.close(alert.id, now))
            self._alerts_changed = True

    def _snooze_end(self, snooze: Snooze) -> int:
        now = self._clock.now()
        match snooze:
            case Snooze.QUARTER_HOUR:
                return now + 15 * MINUTE_MS
            case Snooze.HOUR:
                return now + HOUR_MS
            case Snooze.TOMORROW:
                local = self._clock.local(now)
                day = local.date()
                if local.time() >= DAY_STARTS_AT:
                    day += timedelta(days=1)
                return self._clock.instant(day, TOMORROW_AT)

    def _publish(self) -> None:
        if self._alerts_changed:
            self._alerts_changed = False
            self._on_alerts(self._alerts.view())
        if self._reminders_changed:
            self._reminders_changed = False
            self._on_reminders(self._reminders_view())

    def _reminders_view(self) -> RemindersView:
        silences = Counter(reminder_id for reminder_id, _ in self._silences)
        # Ids grow with each new reminder.
        newest_first = sorted(self._reminders.values(), key=lambda r: r.id, reverse=True)
        return RemindersView(
            tuple(
                ActiveReminder(reminder, silences[reminder.id])
                for reminder in newest_first
                if reminder.completed_at is None
            )
        )
