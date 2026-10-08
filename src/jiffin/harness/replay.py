"""`replay`: a day of the log again through `core`, on simulated time (ADR-0017).

The day's evaluated contexts come back as observations, each at the moment it came to the
foreground, and the situations as the capture observed them, and the clock moves to each
deadline in turn, so every evaluation happens at its exact time (pipeline.md). `core` starts
from the state the log had when the day began; the reminders come, change and go as the log
recorded them; the owner answers the alerts the log also had, after the same time on screen,
says Remind here and withdraws answers when the log says, and every other alert leaves the
screen after 10 s. What changes is one thing at a time: the threshold, the reminders or the
engine. Replayed at its own threshold with its own scores, a day gives its alerts back, those of
the reminders without a remainder too, which ring without being judged. From version 0.2 on,
`core` judges with the return pause each evaluation recorded; a log of 0.1 is replayed with the
default one.

What the log does not keep is inferred from what it does:
- when a context left, from version 0.2 on; before, a context seen twice in a row was left in
  between: a moment with no context separates them;
- a reminder's new text starts when it was made, from version 0.2 on; before, when the context
  of its first evaluation came to the foreground;
- which Snooze answered an alert, from version 0.2 on; before, from when the reminder was last
  judged snoozed and first judged free after it;
- when a situation stopped being read, from the stretches of the situations that always have a
  value while read: one of them that ends with no other starting then.
"""

import heapq
import itertools
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, tzinfo

from jiffin.core.clock import Clock, SimulatedClock, SystemClock
from jiffin.core.context import Context, Observation
from jiffin.core.model import EngineBuild, Model, ModelError
from jiffin.core.records import (
    Alert,
    Answer,
    ContextAnswer,
    Evaluation,
    Here,
    LastIds,
    Left,
    Outcome,
    Record,
    Reminder,
    Revision,
    Snapshot,
    Snooze,
)
from jiffin.core.reminders import THRESHOLD, Reminders, snooze_end
from jiffin.core.situations import Situation, SituationObservation, SituationStretch
from jiffin.harness.day import Day, bounds
from jiffin.harness.errors import HarnessError
from jiffin.harness.truth import ALWAYS_VALUED, unread
from jiffin.store.store import Log

VANISH_MS = 10_000
"""The interface's timer: an unanswered alert leaves the screen after 10 s (lifecycles.md)."""

type Command = Callable[[Reminders], None]


class Recorded:
    """The engine as the log recorded it, and no engine at all: d by context and statement,
    and the failures where the log has them.

    A pair the day never judged has no score: the evaluation that needs it fails, as it would
    have with the engine down.
    """

    def __init__(self, log: Log, day: Day, clock: Clock) -> None:
        builds = [evaluation.build for evaluation in day.evaluations if evaluation.build]
        if not builds:
            raise HarnessError("the engine answered no evaluation of that day")
        self._build = builds[-1]
        self._clock = clock
        self._failed = {evaluation.at for evaluation in day.evaluations if evaluation.failed}
        self._statements = {
            revision.remainder: revision.statement
            for revision in log.revisions.values()
            if revision.statement is not None
        }
        self._d: dict[tuple[Context, str | None], float] = {
            (evaluation.context, day.revisions[candidate.revision_id].statement): candidate.d
            for evaluation in day.evaluations
            for candidate in evaluation.candidates
        }

    def build(self) -> EngineBuild:
        return self._build

    def rewrite(self, condition: str) -> str:
        statement = self._statements.get(condition)
        if statement is None:
            raise ModelError("the log holds no statement for that remainder")
        return statement

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        if self._clock.now() in self._failed:
            raise ModelError("the engine failed here, as the log recorded")
        missing = [text for text in statements.values() if (context, text) not in self._d]
        if missing:
            raise ModelError(f"the day never judged {len(missing)} of those statements there")
        return {key: self._d[(context, text)] for key, text in statements.items()}


@dataclass(order=True)
class _Event:
    at: int
    order: int
    command: Command = field(compare=False)


