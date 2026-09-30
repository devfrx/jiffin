"""`replay`: a day of the log again through `core`, on simulated time (ADR-0017).

The day's evaluated contexts come back as observations, each at the moment it came to the
foreground, and the clock moves to each deadline in turn, so every evaluation happens at its
exact time (pipeline.md). `core` starts from the state the log had when the day began; the
reminders come, change and go as the log recorded them; the owner answers the alerts the log
also had, after the same time on screen, and every other alert leaves the screen after 10 s.
What changes is one thing at a time: the threshold, the reminders or the engine. Replayed at its
own threshold with its own scores, a day gives its alerts back.

What the log does not keep is inferred from what it does:
- a context seen twice in a row was left in between: a moment with no context separates them;
- a reminder's new text starts when the context of its first evaluation came to the foreground;
- how long a snooze lasted, from when the reminder was last judged snoozed and first judged
  free after it.
"""

import heapq
import itertools
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, timedelta

from jiffin.core.clock import Clock, SimulatedClock, SystemClock
from jiffin.core.context import Context, Observation
from jiffin.core.model import EngineBuild, Model, ModelError
from jiffin.core.records import (
    Alert,
    Answer,
    Evaluation,
    LastIds,
    Outcome,
    Record,
    Reminder,
    Revision,
    Snapshot,
)
from jiffin.core.reminders import (
    DAY_STARTS_AT,
    HOUR_MS,
    MINUTE_MS,
    THRESHOLD,
    TOMORROW_AT,
    Reminders,
    Snooze,
)
from jiffin.harness.day import Day
from jiffin.harness.errors import HarnessError
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
            revision.condition: revision.statement
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
            raise ModelError("the log holds no statement for that condition")
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
        self._clock.advance(time - self._clock.now())

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


def observations(evaluations: Iterable[Evaluation]) -> list[Observation]:
    """Each evaluated context when it came to the foreground, once."""
    found: list[Observation] = []
    seen: set[tuple[int, Context]] = set()
    previous: Context | None = None
    for evaluation in sorted(evaluations, key=lambda e: (e.context_since, e.at)):
        mark = (evaluation.context_since, evaluation.context)
        if mark in seen:  # judged again while it stayed: a snooze ended there
            continue
        seen.add(mark)
        if evaluation.context == previous:
            found.append(Observation(evaluation.context_since - 1, None))
        found.append(Observation(evaluation.context_since, evaluation.context))
        previous = evaluation.context
    return found


def new_reminder(condition: str, action: str) -> Command:
    def create(core: Reminders) -> None:
        core.create(condition, action)

    return create


def observe(observation: Observation) -> Command:
    return lambda core: core.observe(observation)


