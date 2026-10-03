"""The rules of the product: reminders, their judging, and their alerts (ADR-0007, ADR-0014,
ADR-0021).

The worker thread owns `Reminders` and gives it one event at a time: observations, deadlines
and the user's commands (ADR-0012). It keeps its state in memory, tells the interface about
the alerts and the reminders through two callbacks, and hands the records to save to whoever
calls `take_records`.

A reminder rings at most once per unit (`units`): the instance of its time, or the occasion. An
occasion starts with a true stretch, a stable context judged true while its time holds, that
begins at least the return pause after the previous one ended.
"""

import itertools
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta

from jiffin.core.alerts import Alerts, AlertsView
from jiffin.core.clock import Clock
from jiffin.core.context import Context, Observation
from jiffin.core.debounce import Debounce, EvaluationRequest
from jiffin.core.meanings import read
from jiffin.core.model import EngineBuild, Model, ModelError
from jiffin.core.records import (
    Alert,
    Answer,
    CacheEntry,
    Candidate,
    Evaluation,
    Left,
    Outcome,
    Record,
    Reminder,
    ReminderDeleted,
    Revision,
    Silence,
    SilencesCleared,
    Snapshot,
    Snooze,
)
from jiffin.core.schedule import jiffin_day
from jiffin.core.units import Times, by_instance

THRESHOLD = 0.97
"""d from which a reminder alerts: the starting value of ADR-0007. It belongs to the engine's
model and prompts, and the acceptance day fixes it."""

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS

RETURN_PAUSE_MS = 2 * MINUTE_MS
"""How long the user must be away from a thing for its reminders to ring again when they come
back: the default of the settings, which allow 10 s to 2 hours (ADR-0021)."""
SHORTEST_RETURN_PAUSE_MS = 10_000
LONGEST_RETURN_PAUSE_MS = 2 * HOUR_MS

# "Domani" is the next day at 08:00, local time: the usual meaning in mail and reminder apps,
# at the earlier of their usual hours (8 or 9), since the alert waits for its context anyway.
# Before 04:00 the night is not over, and "domani" is 08:00 of the same day, as in Anki.
TOMORROW_AT = time(8)


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


@dataclass(frozen=True, slots=True)
class _Time:
    """The window a reminder's time is in, in UTC milliseconds."""

    start: int | None
    """None for a reminder without a time, which may always ring."""
    end: int | None
    unit: int | None
    """When the unit began, for a reminder that rings once per instance of its time."""


_ALWAYS = _Time(None, None, None)


