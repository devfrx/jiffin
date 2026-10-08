"""The rules of the product: reminders, their judging, and their alerts (ADR-0007, ADR-0014,
ADR-0021, ADR-0029).

The worker thread owns `Reminders` and gives it one event at a time: observations, deadlines
and the user's commands (ADR-0012). It keeps its state in memory, tells the interface about
the alerts and the reminders through two callbacks, and hands the records to save to whoever
calls `take_records`.

A reminder rings at most once per unit (`units`): the instance of its time, or the occasion. An
occasion starts with a true stretch, a stable context judged true while its time and its
situations hold, that begins at least the return pause after the previous one ended.

The situations (ADR-0028) come from observations of their own, which count once they have lasted
5 s (`situations`). A reminder rings while they hold, as it does while its time holds; without a
remainder it is never judged, and its unit is each stretch of its situations, or each end.

What the user says of a reminder in a place, an exact context, counts there until its text
changes: Not here keeps it quiet there, Remind here makes it true there, and Remind here near
the cut lowers its threshold (ADR-0029).

A pause from the tray is away until it ends (ADR-0024): nothing is in front for the reminders,
whatever the capture sees, and its end is a return. The situations are followed meanwhile.
"""

import itertools
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from enum import Enum, auto

from jiffin.core.alerts import Alerts, AlertsView
from jiffin.core.clock import Clock
from jiffin.core.context import Context, Observation
from jiffin.core.debounce import Debounce, EvaluationRequest
from jiffin.core.meanings import read
from jiffin.core.model import EngineBuild, Model, ModelError, Need
from jiffin.core.records import (
    Alert,
    Answer,
    CacheEntry,
    Candidate,
    ContextAnswer,
    Evaluation,
    Here,
    Left,
    NothingInFront,
    Outcome,
    Record,
    Reminder,
    ReminderDeleted,
    Revision,
    Snapshot,
    Snooze,
)
from jiffin.core.schedule import jiffin_day
from jiffin.core.situations import (
    Ends,
    Holds,
    Lasts,
    Situation,
    SituationObservation,
    Situations,
)
from jiffin.core.units import Times, by_instance

THRESHOLD = 0.97
"""d from which a reminder alerts: the starting value of ADR-0007, kept on the acceptance day of
0.2 (#106). It belongs to the engine's model and prompts, and is measured again when they
change (ADR-0017)."""
STEP_DOWN = 0.25
"""How far a reminder's threshold goes down for every two Remind here near the cut (ADR-0029)."""
MOST_DOWN = 0.5
"""How far below the threshold a reminder's own may go: learning adds alerts, which show, never
missed reminders, which would not (ADR-0029)."""
NEAR_CUT = 1.0
"""A Remind here is near the cut when its d is under the threshold by this much at most; one
farther away teaches only its place (ADR-0029)."""

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS

RETURN_PAUSE_MS = 2 * MINUTE_MS
"""How long the user must be away from a thing for its reminders to ring again when they come
back: the default of the settings, which allow 10 s to 2 hours (ADR-0021)."""
SHORTEST_RETURN_PAUSE_MS = 10_000
LONGEST_RETURN_PAUSE_MS = 2 * HOUR_MS

# Tomorrow is the next day at 08:00, local time: the usual meaning in mail and reminder apps,
# at the earlier of their usual hours (8 or 9), since the alert waits for its context anyway.
# Before 04:00 the night is not over, and "domani" is 08:00 of the same day, as in Anki.
TOMORROW_AT = time(8)


def tomorrow(clock: Clock, now: int) -> int:
    """08:00 of the next Jiffin day: Snooze's Tomorrow, and the pause's."""
    day = jiffin_day(clock.local(now)) + timedelta(days=1)
    return clock.instant(day, TOMORROW_AT)


def snooze_end(snooze: Snooze, clock: Clock, now: int) -> int | None:
    """When a Snooze answered at `now` ends; Next time has no end, only a next unit.
    The harness replays the snoozes of a log with it."""
    match snooze:
        case Snooze.NEXT_TIME:
            return None
        case Snooze.QUARTER_HOUR:
            return now + 15 * MINUTE_MS
        case Snooze.HOUR:
            return now + HOUR_MS
        case Snooze.TOMORROW:
            return tomorrow(clock, now)