class Timeline:
    """Commands for `core` at given times, run in order with its deadlines on a simulated clock.

    `on_shown` sees each alert once, when it first reaches the screen, and may add commands.
    """

    def __init__(
        self,
        core: Reminders,
        clock: SimulatedClock,
        on_shown: Callable[["Timeline", Alert], None],
    ) -> None:
        self.core = core
        self._clock = clock
        self._on_shown = on_shown
        self._queue: list[_Event] = []
        self._order = itertools.count()
        self._shown: set[int] = set()
        self.evaluations: dict[int, Evaluation] = {}
        self.records: list[Record] = []

    def at(self, time: int, command: Command) -> None:
        when = max(time, self._clock.now())
        heapq.heappush(self._queue, _Event(when, next(self._order), command))

    def run(self, until: int) -> None:
        """Every command, and every deadline of `core` up to `until`."""
        while True:
            deadline = self.core.deadline
            due = self._queue[0].at if self._queue else None
            if deadline is not None and deadline <= until and (due is None or deadline <= due):
                self._move(deadline)
                self.core.poll()
            elif self._queue:
                event = heapq.heappop(self._queue)
                self._move(event.at)
                event.command(self.core)
            else:
                return
            self._collect()

    def _move(self, time: int) -> None:
        """Forward to `time`: a deadline already past, as the end of a Snooze from before the
        day, is handled at once."""
        self._clock.advance(max(time - self._clock.now(), 0))

    def _collect(self) -> None:
        for record in self.core.take_records():
            self.records.append(record)
            if isinstance(record, Evaluation):
                self.evaluations[record.id] = record
            elif (
                isinstance(record, Alert)
                and record.shown_at is not None
                and record.id not in self._shown
            ):
                self._shown.add(record.id)
                self._on_shown(self, record)


def passive(timeline: Timeline, alert: Alert) -> None:
    """Nobody answers: the alert leaves the screen after 10 s."""
    if alert.shown_at is not None:
        timeline.at(alert.shown_at + VANISH_MS, lambda core: core.vanished(alert.id))


def observations(evaluations: Iterable[Evaluation], left: Iterable[Left] = ()) -> list[Observation]:
    """Each evaluated context when it came to the foreground, once, and when it left, where the
    log says: what came in between was never stable, so it counts as no context."""
    until = {(stretch.since, stretch.context): stretch.until for stretch in left}
    found: list[Observation] = []
    seen: set[tuple[int, Context]] = set()
    previous: Context | None = None
    for evaluation in sorted(evaluations, key=lambda e: (e.context_since, e.at)):
        mark = (evaluation.context_since, evaluation.context)
        if mark in seen:  # judged again while it stayed: a snooze or a time ended there
            continue
        seen.add(mark)
        if evaluation.context == previous:
            found.append(Observation(evaluation.context_since - 1, None))
        found.append(Observation(evaluation.context_since, evaluation.context))
        previous = evaluation.context
        if mark in until:
            found.append(Observation(until[mark], None))
            previous = None
    return found


def situation_observations(stretches: Iterable[SituationStretch]) -> list[SituationObservation]:
    """What the capture observed of the situations, from the stretches they gave: at each start
    and end, the values of the situation then (ADR-0028). `core` counts the 5 s again, so they
    give the same stretches. A situation not read any more ends no stretch as an end: it is not
    read where one that always has a value ended with no other starting then, as at the app's
    close."""
    kinds: dict[Situation, list[SituationStretch]] = {}
    for stretch in stretches:
        kinds.setdefault(stretch.situation, []).append(stretch)
    not_read = unread(stretch for found in kinds.values() for stretch in found)
    seen: list[SituationObservation] = []
    for kind, found in kinds.items():
        for at in sorted({s.since for s in found} | {s.until for s in found}):
            values = frozenset(s.value for s in found if s.since <= at < s.until)
            read = bool(values) or (kind not in ALWAYS_VALUED and at not in not_read)
            seen.append(SituationObservation(at, kind, values if read else None))
    return sorted(seen, key=lambda observation: (observation.at, observation.situation))


def new_reminder(condition: str, action: str) -> Command:
    def create(core: Reminders) -> None:
        core.create(condition, action)

    return create


def observe(observation: Observation | SituationObservation) -> Command:
    return lambda core: core.observe(observation)


