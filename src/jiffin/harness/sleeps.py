"""The engine's sleeps over a day, against the thresholds of ADR-0031.

The app records each light sleep of the engine with its wake (ADR-0027), and each stretch with
nothing in front for the reminders; `core`'s requests are its evaluations that asked the engine,
and the statements it wrote.

- **A wake is late** when the first evaluation after it starts after the end of its 5 s of
  stable context. The worker waits for the wake, so that evaluation starts when the engine is
  ready: it waited `ready_at` minus the end of its 5 s. A wake for a statement delays no alert,
  and is apart.
- **The engine must sleep** within 5 minutes and 10 s of `core`'s last request, or of a wake,
  and within 10 s of nothing in front, or of a request while nothing is in front. Each time it
  does not is an error, counted on evidence that the app still ran: a record of `core` or of
  the engine after the time. A new run of the app starts afresh, and a day before version 0.3
  has none of these records.
"""

import bisect
import statistics
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from jiffin.client.supervisor import IDLE_MS
from jiffin.core.clock import Clock
from jiffin.core.debounce import DEBOUNCE_MS
from jiffin.core.records import EngineSleep, SleepReason, Waker
from jiffin.harness import day as days
from jiffin.store.store import Log

LATE_WAKES = 1
LATE_BY_S = 2.0
"""At most one late wake in the day, by at most 2 s (ADR-0031)."""
IDLE_LIMIT_MS = IDLE_MS + 10_000
NOTHING_LIMIT_MS = 10_000
"""Asleep within 5 minutes and 10 s of `core`'s last request, and within 10 s of nothing in
front (ADR-0031)."""
SETTLE_MS = 10_000
"""The engine's VRAM asleep counts after the first 10 s of a sleep."""
ASLEEP_VRAM_MIB = 0.2 * 1024

# What the records say, in the order each acts when two come at the same time.
_STARTUP, _NOTHING, _SOMETHING, _SLEEP, _REQUEST, _EVALUATION = range(6)


@dataclass(frozen=True, slots=True)
class Wake:
    woken_at: int
    woken_by: Waker
    seconds: float
    """From the wake to the model ready, its warm-up judgement done."""
    late: float
    """Seconds the first evaluation after it waited beyond its 5 s: 0 when it did not wait,
    and for a statement."""


@dataclass(frozen=True, slots=True)
class SleepError:
    due: int
    """When the engine should have been asleep."""
    rule: SleepReason
    """The rule that asked it to sleep: 5 minutes idle, or nothing in front."""


@dataclass(frozen=True, slots=True)
class Sleeps:
    recorded: bool
    """False for a day of an app before version 0.3, which neither sleeps nor records."""
    slept: dict[SleepReason, int]
    """The sleeps that began on the day, by why."""
    wakes: tuple[Wake, ...]
    """The wakes of the day with the model ready, in order."""
    unready: int
    """The wakes of the day that ended without the model: the wake failed, or the engine failed
    asleep."""
    errors: tuple[SleepError, ...]
    asleep_ms: int
    """Of the day's active time, from the first context evaluated to the last evaluation."""
    active_ms: int
    vram_asleep_mib: int | None
    """The engine's dedicated VRAM at its peak in the monitor's rows asleep, after the first 10
    s of each sleep; None without such rows."""
    vram_asleep_rows: int
    vram_awake_mib: int | None
    """The engine's dedicated VRAM at its peak in the rows awake."""

    @property
    def late(self) -> tuple[Wake, ...]:
        return tuple(wake for wake in self.wakes if wake.late > 0)


NOT_RECORDED = Sleeps(False, {}, (), 0, (), 0, 0, None, 0, None)


def summarize(
    log: Log, day: days.Day, clock: Clock, engine_vram: Sequence[tuple[int, int]] = ()
) -> Sleeps:
    """`engine_vram` is the monitor's rows: when each was taken, in UTC milliseconds, and the
    engine's dedicated VRAM in MiB then."""
    start, end = days.span(day)
    runs = [stretch.since for stretch in log.nothing_in_front if stretch.startup]
    if not runs or runs[0] > end:
        return NOT_RECORDED
    on_day = [sleep for sleep in log.sleeps if clock.local(sleep.slept_at).date() == day.day]
    woken = [
        sleep
        for sleep in log.sleeps
        if sleep.woken_at is not None and clock.local(sleep.woken_at).date() == day.day
    ]
    asleep = list(_asleep(log.sleeps, runs))
    rows_asleep = [mib for at, mib in engine_vram if _within(asleep, at, SETTLE_MS)]
    rows_awake = [mib for at, mib in engine_vram if not _within(asleep, at, 0)]
    return Sleeps(
        recorded=True,
        slept={
            reason: n
            for reason in SleepReason
            if (n := sum(sleep.reason is reason for sleep in on_day))
        },
        wakes=tuple(_wakes(log, woken)),
        unready=sum(sleep.ready_at is None for sleep in woken),
        errors=tuple(e for e in _errors(log, runs) if clock.local(e.due).date() == day.day),
        asleep_ms=sum(
            max(0, min(end, until or end) - max(start, since)) for since, until in asleep
        ),
        active_ms=end - start,
        vram_asleep_mib=max(rows_asleep, default=None),
        vram_asleep_rows=len(rows_asleep),
        vram_awake_mib=max(rows_awake, default=None),
    )