class Replay:
    """One day of the log through `core` again, with one thing changed.

    Without `model` the scores are those the log keeps; with one, the engine judges and
    `rewrite` has it write every statement again. `extra` adds reminders, as (condition,
    action), from the start of the day; `answers` replays the owner's answers.
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
        self._seen = observations(day.evaluations)
        self._begin = self._seen[0].at - 1
        self._until = max(evaluation.at for evaluation in day.evaluations)
        self._clock = SimulatedClock(self._begin, SystemClock().local(self._begin).tzinfo or UTC)
        self._ids: dict[int, int] = {}
        """The replay's ids of the reminders the day created, by the log's ids."""
        self._recorded = {
            (a.reminder_id, a.context, a.created_at): a
            for a in day.alerts
            if a.answer is not None and a.shown_at is not None and a.answered_at is not None
        }
        """The answered alerts, by reminder, context and when they were made: a reminder may
        alert twice in one stable context, before and after a snooze."""

    def run(self) -> Day:
        start = self._start()
        model = self._model or Recorded(self._log, self._day, self._clock)
        core = Reminders(model, self._clock, lambda view: None, start, threshold=self._threshold)
        timeline = Timeline(core, self._clock, self._answer if self._answers else passive)
        for condition, action in self._extra:
            timeline.at(self._begin, new_reminder(condition, action))
        for when, command in self._commands():
            timeline.at(when, command)
        timeline.run(self._until)
        return self._result(timeline, start)

    # Where core starts

    def _start(self) -> Snapshot:
        reminders = []
        for reminder in self._log.reminders:
            if reminder.created_at < self._begin and not self._gone(reminder):
                first = self._revisions(reminder)[0][1]
                snoozed = self._snoozed_at_start(reminder)
                reminders.append(
                    replace(reminder, revision=first, completed_at=None, snoozed_until=snoozed)
                )
        made = {(a.reminder_id, a.context) for a in self._day.alerts if a.answer is Answer.NOT_HERE}
        return Snapshot(
            reminders=tuple(reminders),
            silences=tuple(
                silence
                for silence in self._log.silences
                if (silence.reminder_id, silence.context) not in made
            ),
            last_alerts=self._last_alerts(),
            last_ids=LastIds(
                reminder=max((r.id for r in self._log.reminders), default=0),
                revision=max(self._log.revisions, default=0),
                evaluation=max((e.id for e in self._log.evaluations), default=0),
                alert=max((a.id for a in self._log.alerts), default=0),
            ),
        )

    def _gone(self, reminder: Reminder) -> bool:
        return reminder.completed_at is not None and reminder.completed_at < self._begin

    def _revisions(self, reminder: Reminder) -> list[tuple[int, Revision]]:
        """Its revisions in the order the day judged them, each with when the context of its
        first evaluation came to the foreground; the current one if the day judged none."""
        chain: list[tuple[int, Revision]] = []
        for evaluation in sorted(self._day.evaluations, key=lambda e: e.at):
            for candidate in evaluation.candidates:
                revision = self._day.revisions[candidate.revision_id]
                known = any(revision.id == earlier.id for _, earlier in chain)
                if revision.reminder_id == reminder.id and not known:
                    chain.append((evaluation.context_since, revision))
        if not chain:
            chain = [(self._begin, reminder.revision)]
        if self._rewrite:
            chain = [(when, replace(r, statement=None, statement_build=None)) for when, r in chain]
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
        """A snooze from before the day: until the reminder was first judged free."""
        judged = self._judged(reminder.id, self._begin)
        if not judged or judged[0][1] is not Outcome.SNOOZED:
            return None
        return next((at for at, outcome in judged if outcome is not Outcome.SNOOZED), None)

    def _last_alerts(self) -> tuple[tuple[int, int], ...]:
        last: dict[int, int] = {}
        for alert in self._log.alerts:
            if alert.created_at < self._begin:
                last[alert.reminder_id] = max(last.get(alert.reminder_id, 0), alert.created_at)
        return tuple(sorted(last.items()))

    # What happens during the day

    def _commands(self) -> list[tuple[int, Command]]:
        commands: list[tuple[int, Command]] = []
        for reminder in self._log.reminders:
            if self._gone(reminder) or reminder.created_at > self._until:
                continue
            chain = self._revisions(reminder)
            if reminder.created_at >= self._begin:
                commands.append((reminder.created_at, self._create(reminder.id, chain[0][1])))
            for since, revision in chain[1:]:
                commands.append((since, self._edit(reminder.id, revision)))
            if reminder.completed_at is not None:
                # A millisecond late, so that a replayed Fatto completes it first, as it did.
                commands.append((reminder.completed_at + 1, self._complete(reminder.id)))
        commands += [(observation.at, observe(observation)) for observation in self._seen]
        return commands

    def _create(self, log_id: int, revision: Revision) -> Command:
        def create(core: Reminders) -> None:
            self._ids[log_id] = core.create(revision.condition, revision.action).id

        return create

    def _edit(self, log_id: int, revision: Revision) -> Command:
        def edit(core: Reminders) -> None:
            core.edit(self._ids.get(log_id, log_id), revision.condition, revision.action)

        return edit

    def _complete(self, log_id: int) -> Command:
        return lambda core: core.complete(self._ids.get(log_id, log_id))

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
                case Answer.USEFUL:
                    core.useful(alert_id)
                case Answer.NOT_HERE:
                    core.not_here(alert_id)
                case Answer.SNOOZE:
                    core.snooze(alert_id, self._snooze(original))
                case None:
                    pass

        return reply

    def _snooze(self, original: Alert) -> Snooze:
        """The snooze whose end falls after the reminder's last judgement as snoozed and by its
        first judgement as free. A reminder the day never judged again stays snoozed until
        tomorrow, so the replay does not judge it where the day did not."""
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
        local = self._clock.local(answered)
        day = local.date() + timedelta(days=int(local.time() >= DAY_STARTS_AT))
        ends = (
            (Snooze.QUARTER_HOUR, answered + 15 * MINUTE_MS),
            (Snooze.HOUR, answered + HOUR_MS),
            (Snooze.TOMORROW, self._clock.instant(day, TOMORROW_AT)),
        )
        return next((kind for kind, end in ends if low < end <= high), Snooze.HOUR)

    # The replayed day

    def _result(self, timeline: Timeline, start: Snapshot) -> Day:
        revisions = {reminder.revision.id: reminder.revision for reminder in start.reminders}
        alerts: dict[int, Alert] = {}
        for record in timeline.records:
            if isinstance(record, Reminder):
                revisions[record.revision.id] = record.revision
            elif isinstance(record, Alert):
                alerts[record.id] = record
        return Day(
            self._day.day, tuple(timeline.evaluations.values()), tuple(alerts.values()), revisions
        )