def return_pause(milliseconds: int) -> Command:
    def change(core: Reminders) -> None:
        core.return_pause = milliseconds

    return change


class Replay:
    """One day of the log through `core` again, with one thing changed.

    Without `model` the scores are those the log keeps; with one, the engine judges and
    `rewrite` has it write every statement again. `extra` adds reminders, as (condition,
    action), from the start of the day; `answers` replays the owner's answers, to the alerts and
    per place. The times of the reminders are read in `zone`: this machine's by default, where
    the app wrote its log.
    """

    def __init__(
        self,
        log: Log,
        day: Day,
        model: Model | None = None,
        *,
        threshold: float = THRESHOLD,
        rewrite: bool = False,
        extra: Sequence[tuple[str, str]] = (),
        answers: bool = True,
        zone: tzinfo | None = None,
    ) -> None:
        if not day.evaluations:
            raise HarnessError("the day has no evaluation")
        self._log = log
        self._day = day
        self._model = model
        self._threshold = threshold
        self._rewrite = rewrite
        self._extra = extra
        self._answers = answers
        self._seen = observations(day.evaluations, log.left)
        self._begin = self._seen[0].at - 1
        self._until = max(
            [evaluation.at for evaluation in day.evaluations]
            + [alert.created_at for alert in (*day.alerts, *day.requested)]
        )
        """The last evaluation, or a later alert of a reminder without a remainder, which rings at
        a deadline without one."""
        self._situations = situation_observations(self._stretches())
        self._made_known = any(
            evaluation.return_pause is not None for evaluation in day.evaluations
        )
        """From version 0.2 on the log records when each revision was made and which Snooze
        answered an alert; it judges with a return pause, which 0.1 did not have."""
        self._zone = zone or SystemClock().local(self._begin).tzinfo or UTC
        self._calendar = SimulatedClock(self._begin, self._zone)
        """For local days and hours only: it never moves."""
        self._ids: dict[int, int] = {}
        """The replay's ids of the reminders the day created, by the log's ids."""
        self._recorded = {
            (a.reminder_id, a.context, a.created_at): a
            for a in (*day.alerts, *day.requested)
            if a.answer is not None and a.shown_at is not None and a.answered_at is not None
        }
        """The answered alerts, by reminder, context and when they were made: a reminder may
        alert twice in one stable context, before and after a snooze."""
        self._unseen = self._unseen_at_start()

    def run(self) -> Day:
        """The day replayed; each run starts over."""
        self._ids = {}
        clock = SimulatedClock(self._begin, self._zone)
        start = self._start()
        model = self._model or Recorded(self._log, self._day, clock)
        core = Reminders(
            model, clock, lambda view: None, lambda view: None, start, threshold=self._threshold
        )
        timeline = Timeline(core, clock, self._answer if self._answers else passive)
        for condition, action in self._extra:
            timeline.at(self._begin, new_reminder(condition, action))
        for when, command in self._commands():
            timeline.at(when, command)
        timeline.run(self._until)
        return self._result(timeline, start)

    # Where core starts

    def _start(self) -> Snapshot:
        reminders = []
        for reminder in self._before():
            first = self._revisions(reminder)[0][1]
            snoozed = self._snoozed_at_start(reminder)
            reminders.append(
                replace(reminder, revision=first, completed_at=None, snoozed_until=snoozed)
            )
        return Snapshot(
            reminders=tuple(reminders),
            answers=self._answers_at_start(),
            last_alerts=self._last_alerts(),
            unseen=tuple(
                replace(alert, answer=None, answered_at=None, snooze=None) for alert in self._unseen
            ),
            last_ids=LastIds(
                reminder=max((r.id for r in self._log.reminders), default=0),
                revision=max(self._log.revisions, default=0),
                evaluation=max((e.id for e in self._log.evaluations), default=0),
                alert=max((a.id for a in self._log.alerts), default=0),
            ),
        )

    def _before(self) -> list[Reminder]:
        """The reminders active when the day began."""
        return [
            reminder
            for reminder in self._log.reminders
            if reminder.created_at < self._begin and not self._gone(reminder)
        ]

    def _gone(self, reminder: Reminder) -> bool:
        return reminder.completed_at is not None and reminder.completed_at < self._begin

    def _stretches(self) -> list[SituationStretch]:
        """The stretches of the situations from the start of the app's run under way when the
        day began, which read them all from its start, to the day's last moment replayed."""
        runs = [s.since for s in self._log.nothing_in_front if s.startup and s.since <= self._begin]
        start = max(runs, default=None)
        return [
            stretch
            for stretch in self._log.situations
            if (start is None or stretch.since >= start) and stretch.since <= self._until
        ]

    def _unseen_at_start(self) -> list[Alert]:
        """The alerts on the tray list when the day began, as the log has them: of each reminder
        active then, its last alert before the day, if it was shown and not answered by then
        (lifecycles.md). The newest first."""
        active = {reminder.id for reminder in self._before()}
        last: dict[int, Alert] = {}
        for alert in self._log.alerts:  # the oldest first
            if alert.created_at < self._begin and alert.reminder_id in active:
                last[alert.reminder_id] = alert
        return sorted(
            (a for a in last.values() if a.shown_at is not None and not self._answered_before(a)),
            key=lambda alert: alert.created_at,
            reverse=True,
        )

    def _answered_before(self, alert: Alert) -> bool:
        return alert.answered_at is not None and alert.answered_at < self._begin

    def _revisions(self, reminder: Reminder) -> list[tuple[int, Revision]]:
        """Its revisions over the day, each with when it took effect, the one in force when the
        day began first; the current one if the log tells nothing."""
        chain = self._made(reminder) if self._made_known else self._judged_in_turn(reminder)
        if not chain:
            chain = [(self._begin, reminder.revision)]
        if self._rewrite:
            chain = [(when, replace(r, statement=None, statement_build=None)) for when, r in chain]
        return chain

    def _made(self, reminder: Reminder) -> list[tuple[int, Revision]]:
        """From version 0.2 on: the last revision made before the day, then each made during
        it, when it was made, also those of a reminder with only a time, never judged. A
        revision of 0.1 without that time was made before 0.2, so before the day."""
        chain: list[tuple[int, Revision]] = []
        mine = (r for r in self._log.revisions.values() if r.reminder_id == reminder.id)
        for revision in sorted(mine, key=lambda r: r.number):
            made = revision.created_at
            if made is None or made < self._begin:
                chain = [(self._begin, revision)]
            elif made <= self._until:
                chain.append((made, revision))
        return chain

    def _judged_in_turn(self, reminder: Reminder) -> list[tuple[int, Revision]]:
        """In version 0.1: its revisions in the order the day judged them, each with when the
        context of its first evaluation came to the foreground."""
        chain: list[tuple[int, Revision]] = []
        for evaluation in sorted(self._day.evaluations, key=lambda e: e.at):
            for candidate in evaluation.candidates:
                revision = self._day.revisions[candidate.revision_id]
                known = any(revision.id == earlier.id for _, earlier in chain)
                if revision.reminder_id == reminder.id and not known:
                    chain.append((evaluation.context_since, revision))
        return chain

    def _judged(self, reminder_id: int, after: int) -> list[tuple[int, Outcome]]:
        """When the day judged a reminder after a moment, and how."""
        return [
            (evaluation.at, candidate.outcome)
            for evaluation in sorted(self._day.evaluations, key=lambda e: e.at)
            if evaluation.at > after
            for candidate in evaluation.candidates
            if self._day.revisions[candidate.revision_id].reminder_id == reminder_id
        ]

    def _snoozed_at_start(self, reminder: Reminder) -> int | None:
        """A Snooze from before the day, even one over already: a reminder that has not rung
        since comes back within its unit (ADR-0021). From its recorded kind, from version 0.2
        on; before, until the reminder was first judged free."""
        answered = [
            alert
            for alert in self._log.alerts
            if alert.reminder_id == reminder.id
            and alert.answer is Answer.SNOOZE
            and alert.answered_at is not None
            and alert.answered_at < self._begin
        ]
        last = max(answered, key=lambda alert: alert.answered_at or 0, default=None)
        if last is not None and last.snooze is not None and last.answered_at is not None:
            return snooze_end(last.snooze, self._calendar, last.answered_at)
        judged = self._judged(reminder.id, self._begin)
        if not judged or judged[0][1] is not Outcome.SNOOZED:
            return None
        return next((at for at, outcome in judged if outcome is not Outcome.SNOOZED), None)

    def _answers_at_start(self) -> tuple[ContextAnswer, ...]:
        """What counted in each place when the day began: the last answer said there before it,
        unless it was withdrawn (ADR-0029). The answers of the day come again at their time."""
        said: dict[tuple[int, Context], ContextAnswer] = {}
        for answer in self._log.answers:
            if answer.at < self._begin:
                said.pop((answer.reminder_id, answer.context), None)  # the last answered last
                said[(answer.reminder_id, answer.context)] = answer
        return tuple(answer for answer in said.values() if answer.here is not Here.WITHDRAWN)

    def _last_alerts(self) -> tuple[tuple[int, int, int], ...]:
        """For each reminder, its last alert before the day that counts: not answered Not here by
        then. One answered Not here during the day stops counting then, as `core` hears it."""
        last: dict[int, Alert] = {}
        for alert in self._log.alerts:
            silenced = alert.answer is Answer.NOT_HERE and self._answered_before(alert)
            if alert.created_at < self._begin and not silenced:
                kept = last.get(alert.reminder_id)
                if kept is None or alert.created_at >= kept.created_at:
                    last[alert.reminder_id] = alert
        return tuple((rid, alert.id, alert.created_at) for rid, alert in sorted(last.items()))

    # What happens during the day

    def _commands(self) -> list[tuple[int, Command]]:
        commands = self._pauses()
        for reminder in self._log.reminders:
            if self._gone(reminder) or reminder.created_at > self._until:
                continue
            chain = self._revisions(reminder)
            if reminder.created_at >= self._begin:
                commands.append((reminder.created_at, self._create(reminder.id, chain[0][1])))
            for since, revision in chain[1:]:
                commands.append((since, self._edit(reminder.id, revision)))
            if reminder.completed_at is not None:
                # A millisecond late, so that a replayed Done completes it first, as it did.
                commands.append((reminder.completed_at + 1, self._complete(reminder.id)))
        commands += [(observation.at, observe(observation)) for observation in self._situations]
        commands += [(observation.at, observe(observation)) for observation in self._seen]
        if self._answers:
            commands += self._said()
        return commands

    def _said(self) -> list[tuple[int, Command]]:
        """What the owner said during the day that no alert of the day brings back: Remind here
        and the withdrawals per place (ADR-0029), and the answers to alerts from before the day,
        on the tray list. A Not here comes with its alert."""
        commands: list[tuple[int, Command]] = []
        for answer in self._log.answers:
            if not self._begin <= answer.at <= self._until:
                continue
            if answer.here is Here.YES:
                commands.append((answer.at, self._remind_here(answer.reminder_id, answer.context)))
            elif answer.here is Here.WITHDRAWN:
                commands.append((answer.at, self._withdraw(answer.reminder_id, answer.context)))
        for alert in self._unseen:
            if alert.answered_at is not None and alert.answered_at <= self._until:
                commands.append((alert.answered_at, self._reply(alert.id, alert)))
        return commands

    def _pauses(self) -> list[tuple[int, Command]]:
        """The return pauses the day was judged with, as its evaluations recorded them. A pause
        counts only when a context is judged, so a change from the settings is in force right
        after the last evaluation judged with the one before."""
        commands: list[tuple[int, Command]] = []
        before, since = None, self._begin
        for evaluation in sorted(self._day.evaluations, key=lambda e: e.at):
            pause = evaluation.return_pause
            if pause is not None and pause != before:
                commands.append((since, return_pause(pause)))
                before = pause
            since = evaluation.at
        return commands

    def _create(self, log_id: int, revision: Revision) -> Command:
        def create(core: Reminders) -> None:
            made = core.create(revision.condition, revision.action, revision.perennial)
            self._ids[log_id] = made.id

        return create

    def _edit(self, log_id: int, revision: Revision) -> Command:
        def edit(core: Reminders) -> None:
            reminder_id = self._ids.get(log_id, log_id)
            core.edit(reminder_id, revision.condition, revision.action, revision.perennial)

        return edit

    def _complete(self, log_id: int) -> Command:
        return lambda core: core.complete(self._ids.get(log_id, log_id))

    def _remind_here(self, log_id: int, context: Context) -> Command:
        return lambda core: core.remind_here(self._ids.get(log_id, log_id), context)

    def _withdraw(self, log_id: int, context: Context) -> Command:
        return lambda core: core.withdraw(self._ids.get(log_id, log_id), context)

    # The owner

    def _answer(self, timeline: Timeline, alert: Alert) -> None:
        """The answer the log recorded for the same alert, after the same time on screen."""
        passive(timeline, alert)
        back = {replayed: original for original, replayed in self._ids.items()}
        original = self._recorded.get(
            (back.get(alert.reminder_id, alert.reminder_id), alert.context, alert.created_at)
        )
        if original is None or alert.shown_at is None:
            return
        assert original.shown_at is not None and original.answered_at is not None
        when = alert.shown_at + original.answered_at - original.shown_at
        timeline.at(when, self._reply(alert.id, original))

    def _reply(self, alert_id: int, original: Alert) -> Command:
        def reply(core: Reminders) -> None:
            match original.answer:
                case Answer.DONE:
                    core.done(alert_id)
                case Answer.USEFUL:  # Next time took its place (ADR-0021)
                    core.snooze(alert_id, Snooze.NEXT_TIME)
                case Answer.NOT_HERE:
                    core.not_here(alert_id)
                case Answer.SNOOZE:
                    core.snooze(alert_id, original.snooze or self._snooze(original))
                case Answer.CLOSED:
                    core.close(alert_id)
                case None:
                    pass

        return reply

    def _snooze(self, original: Alert) -> Snooze:
        """For version 0.1, which did not record it: the Snooze whose end falls after the
        reminder's last judgement as snoozed and by its first judgement as free. A reminder the
        day never judged again stays snoozed until tomorrow, so the replay does not judge it
        where the day did not."""
        answered = original.answered_at
        assert answered is not None
        judged = self._judged(original.reminder_id, answered)
        if not judged:
            return Snooze.TOMORROW
        low = max((at for at, outcome in judged if outcome is Outcome.SNOOZED), default=answered)
        high = min(
            (at for at, outcome in judged if outcome is not Outcome.SNOOZED and at > low),
            default=math.inf,
        )
        for kind in (Snooze.QUARTER_HOUR, Snooze.HOUR, Snooze.TOMORROW):
            end = snooze_end(kind, self._calendar, answered)
            if end is not None and low < end <= high:
                return kind
        return Snooze.HOUR

    # The replayed day

    def _result(self, timeline: Timeline, start: Snapshot) -> Day:
        """The replayed day, as `day.select` gives a day of the log: the alerts made in it, and
        the answers from the log's first."""
        revisions = {reminder.revision.id: reminder.revision for reminder in start.reminders}
        reminders = {reminder.id: reminder for reminder in start.reminders}
        alerts: dict[int, Alert] = {}
        answers = [answer for answer in self._log.answers if answer.at < self._begin]
        left: list[Left] = []
        stretches: list[SituationStretch] = []
        for record in timeline.records:
            match record:
                case Reminder():
                    revisions[record.revision.id] = record.revision
                    reminders[record.id] = record
                case Alert() if record.created_at >= self._begin:  # not those of the tray list
                    alerts[record.id] = record
                case ContextAnswer():
                    answers.append(record)
                case Left():
                    left.append(record)
                case SituationStretch():
                    stretches.append(record)
        start_of_day, end_of_day = bounds(self._day.day, self._calendar)
        return Day(
            self._day.day,
            tuple(timeline.evaluations.values()),
            tuple(alert for alert in alerts.values() if not alert.requested),
            revisions,
            requested=tuple(alert for alert in alerts.values() if alert.requested),
            answers=tuple(answers),
            situations=tuple(
                sorted(
                    (s for s in stretches if s.until > start_of_day and s.since < end_of_day),
                    key=lambda s: (s.since, s.situation, s.value),
                )
            ),
            left=tuple(left),
            reminders=tuple(reminders.values()),
        )