def spread(wakes: Sequence[Wake]) -> tuple[float, float, float]:
    """The wakes' times: min, median and max, in seconds."""
    seconds = [wake.seconds for wake in wakes]
    return min(seconds), statistics.median(seconds), max(seconds)


def _wakes(log: Log, woken: Sequence[EngineSleep]) -> Iterator[Wake]:
    """Each wake with the model ready, and how long the first evaluation after it waited beyond
    its 5 s."""
    evaluations = log.evaluations  # the oldest first
    times = [evaluation.at for evaluation in evaluations]
    for sleep in woken:
        if sleep.ready_at is None or sleep.woken_at is None or sleep.woken_by is None:
            continue
        index = bisect.bisect_left(times, sleep.woken_at)
        waited = 0
        if sleep.woken_by is not Waker.STATEMENT and index < len(evaluations):
            stable = evaluations[index].context_since + DEBOUNCE_MS
            waited = max(0, sleep.ready_at - stable)
        yield Wake(
            sleep.woken_at,
            sleep.woken_by,
            (sleep.ready_at - sleep.woken_at) / 1000,
            waited / 1000,
        )


def _errors(log: Log, runs: Sequence[int]) -> Iterator[SleepError]:
    """Walk the records in order of time, from the first run that keeps them: while the engine
    is known to be awake, since a request or a wake, each deadline that passes before it sleeps
    is an error, once."""
    events = [(run, _STARTUP) for run in runs]
    for stretch in log.nothing_in_front:
        if not stretch.startup:
            events.append((stretch.since, _NOTHING))
        if stretch.until is not None:
            events.append((stretch.until, _SOMETHING))
    events += [(sleep.slept_at, _SLEEP) for sleep in log.sleeps]
    events += [(sleep.ready_at, _REQUEST) for sleep in log.sleeps if sleep.ready_at is not None]
    for evaluation in log.evaluations:
        asked = not evaluation.failed and any(not c.from_cache for c in evaluation.candidates)
        events.append((evaluation.at, _REQUEST if asked else _EVALUATION))
    events += [
        (revision.created_at, _REQUEST)
        for revision in log.revisions.values()
        if revision.statement is not None and revision.created_at is not None
    ]
    awake: int | None = None  # the last request or wake, while the engine is known to be awake
    nothing: int | None = None  # since when nothing has been in front
    idle_said = nothing_said = False
    for at, kind in sorted(event for event in events if event[0] >= runs[0]):
        if kind == _STARTUP:  # the engine of the run before is gone
            awake, nothing, nothing_said = None, at, False
            continue
        if awake is not None:
            if not idle_said and at > awake + IDLE_LIMIT_MS:
                idle_said = True
                yield SleepError(awake + IDLE_LIMIT_MS, SleepReason.IDLE)
            due = None if nothing is None else max(nothing, awake) + NOTHING_LIMIT_MS
            if due is not None and not nothing_said and at > due:
                nothing_said = True
                yield SleepError(due, SleepReason.NOTHING_IN_FRONT)
        if kind == _NOTHING:
            nothing, nothing_said = at, False
        elif kind == _SOMETHING:
            nothing = None
        elif kind == _SLEEP:
            awake = None
        elif kind == _REQUEST:
            awake, idle_said, nothing_said = at, False, False


def _asleep(sleeps: Sequence[EngineSleep], runs: Sequence[int]) -> Iterator[tuple[int, int | None]]:
    """When the engine slept: a sleep the app closed in ends when the app starts again, or
    never."""
    for sleep in sleeps:
        until = sleep.woken_at
        if until is None:
            until = next((run for run in runs if run > sleep.slept_at), None)
        yield sleep.slept_at, until


def _within(asleep: Sequence[tuple[int, int | None]], at: int, after: int) -> bool:
    return any(since + after <= at and (until is None or at < until) for since, until in asleep)