@dataclass(slots=True)
class _Stretches:
    """The true stretches of a reminder with a remainder, from which its occasions come."""

    since: int | None = None
    """When the stretch under way began; None while there is none."""
    until: int | None = None
    """When the window of the stretch under way ends, if it does."""
    ended: int | None = None
    """When the last stretch ended."""
    occasion: int | None = None
    """When the current occasion began."""


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
        return_pause: int = RETURN_PAUSE_MS,
    ) -> None:
        """Start from what `store` saved, or from nothing; occasions start afresh (ADR-0021).

        Only the harness judges at another threshold, to choose the next one (ADR-0013). The
        return pause is in milliseconds.
        """
        saved = saved or Snapshot()
        self._model = model
        self._threshold = threshold
        self._return_pause = return_pause
        self._clock = clock
        self._on_alerts = on_alerts
        self._on_reminders = on_reminders
        self._debounce = Debounce()
        self._alerts = Alerts(saved.unseen)
        self._reminders = {reminder.id: reminder for reminder in saved.reminders}
        self._silences = {(silence.reminder_id, silence.context) for silence in saved.silences}
        self._cache = {(e.context, e.revision_id, e.build): e.d for e in saved.cache}
        self._counted = {
            reminder_id: [(alert_id, at)] for reminder_id, alert_id, at in saved.last_alerts
        }
        """The alerts that count in the units of each reminder, as (id, when): all but those
        answered "Non qui"."""
        self._stretches: dict[int, _Stretches] = {}
        self._times: dict[int, Times] = {}
        """The windows of the revisions with a time, by revision."""
        self._snooze_deadlines = {
            reminder.id: reminder.snoozed_until
            for reminder in saved.reminders
            if reminder.completed_at is None and reminder.snoozed_until is not None
        }
        self._edges: dict[int, int] = {}
        """While a context is stable: when the time of each reminder starts or ends next."""
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

    @property
    def return_pause(self) -> int:
        """In milliseconds. A change from the settings is in force at once: it decides the
        occasions of the stretches that start after it (ADR-0021)."""
        return self._return_pause

    @return_pause.setter
    def return_pause(self, return_pause: int) -> None:
        self._return_pause = return_pause

    # Time

    @property
    def deadline(self) -> int | None:
        """When `poll` has something to do: a context becomes stable, a snooze ends, or the time
        of a reminder starts or ends while a context is stable."""
        deadlines = [*self._snooze_deadlines.values(), *self._edges.values()]
        if self._debounce.deadline is not None:
            deadlines.append(self._debounce.deadline)
        return min(deadlines, default=None)

    def observe(self, observation: Observation) -> None:
        self._catch_up(observation.at)
        stable = self._debounce.stable
        if stable is not None and observation.context != stable.context:
            self._leave(stable, observation.at)
        self._debounce.observe(observation)
        if self._debounce.stable is None:
            self._edges = {}
        self._publish()

    def poll(self) -> None:
        self._catch_up(self._clock.now())
        self._publish()

    def model_ready(self) -> None:
        """The model answers again, after a start or a restart (ADR-0011): the statements it
        missed are written, and the stable context, if any, is judged again. The cache spares
        what was judged already, and the unit a second alert."""
        stable = self._debounce.stable
        if stable is None:
            self._write_missing_statements()
        else:
            self._evaluate(stable.context, stable.context_since, None)
            self._plan()
        self._publish()

    # Commands from the interface. The interface does not wait for them, so a command about a
    # reminder or an alert that is gone meanwhile does nothing.

    def create(self, condition: str, action: str, perennial: bool = False) -> Reminder:
        """A new reminder: its time is read now (ADR-0020), and its remainder goes to the engine."""
        now = self._clock.now()
        reading = read(condition, self._clock.local(now))
        reminder_id = next(self._reminder_ids)
        revision = Revision(
            next(self._revision_ids),
            reminder_id,
            1,
            condition,
            action,
            reading.remainder,
            schedule=reading.schedule,
            written_at=now,
            perennial=perennial,
            created_at=now,
        )
        self._save(Reminder(reminder_id, now, revision))
        self._write_statement(reminder_id)
        self._plan([reminder_id])
        self._publish()
        return self._reminders[reminder_id]

    def edit(self, reminder_id: int, condition: str, action: str, perennial: bool = False) -> None:
        """A new revision. A new text clears its silences; a new condition is read again from now,
        and a new remainder waits for a new statement. The same condition keeps its time
        (ADR-0020)."""
        reminder = self._reminders.get(reminder_id)
        if reminder is None:
            return
        old = reminder.revision
        if (condition, action, perennial) == (old.condition, old.action, old.perennial):
            return
        now = self._clock.now()
        self._forget(old)
        if (condition, action) != (old.condition, old.action) and any(
            silenced == reminder_id for silenced, _ in self._silences
        ):
            self._silences = {s for s in self._silences if s[0] != reminder_id}
            self._records.append(SilencesCleared(reminder_id))
        revision = replace(
            old,
            id=next(self._revision_ids),
            number=old.number + 1,
            action=action,
            perennial=perennial,
            created_at=now,
        )
        if condition != old.condition:
            reading = read(condition, self._clock.local(now))
            same = reading.remainder == old.remainder
            revision = replace(
                revision,
                condition=condition,
                remainder=reading.remainder,
                statement=old.statement if same else None,
                statement_build=old.statement_build if same else None,
                schedule=reading.schedule,
                written_at=now,
            )
        self._close(reminder_id, now)
        self._save(replace(reminder, revision=revision))
        if revision.statement is None:
            self._write_statement(reminder_id)
        self._plan([reminder_id])
        self._publish()

    def complete(self, reminder_id: int) -> None:
        reminder = self._reminders.get(reminder_id)
        if reminder is None or reminder.completed_at is not None:
            return
        now = self._clock.now()
        self._save(replace(reminder, completed_at=now))
        self._snooze_deadlines.pop(reminder_id, None)
        self._edges.pop(reminder_id, None)
        self._stretches.pop(reminder_id, None)
        self._close_alerts(reminder_id, now)
        self._publish()

    def delete(self, reminder_id: int) -> None:
        reminder = self._reminders.pop(reminder_id, None)
        if reminder is None:
            return
        self._forget(reminder.revision)
        self._silences = {s for s in self._silences if s[0] != reminder_id}
        self._counted.pop(reminder_id, None)
        self._stretches.pop(reminder_id, None)
        self._snooze_deadlines.pop(reminder_id, None)
        self._edges.pop(reminder_id, None)
        self._close_alerts(reminder_id, self._clock.now())
        self._records.append(ReminderDeleted(reminder_id))
        self._reminders_changed = True
        self._publish()

    def done(self, alert_id: int) -> None:
        """Fatto: a one-off reminder is completed; a perennial one waits for its next unit."""
        alert = self._answer(alert_id, Answer.DONE)
        reminder = None if alert is None else self._reminders.get(alert.reminder_id)
        if reminder is not None and not reminder.revision.perennial:
            self.complete(reminder.id)
        self._publish()

    def not_here(self, alert_id: int) -> None:
        """Non qui: the reminder keeps quiet in this exact context until its text changes, and the
        alert does not count, so it may ring elsewhere in the same unit (ADR-0021)."""
        alert = self._answer(alert_id, Answer.NOT_HERE)
        if alert is not None and alert.reminder_id in self._reminders:
            self._silences.add((alert.reminder_id, alert.context))
            self._records.append(Silence(alert.reminder_id, alert.context))
            self._reminders_changed = True
            counted = self._counted.get(alert.reminder_id, [])
            self._counted[alert.reminder_id] = [c for c in counted if c[0] != alert.id]
            stable = self._debounce.stable
            if stable is not None and stable.context == alert.context:
                self._close(alert.reminder_id, self._clock.now())
        self._publish()

    def snooze(self, alert_id: int, snooze: Snooze) -> None:
        """Rimanda. Alla prossima volta waits for the next unit; the others keep the reminder quiet
        until they end, then it rings at the first chance, even within the same unit."""
        alert = self._answer(alert_id, Answer.SNOOZE, snooze)
        reminder = None if alert is None else self._reminders.get(alert.reminder_id)
        if reminder is not None:
            until = self._snooze_end(snooze)
            if until != reminder.snoozed_until:
                self._save(replace(reminder, snoozed_until=until))
            if until is None:
                self._snooze_deadlines.pop(reminder.id, None)
            else:
                self._snooze_deadlines[reminder.id] = until
        self._publish()

    def close(self, alert_id: int) -> None:
        """The X: the reminder waits for its next unit, and the alert, seen, does not go among
        the unseen."""
        self._answer(alert_id, Answer.CLOSED)
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
                    self._plan()
                continue
            due = sorted(
                {
                    reminder_id
                    for reminder_id, at in self._snooze_deadlines.items()
                    if at == deadline
                }
                | {reminder_id for reminder_id, at in self._edges.items() if at == deadline}
            )
            for reminder_id in due:
                if self._snooze_deadlines.get(reminder_id) == deadline:
                    del self._snooze_deadlines[reminder_id]
                if self._edges.get(reminder_id) == deadline:
                    del self._edges[reminder_id]
            stable = self._debounce.stable
            if stable is not None:
                self._evaluate(stable.context, stable.context_since, due)
                self._plan(due, after=max(deadline, self._clock.now()))

    def _leave(self, stable: EvaluationRequest, at: int) -> None:
        """The stable context left the foreground: its true stretches end."""
        for reminder_id in self._stretches:
            self._close(reminder_id, at)
        self._records.append(Left(stable.context, stable.context_since, at))

    def _evaluate(
        self, context: Context, context_since: int, reminder_ids: Iterable[int] | None
    ) -> None:
        """In a stable context, judge the reminders with a remainder and ring those with only a
        time: all of them when the context has just become stable, or those whose snooze or time
        has just ended or started."""
        self._write_missing_statements()
        now = self._clock.now()
        active = [
            reminder
            for reminder_id in (list(self._reminders) if reminder_ids is None else reminder_ids)
            if (reminder := self._reminders.get(reminder_id)) is not None
            and reminder.completed_at is None
        ]
        judged = [r for r in active if r.revision.remainder and r.revision.statement is not None]
        if reminder_ids is None or judged:
            self._judge(context, context_since, judged)
        for reminder in active:
            if not reminder.revision.remainder:
                self._ring_on_time(reminder, context, context_since)
            if reminder.snoozed_until is not None and reminder.snoozed_until <= now:
                # Its snooze is over, and it has now been checked against the current context.
                self._snooze_deadlines.pop(reminder.id, None)

    def _judge(self, context: Context, context_since: int, judged: list[Reminder]) -> None:
        evaluation_id = next(self._evaluation_ids)
        try:
            build, candidates, alerts = self._candidates(context, context_since, judged)
        except ModelError:
            self._records.append(
                Evaluation(
                    evaluation_id,
                    self._clock.now(),
                    context,
                    context_since,
                    self._threshold,
                    None,
                    (),
                    failed=True,
                    return_pause=self._return_pause,
                )
            )
            return
        now = self._clock.now()
        self._records.append(
            Evaluation(
                evaluation_id,
                now,
                context,
                context_since,
                self._threshold,
                build,
                candidates,
                return_pause=self._return_pause,
            )
        )
        for reminder, d, due in alerts:
            self._alert(reminder, evaluation_id, context, d, now, due)

    def _candidates(
        self, context: Context, context_since: int, judged: list[Reminder]
    ) -> tuple[EngineBuild | None, tuple[Candidate, ...], list[tuple[Reminder, float, int]]]:
        """Score the reminders, from the cache or the model, follow their true stretches, and
        give each one its outcome; with the alerts to make, and when each was due."""
        if not judged:
            return None, (), []
        build = self._model.build()
        scores, fresh = self._scores(context, judged, build)
        now = self._clock.now()
        candidates = []
        alerts = []
        for reminder in judged:
            revision_id = reminder.revision.id
            d = scores[revision_id]
            self._records.append(CacheEntry(context, revision_id, build, d, now))
            span = self._time(reminder.revision, now)
            silenced = (reminder.id, context) in self._silences
            if d >= self._threshold and span is not None and not silenced:
                start = context_since if span.start is None else max(context_since, span.start)
                self._open(reminder.id, start, span.end)
            else:
                self._close(reminder.id, now)
            outcome = self._outcome(reminder, context, d, span, now)
            candidates.append(Candidate(revision_id, d, revision_id not in fresh, outcome))
            if outcome is Outcome.ALERT and span is not None:
                alerts.append((reminder, d, self._due(reminder, span, context_since, now)))
        return build, tuple(candidates), alerts

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

    def _outcome(
        self, reminder: Reminder, context: Context, d: float, span: _Time | None, now: int
    ) -> Outcome:
        if d < self._threshold:
            return Outcome.BELOW_THRESHOLD
        if span is None:
            return Outcome.OUTSIDE_TIME
        if (reminder.id, context) in self._silences:
            return Outcome.SILENCED
        if self._snoozed(reminder, now):
            return Outcome.SNOOZED
        if self._rang(reminder, span, now):
            return Outcome.SAME_OCCASION
        return Outcome.ALERT

    def _ring_on_time(self, reminder: Reminder, context: Context, context_since: int) -> None:
        """A reminder with only a time rings in any stable context: the user is there."""
        now = self._clock.now()
        span = self._time(reminder.revision, now)
        if (
            span is None
            or (reminder.id, context) in self._silences
            or self._snoozed(reminder, now)
            or self._rang(reminder, span, now)
        ):
            return
        self._alert(
            reminder, None, context, None, now, self._due(reminder, span, context_since, now)
        )

    def _alert(
        self,
        reminder: Reminder,
        evaluation_id: int | None,
        context: Context,
        d: float | None,
        now: int,
        due: int,
    ) -> None:
        alert = Alert(
            next(self._alert_ids),
            reminder.id,
            reminder.revision,
            evaluation_id,
            context,
            d,
            now,
            due,
        )
        self._counted.setdefault(reminder.id, []).append((alert.id, now))
        self._records.append(self._alerts.add(alert, now))
        self._alerts_changed = True

    # Units

    def _time(self, revision: Revision, now: int) -> _Time | None:
        """The window the revision's time is in at `now`; None out of its time."""
        times = self._times_of(revision)
        if times is None:
            # Without a time it may always ring; without a remainder either, never.
            return _ALWAYS if revision.remainder else None
        window = times.at(self._clock.local(now))
        if window is None:
            return None
        end = None if window.end is None else self._instant(window.end)
        return _Time(self._instant(window.start), end, self._instant(window.unit))

    def _times_of(self, revision: Revision) -> Times | None:
        if revision.schedule is None or revision.written_at is None:
            return None
        times = self._times.get(revision.id)
        if times is None:
            written_at = self._clock.local(revision.written_at)
            times = Times(revision.schedule, revision.perennial, written_at)
            self._times[revision.id] = times
        return times

    def _plan(self, reminder_ids: Iterable[int] | None = None, after: int | None = None) -> None:
        """While a context is stable, when the time of the given reminders, or of all of them,
        next starts or ends after now is a deadline: the context is judged again for them then."""
        if self._debounce.stable is None:
            self._edges = {}
            return
        if reminder_ids is None:
            self._edges = {}
            reminder_ids = list(self._reminders)
        now = self._clock.local(self._clock.now() if after is None else after)
        for reminder_id in reminder_ids:
            self._edges.pop(reminder_id, None)
            reminder = self._reminders.get(reminder_id)
            times = None if reminder is None else self._times_of(reminder.revision)
            if reminder is None or reminder.completed_at is not None or times is None:
                continue
            change = times.next_change(now)
            if change is not None:
                self._edges[reminder_id] = self._instant(change)

    def _rang(self, reminder: Reminder, span: _Time, now: int) -> bool:
        """It has rung in its unit, and no snooze with a time has ended since."""
        last = self._last_counted(reminder.id)
        if last is None or self._returning(reminder, now):
            return False
        if by_instance(reminder.revision):
            return span.unit is None or last >= span.unit
        stretches = self._stretches.get(reminder.id)
        return (
            stretches is not None and stretches.occasion is not None and last >= stretches.occasion
        )

    def _returning(self, reminder: Reminder, now: int) -> bool:
        """A snooze with a time is over, and the reminder has not rung since."""
        until = reminder.snoozed_until
        if until is None or until > now:
            return False
        last = self._last_counted(reminder.id)
        return last is None or last < until

    def _snoozed(self, reminder: Reminder, now: int) -> bool:
        return reminder.snoozed_until is not None and now < reminder.snoozed_until

    def _due(self, reminder: Reminder, span: _Time, context_since: int, now: int) -> int:
        """When the alert became due: the arrival of its context, the start of its time or the end
        of its snooze, whichever came last (ADR-0022)."""
        due = context_since if span.start is None else max(context_since, span.start)
        if reminder.snoozed_until is not None and self._returning(reminder, now):
            due = max(due, reminder.snoozed_until)
        return due

    def _last_counted(self, reminder_id: int) -> int | None:
        return max((at for _, at in self._counted.get(reminder_id, ())), default=None)

    def _open(self, reminder_id: int, start: int, until: int | None) -> None:
        """A true stretch begins at `start`, unless one is under way in the same window; with a new
        occasion if the last one ended at least the return pause before."""
        stretches = self._stretches.setdefault(reminder_id, _Stretches())
        if stretches.since is not None:
            if stretches.until is None or start < stretches.until:
                return
            self._close(reminder_id, start)  # its window ended while nobody looked
        if stretches.ended is None or start - stretches.ended >= self._return_pause:
            stretches.occasion = start
        stretches.since, stretches.until = start, until

    def _close(self, reminder_id: int, at: int) -> None:
        """The true stretch under way, if any, ends at `at`, or when its window ended."""
        stretches = self._stretches.get(reminder_id)
        if stretches is None or stretches.since is None:
            return
        stretches.ended = at if stretches.until is None else min(at, stretches.until)
        stretches.since = stretches.until = None

    # Helpers

    def _save(self, reminder: Reminder) -> None:
        self._reminders[reminder.id] = reminder
        self._records.append(reminder)
        self._reminders_changed = True

    def _write_statement(self, reminder_id: int) -> None:
        """The engine rewrites the remainder; a reminder with only a time never needs it."""
        reminder = self._reminders[reminder_id]
        if not reminder.revision.remainder:
            return
        try:
            statement = self._model.rewrite(reminder.revision.remainder)
            build = self._model.build()
        except ModelError:
            return  # it is tried again before the next evaluation
        revision = replace(reminder.revision, statement=statement, statement_build=build)
        self._save(replace(reminder, revision=revision))

    def _write_missing_statements(self) -> None:
        for reminder in list(self._reminders.values()):
            revision = reminder.revision
            if reminder.completed_at is None and revision.remainder and revision.statement is None:
                self._write_statement(reminder.id)

    def _forget(self, revision: Revision) -> None:
        """A revision no longer current: its scores and its windows go."""
        self._cache = {key: d for key, d in self._cache.items() if key[1] != revision.id}
        self._times.pop(revision.id, None)

    def _instant(self, at: datetime) -> int:
        return self._clock.instant(at.date(), at.time())

    def _answer(self, alert_id: int, answer: Answer, snooze: Snooze | None = None) -> Alert | None:
        alert = self._alerts.find(alert_id)
        if alert is None:
            return None
        now = self._clock.now()
        answered = replace(alert, answer=answer, answered_at=now, snooze=snooze)
        self._records.append(answered)
        self._records.extend(self._alerts.close(alert_id, now))
        self._alerts_changed = True
        return answered

    def _close_alerts(self, reminder_id: int, now: int) -> None:
        for alert in self._alerts.of(reminder_id):
            self._records.extend(self._alerts.close(alert.id, now))
            self._alerts_changed = True

    def _snooze_end(self, snooze: Snooze) -> int | None:
        """When a snooze with a time ends; Alla prossima volta has none."""
        now = self._clock.now()
        match snooze:
            case Snooze.NEXT_TIME:
                return None
            case Snooze.QUARTER_HOUR:
                return now + 15 * MINUTE_MS
            case Snooze.HOUR:
                return now + HOUR_MS
            case Snooze.TOMORROW:
                tomorrow = jiffin_day(self._clock.local(now)) + timedelta(days=1)
                return self._clock.instant(tomorrow, TOMORROW_AT)

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