class Pause(Enum):
    """Pause, in the tray icon's menu (ADR-0024)."""

    HOUR = auto()
    TOMORROW = auto()
    """Until `tomorrow`, as Snooze's Tomorrow."""


@dataclass(frozen=True, slots=True)
class Place:
    """A place where the user answered for a reminder, and the answer (ADR-0029)."""

    context: Context
    here: Here
    """Not here or Remind here: a withdrawn answer leaves no place."""


@dataclass(frozen=True, slots=True)
class ActiveReminder:
    """A reminder not completed yet, as the tray list shows it."""

    reminder: Reminder
    places: tuple[Place, ...] = ()
    """Where the user answered for it, until its text changes: the last answered first."""
    attentive: bool = False
    """Its threshold went down, with the engine build in use (ADR-0029)."""

    @property
    def silences(self) -> int:
        """How many contexts Not here has silenced it in."""
        return sum(place.here is Here.NO for place in self.places)


@dataclass(frozen=True, slots=True)
class HereReminder:
    """An active reminder on the card of Remind here (ADR-0029)."""

    reminder: Reminder
    quiet: Outcome | None
    """What else keeps it quiet in the place now, in the order of ADR-0021: its time, Not here,
    a snooze, or a ring in its unit; None when nothing does but the judge."""


@dataclass(frozen=True, slots=True)
class HereView:
    """What the card of Remind here shows (ADR-0029)."""

    place: Context | None
    """The last context stable for 5 s, still the place once it leaves the foreground, since
    Jiffin's windows are no place; None until the first."""
    reminders: tuple[HereReminder, ...] = ()
    """The active reminders: first those judged in the place, the closest to ringing first;
    then those not judged there, then those with only a time, the newest first."""


@dataclass(frozen=True, slots=True)
class RemindersView:
    """What the interface shows of the reminders."""

    active: tuple[ActiveReminder, ...]
    """Newest first."""
    paused_until: int | None = None
    """When the pause from the tray ends; None while there is none."""


@dataclass(frozen=True, slots=True)
class _Time:
    """The window a reminder's time is in, in UTC milliseconds."""

    start: int | None
    """None for a reminder without a time, which may always ring."""
    end: int | None
    unit: int | None
    """When the unit began, for a reminder that rings once per instance of its time."""


_ALWAYS = _Time(None, None, None)


def _thing_minutes(revision: Revision) -> int | None:
    """How long the thing the judge checks must have lasted: "quando sono su YouTube da più di 20
    minuti" (ADR-0028); None without such a duration."""
    return next(
        (
            term.minutes
            for term in revision.situations
            if isinstance(term, Lasts) and term.situation is None
        ),
        None,
    )


@dataclass(frozen=True, slots=True)
class _Said:
    """The answer that counts in a place, with the reminder's d there and the build of that d,
    when the cache knew them as it was given (ADR-0029)."""

    here: Here
    """Not here or Remind here."""
    d: float | None
    build: EngineBuild | None


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
        paused_until: int | None = None,
    ) -> None:
        """Start from what `store` saved, or from nothing; occasions start afresh (ADR-0021).

        Only the harness judges at another threshold, to choose the next one (ADR-0013). The
        return pause is in milliseconds. `paused_until` is the end of a pause kept in the
        settings, which goes on after a restart (ADR-0024).
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
        self._answers = {
            (answer.reminder_id, answer.context): _Said(answer.here, answer.d, answer.build)
            for answer in saved.answers
        }
        """The answer that counts in each place, by reminder and context: the last answered
        last."""
        self._cache = {(e.context, e.revision_id, e.build): e.d for e in saved.cache}
        self._counted = {
            reminder_id: [(alert_id, at)] for reminder_id, alert_id, at in saved.last_alerts
        }
        """The alerts that count in the units of each reminder, as (id, when): all but those
        answered Not here."""
        self._stretches: dict[int, _Stretches] = {}
        self._times: dict[int, Times] = {}
        """The windows of the revisions with a time, by revision."""
        self._situations = Situations()
        """Read again from the capture's observations: after a restart a situation's stretch
        starts from its state read at start (ADR-0028)."""
        for reminder in saved.reminders:
            self._situations.follow(reminder.revision.situations)
        self._snooze_deadlines = {
            reminder.id: reminder.snoozed_until
            for reminder in saved.reminders
            if reminder.completed_at is None and reminder.snoozed_until is not None
        }
        self._edges: dict[int, int] = {}
        """While a context is stable: when the time of each reminder starts or ends next."""
        self._paused_until = paused_until
        self._seen: Context | None = None
        """The context in front as the capture last saw it, paused or not: the pause's end
        brings it back."""
        self._front: Context | None = None
        """The last context in front for the reminders, no context aside: one of Jiffin's
        windows, which asks for Remind here, leaves the context before it in front."""
        self._place: Context | None = None
        """The last context stable for 5 s: "here", for Remind here."""
        self._nothing: NothingInFront | None = NothingInFront(clock.now(), startup=True)
        """The stretch with nothing in front under way: from the start, until the capture says."""
        self._records: list[Record] = [self._nothing]
        self._alerts_changed = bool(saved.unseen)
        self._reminders_changed = bool(saved.reminders) or paused_until is not None
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
        """When `poll` has something to do: a context becomes stable, a change of a situation
        counts, a snooze or the pause ends; or, while a context is stable, the time of a reminder
        starts or ends, or a duration of its situations is reached."""
        deadlines = [*self._snooze_deadlines.values(), *self._edges.values()]
        for deadline in (self._debounce.deadline, self._situations.deadline, self._paused_until):
            if deadline is not None:
                deadlines.append(deadline)
        return min(deadlines, default=None)

    @property
    def need(self) -> Need:
        """When the model will be asked next, as far as `core` knows: the client lets the engine
        sleep by it (ADR-0027). Soon when the context waiting to be stable has a judgement not in
        the cache, a revision without its statement included: it was never judged."""
        if self._nothing_in_front:
            return Need.NOTHING_IN_FRONT
        pending = self._debounce.pending
        if pending is None:
            return Need.NOT_NOW
        build = self._build()  # None before any engine started: no score is in the cache then
        missing = any(
            reminder.completed_at is None
            and reminder.revision.remainder
            and (pending.context, reminder.revision.id, build) not in self._cache
            for reminder in self._reminders.values()
        )
        return Need.SOON if missing else Need.NOT_NOW

    def observe(self, observation: Observation | SituationObservation) -> None:
        """What the capture saw: the window in front, or a situation (ADR-0028)."""
        self._catch_up(observation.at)
        if isinstance(observation, SituationObservation):
            self._situations.observe(observation)
            if observation.values is None:  # not read any more: it does not hold, at once
                self._changed([observation.situation], observation.at)
            self._records.extend(self._situations.take_records())
        else:
            self._seen = observation.context
            self._front_changed(observation.at)
            if self._paused_until is None:
                self._in_front(observation)
        self._publish()

    def poll(self) -> None:
        self._catch_up(self._clock.now())
        self._publish()

    def model_ready(self) -> None:
        """The model answers again, after a start or a restart (ADR-0011): the statements it
        missed are written, and the stable context, if any, is judged again. The cache spares
        what was judged already, and the unit a second alert. The build may be a new one, and
        the reminders' thresholds with it (ADR-0029)."""
        stable = self._debounce.stable
        if stable is None:
            self._write_missing_statements()
        else:
            self._evaluate(stable.context, stable.context_since, None)
            self._plan()
        self._reminders_changed = True
        self._publish()

    # The pause from the tray (ADR-0024)

    def pause(self, pause: Pause) -> int:
        """Pause: from now until the pause ends, the user is away. Return when it ends, for
        the settings to keep."""
        now = self._clock.now()
        self._catch_up(now)
        if self._paused_until is None:
            self._in_front(Observation(now, None))
        until = now + HOUR_MS if pause is Pause.HOUR else tomorrow(self._clock, now)
        self._paused_until = until
        self._front_changed(now)
        self._reminders_changed = True
        self._publish()
        return until

    def resume(self) -> None:
        """Resume: back now, as after any absence (ADR-0021)."""
        now = self._clock.now()
        self._catch_up(now)
        if self._paused_until is not None:
            self._end_pause(now)
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
            situations=reading.situations,
        )
        self._save(Reminder(reminder_id, now, revision))
        self._write_statement(reminder_id)
        self._plan([reminder_id])
        self._publish()
        return self._reminders[reminder_id]

    def edit(self, reminder_id: int, condition: str, action: str, perennial: bool = False) -> None:
        """A new revision. A new text withdraws what was said of it in every place (ADR-0029); a
        new condition is read again from now, and a new remainder waits for a new statement. The
        same condition keeps its time (ADR-0020)."""
        reminder = self._reminders.get(reminder_id)
        if reminder is None:
            return
        old = reminder.revision
        if (condition, action, perennial) == (old.condition, old.action, old.perennial):
            return
        now = self._clock.now()
        if (condition, action) != (old.condition, old.action):
            self._withdraw_all(reminder_id)  # before its scores go: the withdrawals carry its d
        self._forget(old)
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
                situations=reading.situations,
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
        self._answers = {key: said for key, said in self._answers.items() if key[0] != reminder_id}
        self._counted.pop(reminder_id, None)
        self._stretches.pop(reminder_id, None)
        self._snooze_deadlines.pop(reminder_id, None)
        self._edges.pop(reminder_id, None)
        self._close_alerts(reminder_id, self._clock.now())
        self._records.append(ReminderDeleted(reminder_id))
        self._reminders_changed = True
        self._publish()

    def done(self, alert_id: int) -> None:
        """Done: a one-off reminder is completed; a perennial one waits for its next unit."""
        alert = self._answer(alert_id, Answer.DONE)
        reminder = None if alert is None else self._reminders.get(alert.reminder_id)
        if reminder is not None and not reminder.revision.perennial:
            self.complete(reminder.id)
        self._publish()

    def not_here(self, alert_id: int) -> None:
        """Not here: the reminder keeps quiet in this exact context until its text changes, and the
        alert does not count, so it may ring elsewhere in the same unit (ADR-0021). It takes the
        place of a Remind here said there (ADR-0029)."""
        alert = self._answer(alert_id, Answer.NOT_HERE)
        if alert is not None and alert.reminder_id in self._reminders:
            self._say(alert.reminder_id, alert.context, Here.NO)
            counted = self._counted.get(alert.reminder_id, [])
            self._counted[alert.reminder_id] = [c for c in counted if c[0] != alert.id]
            stable = self._debounce.stable
            if stable is not None and stable.context == alert.context:
                self._close(alert.reminder_id, self._clock.now())
        self._publish()

    def remind_here(self, reminder_id: int, context: Context) -> None:
        """Remind here, "qui dovevi avvisarmi" (ADR-0029): the reminder is true in this exact
        context until its text changes, and takes the place of a Not here said there. If the
        context is still in front it rings at once, as asked: also when it rang already in its
        unit, was snoozed or out of its time. Otherwise the yes holds from the next time there.
        A reminder with only a time just rings: there is nothing to learn."""
        reminder = self._reminders.get(reminder_id)
        if reminder is None or reminder.completed_at is not None:
            return
        if reminder.revision.remainder:
            self._say(reminder_id, context, Here.YES)
        if self._paused_until is None and context == self._front:
            self._ring_requested(reminder, context)
        self._publish()

    def withdraw(self, reminder_id: int, context: Context) -> None:
        """Forget what was said of the reminder in one place, from the tray list: as if never
        answered there, and its threshold is what its other answers make it (ADR-0029)."""
        if (reminder_id, context) in self._answers:
            self._say(reminder_id, context, Here.WITHDRAWN)
        self._publish()

    def withdraw_all(self, reminder_id: int) -> None:
        """Forget everything the reminder learned, from the tray list (ADR-0029)."""
        self._withdraw_all(reminder_id)
        self._publish()

    def snooze(self, alert_id: int, snooze: Snooze) -> None:
        """Snooze. Next time waits for the next unit; the others keep the reminder quiet
        until they end, then it rings at the first chance, even within the same unit."""
        alert = self._answer(alert_id, Answer.SNOOZE, snooze)
        reminder = None if alert is None else self._reminders.get(alert.reminder_id)
        if reminder is not None:
            until = snooze_end(snooze, self._clock, self._clock.now())
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

    def here(self) -> HereView:
        """What the card of Remind here shows: the place, and the active reminders in their order
        there (ADR-0029)."""
        place = self._place
        if place is None:
            return HereView(None)
        now = self._clock.now()
        build = self._build()
        judged: list[tuple[float, Reminder]] = []
        unjudged: list[Reminder] = []
        on_time: list[Reminder] = []
        for reminder in self._active():
            if not reminder.revision.remainder:
                on_time.append(reminder)
                continue
            d = None if build is None else self._cache.get((place, reminder.revision.id, build))
            if d is None:
                unjudged.append(reminder)
            else:
                judged.append((d - self._threshold_of(reminder.id, build), reminder))
        judged.sort(key=lambda judgement: judgement[0], reverse=True)
        ordered = [reminder for _, reminder in judged] + unjudged + on_time
        return HereView(
            place,
            tuple(HereReminder(r, self._quiet(r, place, self._span(r, now), now)) for r in ordered),
        )

    # Judging

    def _catch_up(self, until: int) -> None:
        """Handle every deadline up to `until`, in order."""
        while (deadline := self.deadline) is not None and deadline <= until:
            if deadline == self._paused_until:
                self._end_pause(deadline)
                continue
            # Before a context that becomes stable at the same moment: it is judged with them.
            if deadline == self._situations.deadline:
                self._changed(self._situations.poll(deadline), deadline)
                self._records.extend(self._situations.take_records())
                continue
            if deadline == self._debounce.deadline:
                request = self._debounce.poll(deadline)
                if request is not None:
                    self._place = request.context
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

    def _changed(self, situations: list[Situation], at: int) -> None:
        """A change of situations is a deadline (ADR-0028): while a context is stable, it is
        judged again from the cache for the reminders on them, which ring if they may."""
        stable = self._debounce.stable
        if stable is None or not situations:
            return
        due = [
            reminder.id
            for reminder in self._reminders.values()
            if any(term.situation in situations for term in reminder.revision.situations)
        ]
        self._evaluate(stable.context, stable.context_since, due)
        self._plan(due, after=max(at, self._clock.now()))

    def _in_front(self, observation: Observation) -> None:
        """The context in front for the reminders: the capture's, or nothing while paused."""
        stable = self._debounce.stable
        if stable is not None and observation.context != stable.context:
            self._leave(stable, observation.at)
        self._debounce.observe(observation)
        if self._debounce.stable is None:
            self._edges = {}
        if observation.context is not None:
            self._front = observation.context

    @property
    def _nothing_in_front(self) -> bool:
        """No context in front, or the pause: nothing is judged, and the engine may sleep."""
        return self._paused_until is not None or self._seen is None

    def _front_changed(self, at: int) -> None:
        """Record when nothing comes in front for the reminders, and when something comes back:
        the harness checks that the engine slept (ADR-0031)."""
        if self._nothing_in_front and self._nothing is None:
            self._nothing = NothingInFront(at)
            self._records.append(self._nothing)
        elif not self._nothing_in_front and self._nothing is not None:
            self._records.append(replace(self._nothing, until=at))
            self._nothing = None

    def _end_pause(self, at: int) -> None:
        """The pause is over: what the capture sees is in front again."""
        self._paused_until = None
        self._front_changed(at)
        self._reminders_changed = True
        self._in_front(Observation(at, self._seen))

    def _leave(self, stable: EvaluationRequest, at: int) -> None:
        """The stable context left the foreground: its true stretches end."""
        for reminder_id in self._stretches:
            self._close(reminder_id, at)
        self._records.append(Left(stable.context, stable.context_since, at))

    def _evaluate(
        self, context: Context, context_since: int, reminder_ids: Iterable[int] | None
    ) -> None:
        """In a stable context, judge the reminders with a remainder and ring those without:
        all of them when the context has just become stable, or those whose snooze, time or
        situations have just changed."""
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
                self._ring_unjudged(reminder, context, context_since)
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
            span = self._span(reminder, now)
            here = self._here(reminder.id, context)
            true = here is Here.YES or d >= self._threshold_of(reminder.id, build)
            if true and isinstance(span, _Time) and here is not Here.NO:
                start = context_since if span.start is None else max(context_since, span.start)
                self._open(reminder.id, start, span.end)
            elif span is Outcome.OUTSIDE_SITUATION:
                self._close(reminder.id, self._stopped(reminder, now))
            else:
                self._close(reminder.id, now)
            outcome = self._outcome(reminder, context, true, span, now)
            candidates.append(Candidate(revision_id, d, revision_id not in fresh, outcome))
            if outcome is Outcome.ALERT and isinstance(span, _Time):
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
        self, reminder: Reminder, context: Context, true: bool, span: _Time | Outcome, now: int
    ) -> Outcome:
        """`true`: at or above its threshold, or Remind here was said there (ADR-0029)."""
        if not true:
            return Outcome.BELOW_THRESHOLD
        quiet = self._quiet(reminder, context, span, now)
        return Outcome.ALERT if quiet is None else quiet

    def _quiet(
        self, reminder: Reminder, context: Context, span: _Time | Outcome, now: int
    ) -> Outcome | None:
        """What keeps the reminder quiet in the context but the judge, in the order of ADR-0021
        and ADR-0028; None when nothing does."""
        if isinstance(span, Outcome):
            return span
        if _thing_minutes(reminder.revision) is not None:
            reached = self._thing_reached(reminder)
            if reached is None or reached > now:
                return Outcome.OUTSIDE_SITUATION
        if self._here(reminder.id, context) is Here.NO:
            return Outcome.SILENCED
        if self._snoozed(reminder, now):
            return Outcome.SNOOZED
        if self._rang(reminder, span, now):
            return Outcome.SAME_OCCASION
        return None

    def _ring_unjudged(self, reminder: Reminder, context: Context, context_since: int) -> None:
        """A reminder without a remainder, with only a time or situations, rings in any stable
        context: the user is there."""
        now = self._clock.now()
        span = self._span(reminder, now)
        if not isinstance(span, _Time) or self._quiet(reminder, context, span, now) is not None:
            return
        self._alert(
            reminder, None, context, None, now, self._due(reminder, span, context_since, now)
        )

    def _ring_requested(self, reminder: Reminder, context: Context) -> None:
        """The alert asked for with Remind here: it counts in the unit, and it is never the
        judge's (ADR-0029). A true stretch starts with it, so that coming back to the context
        rings no second alert in the same occasion (ADR-0021); it ends at once unless the
        context is the stable one, since the card that asks is one of Jiffin's windows."""
        now = self._clock.now()
        span = self._span(reminder, now)
        if isinstance(span, _Time) and reminder.revision.remainder:
            self._open(reminder.id, now, span.end)
            stable = self._debounce.stable
            if stable is None or stable.context != context:
                self._close(reminder.id, now)
        d, _ = self._known(reminder, context)
        self._alert(reminder, None, context, d, now, now, requested=True)

    def _alert(
        self,
        reminder: Reminder,
        evaluation_id: int | None,
        context: Context,
        d: float | None,
        now: int,
        due: int,
        requested: bool = False,
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
            requested=requested,
        )
        self._counted.setdefault(reminder.id, []).append((alert.id, now))
        self._records.append(self._alerts.add(alert, now))
        self._alerts_changed = True

    # Answers per place (ADR-0029)

    def _say(self, reminder_id: int, context: Context, here: Here) -> None:
        """Answer in a place, or withdraw the answer, which leaves no place: the last one counts.
        Each is recorded with the reminder's d there, when the cache knows it."""
        d, build = self._known(self._reminders[reminder_id], context)
        self._answers.pop((reminder_id, context), None)  # an answer again is the last answered
        if here is not Here.WITHDRAWN:
            self._answers[(reminder_id, context)] = _Said(here, d, build)
        self._records.append(ContextAnswer(reminder_id, context, here, d, build, self._clock.now()))
        self._reminders_changed = True

    def _withdraw_all(self, reminder_id: int) -> None:
        for answered, context in list(self._answers):
            if answered == reminder_id:
                self._say(reminder_id, context, Here.WITHDRAWN)

    def _here(self, reminder_id: int, context: Context) -> Here | None:
        """What counts of what the user said of the reminder in the context; None if nothing."""
        said = self._answers.get((reminder_id, context))
        return None if said is None else said.here

    def _threshold_of(self, reminder_id: int, build: EngineBuild | None) -> float:
        """The reminder's threshold: `STEP_DOWN` under the threshold for every two Remind here
        near the cut said with the build in use, `MOST_DOWN` under it at most. Computed again
        each time from the answers, never kept, so a withdrawal puts it back exactly."""
        near = sum(
            said.here is Here.YES
            and said.build == build
            and said.d is not None
            and self._threshold - NEAR_CUT <= said.d < self._threshold
            for (answered, _), said in self._answers.items()
            if answered == reminder_id
        )
        return self._threshold - min(MOST_DOWN, STEP_DOWN * (near // 2))

    def _known(
        self, reminder: Reminder, context: Context
    ) -> tuple[float | None, EngineBuild | None]:
        """The reminder's d in the context, with its build, when the cache holds a score of its
        revision there from the build in use; else None and None."""
        build = self._build()
        d = None if build is None else self._cache.get((context, reminder.revision.id, build))
        return (None, None) if d is None else (d, build)

    # Units

    def _time(self, revision: Revision, now: int) -> _Time | None:
        """The window the revision's time is in at `now`; None out of its time."""
        times = self._times_of(revision)
        if times is None:
            # Without a time it may always ring; without a remainder or situations either, never.
            return _ALWAYS if revision.remainder or revision.situations else None
        window = times.at(self._clock.local(now))
        if window is None:
            return None
        end = None if window.end is None else self._instant(window.end)
        return _Time(self._instant(window.start), end, self._instant(window.unit))

    def _span(self, reminder: Reminder, now: int) -> _Time | Outcome:
        """When the reminder may ring now: the window of its time, from when its situations hold
        together, with the start of its unit (ADR-0028); else what keeps it out, `OUTSIDE_TIME`
        or `OUTSIDE_SITUATION`. A duration of the thing the judge checks counts in `_quiet`, once
        its occasion is known."""
        revision = reminder.revision
        span = self._time(revision, now)
        if span is None:
            return Outcome.OUTSIDE_TIME
        starts: list[int] = []
        end: int | None = None
        for term in revision.situations:
            match term:
                case Ends():
                    end = self._end(reminder, term, span, now)
                    if end is None:
                        return Outcome.OUTSIDE_SITUATION
                    starts.append(end)
                case Lasts(minutes, situation, value) if situation is not None:
                    since = self._situations.since(situation, value)
                    if since is None or since + minutes * MINUTE_MS > now:
                        return Outcome.OUTSIDE_SITUATION
                    starts.append(since + minutes * MINUTE_MS)
                case Lasts():
                    pass
                case Holds(situation, value):
                    since = self._situations.since(situation, value)
                    if since is None:
                        return Outcome.OUTSIDE_SITUATION
                    starts.append(since)
        if not starts:
            return span
        start = max(starts) if span.start is None else max(span.start, *starts)
        if by_instance(revision):
            unit = span.unit
        elif end is not None:  # each end
            unit = end
        elif not revision.remainder:  # each stretch of the situations, within its time
            unit = start
        else:  # the occasion
            unit = None
        return _Time(start, span.end, unit)

    def _end(self, reminder: Reminder, term: Ends, span: _Time, now: int) -> int | None:
        """The end the reminder may ring for now, as a moment (ADR-0028): the last one, after the
        condition was written and within the window of its time under way. One-off, it waits
        until the next end, so it is never lost; with "Ogni volta", until 04:00 of its Jiffin
        day."""
        ended = self._situations.ended(term.situation, term.value)
        written_at = reminder.revision.written_at
        if ended is None or (written_at is not None and ended < written_at):
            return None
        if span.start is not None and ended < span.start:
            return None
        day = jiffin_day(self._clock.local(ended))
        if reminder.revision.perennial and day != jiffin_day(self._clock.local(now)):
            return None
        return ended

    def _thing_reached(self, reminder: Reminder) -> int | None:
        """When the thing the judge checks will have lasted as long as the condition wants, from
        the start of the occasion under way (ADR-0028); None while no true stretch is under
        way, or without such a duration."""
        minutes = _thing_minutes(reminder.revision)
        stretches = self._stretches.get(reminder.id)
        if minutes is None or stretches is None or stretches.since is None:
            return None
        if stretches.occasion is None:
            return None
        return stretches.occasion + minutes * MINUTE_MS

    def _stopped(self, reminder: Reminder, now: int) -> int:
        """When the situations of the reminder stopped holding: its true stretch ends then, not
        when the change counted, 5 s later."""
        ends = [
            ended
            for term in reminder.revision.situations
            if not isinstance(term, Ends) and term.situation is not None
            if (ended := self._situations.ended(term.situation, term.value)) is not None
            and ended <= now
        ]
        return max(ends, default=now)

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
        next starts or ends after now is a deadline, and so is a duration of their situations
        reached: the context is judged again for them then."""
        if self._debounce.stable is None:
            self._edges = {}
            return
        if reminder_ids is None:
            self._edges = {}
            reminder_ids = list(self._reminders)
        now = self._clock.now() if after is None else after
        for reminder_id in reminder_ids:
            self._edges.pop(reminder_id, None)
            reminder = self._reminders.get(reminder_id)
            if reminder is None or reminder.completed_at is not None:
                continue
            times = self._times_of(reminder.revision)
            change = None if times is None else times.next_change(self._clock.local(now))
            changes = [*self._reached(reminder, now)]
            if change is not None:
                changes.append(self._instant(change))
            if changes:
                self._edges[reminder_id] = min(changes)

    def _reached(self, reminder: Reminder, now: int) -> list[int]:
        """When the durations of the reminder's situations, and of its thing, will be reached
        after `now` (ADR-0028)."""
        found = []
        for term in reminder.revision.situations:
            if isinstance(term, Lasts):
                if term.situation is None:
                    reached = self._thing_reached(reminder)
                else:
                    since = self._situations.since(term.situation, term.value)
                    reached = None if since is None else since + term.minutes * MINUTE_MS
                if reached is not None and reached > now:
                    found.append(reached)
        return found

    def _rang(self, reminder: Reminder, span: _Time, now: int) -> bool:
        """It has rung in its unit, and no snooze with a time has ended since. The unit is the
        occasion, unless `span` gives where it starts: an instance of its time, a stretch of its
        situations or an end (ADR-0028)."""
        last = self._last_counted(reminder.id)
        if last is None or self._returning(reminder, now):
            return False
        revision = reminder.revision
        ends = any(isinstance(term, Ends) for term in revision.situations)
        if by_instance(revision) or ends or not revision.remainder:
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
        """When the alert became due: the arrival of its context, the start of its time, when its
        situations made it due (the start of a stretch, an end, a duration reached) or the end of
        its snooze, whichever came last (ADR-0022, ADR-0028)."""
        due = context_since if span.start is None else max(context_since, span.start)
        reached = self._thing_reached(reminder)
        if reached is not None:
            due = max(due, reached)
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
        """The true stretch under way, if any, ends at `at`, or when its window ended; never
        before it began."""
        stretches = self._stretches.get(reminder_id)
        if stretches is None or stretches.since is None:
            return
        ended = at if stretches.until is None else min(at, stretches.until)
        stretches.ended = max(ended, stretches.since)
        stretches.since = stretches.until = None

    # Helpers

    def _save(self, reminder: Reminder) -> None:
        self._reminders[reminder.id] = reminder
        self._records.append(reminder)
        self._situations.follow(reminder.revision.situations)
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

    def _build(self) -> EngineBuild | None:
        """The engine build in use; None before any engine started."""
        try:
            return self._model.build()
        except ModelError:
            return None

    def _active(self) -> list[Reminder]:
        """The reminders not completed, the newest first: ids grow with each new reminder."""
        return sorted(
            (reminder for reminder in self._reminders.values() if reminder.completed_at is None),
            key=lambda reminder: reminder.id,
            reverse=True,
        )

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

    def _publish(self) -> None:
        if self._alerts_changed:
            self._alerts_changed = False
            self._on_alerts(self._alerts.view())
        if self._reminders_changed:
            self._reminders_changed = False
            self._on_reminders(self._reminders_view())

    def _reminders_view(self) -> RemindersView:
        build = self._build()
        places: dict[int, list[Place]] = {}
        # The last answered first.
        for (reminder_id, context), said in reversed(self._answers.items()):
            places.setdefault(reminder_id, []).append(Place(context, said.here))
        return RemindersView(
            tuple(
                ActiveReminder(
                    reminder,
                    tuple(places.get(reminder.id, ())),
                    self._threshold_of(reminder.id, build) < self._threshold,
                )
                for reminder in self._active()
            ),
            self._paused_until,
        )
