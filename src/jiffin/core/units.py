"""When a reminder may ring, and its units (ADR-0021).

A reminder rings at most once per unit: the instance of its time, or the occasion, which
`reminders` follows from the contexts. Each instance of a time (`schedule.instances`) gets a
window, how long it may ring from its start, which depends on the kind of time and on "Ogni
volta". Times are wall-clock times, as in `schedule`.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime

from jiffin.core.clock import Clock
from jiffin.core.records import Revision
from jiffin.core.schedule import (
    DAY_STARTS_AT,
    ONE_DAY,
    Instance,
    Moment,
    OnDate,
    Schedule,
    frequency_period,
    instances,
    jiffin_day,
)


@dataclass(frozen=True, slots=True)
class Window:
    """When an instance may ring: from `start`, and no longer from `end`; None is never."""

    start: datetime
    end: datetime | None
    unit: datetime
    """When its unit starts, for a reminder that rings once per instance: the instance's start,
    or with a frequency the start of its period."""


def by_instance(revision: Revision) -> bool:
    """Whether the reminder rings once per instance of its time rather than once per occasion:
    with only a time, a moment or a frequency, and with a date when it is not perennial, since
    that rings once, however many occasions the day brings."""
    schedule = revision.schedule
    if not revision.remainder:
        return True
    if schedule is None:
        return False
    return (
        isinstance(schedule.hours, Moment)
        or schedule.frequency is not None
        or (isinstance(schedule.days, OnDate) and not revision.perennial)
    )


def windows(schedule: Schedule, perennial: bool, written_at: datetime) -> Iterator[Window]:
    """The windows of a time written at `written_at`, in order, as ADR-0021's table gives them. A
    moment already past when the condition was written has none."""
    found = instances(schedule, written_at)
    instance = next(found, None)
    while instance is not None:
        following = next(found, None)
        yield _window(schedule, perennial, instance, following)
        instance = following


class Times:
    """The windows of one time, read forward as the clock moves."""

    def __init__(self, schedule: Schedule, perennial: bool, written_at: datetime) -> None:
        self._schedule = schedule
        self._perennial = perennial
        self._written_at = _wall(written_at)
        self._start()

    def at(self, moment: datetime) -> Window | None:
        """The window `moment` is in, if any."""
        moment = self._reach(moment)
        window = self._next
        if window is None or window.start > moment:
            return None
        return window

    def next_change(self, moment: datetime) -> datetime | None:
        """The first start or end of a window after `moment`: when the reminder may start or stop
        ringing. None when nothing changes any more."""
        window = self.at(moment)
        if window is not None:
            return window.end
        return None if self._next is None else self._next.start

    def _start(self) -> None:
        self._windows = windows(self._schedule, self._perennial, self._written_at)
        self._next = next(self._windows, None)
        """The first window not over at `_last`."""
        self._last = self._written_at

    def _reach(self, moment: datetime) -> datetime:
        moment = _wall(moment)
        if moment < self._last:  # the clock went back
            self._start()
        self._last = moment
        while self._next is not None and self._next.end is not None and self._next.end <= moment:
            self._next = next(self._windows, None)
        return moment


def next_occasion(revision: Revision, clock: Clock, now: int) -> bool:
    """Whether "Alla prossima volta" has a unit to wait for, the reminder having rung in this one
    (ADR-0021): with the occasion as its unit, when its time still holds after now or it has
    none; with the instance, when an instance comes after this one."""
    schedule, written_at = revision.schedule, revision.written_at
    if schedule is None or written_at is None:
        return True
    at = _wall(clock.local(now))
    once = by_instance(revision)
    current: Window | None = None
    for window in windows(schedule, revision.perennial, clock.local(written_at)):
        if window.end is not None and window.end <= at:
            continue
        if not once:
            return True
        if window.start <= at:
            current = window
        elif current is None or window.unit > current.unit:
            return True
    return False


def instance_day(revision: Revision, clock: Clock, at: int) -> date | None:
    """The Jiffin day of the instance of its time that a reminder rings for at `at`: what the
    alert of a reminder with only a time names, "Ieri alle 15:00" when it rings late (#84). None
    without a time, or when `at` is in no window."""
    schedule, written_at = revision.schedule, revision.written_at
    if schedule is None or written_at is None:
        return None
    moment = _wall(clock.local(at))
    for window in windows(schedule, revision.perennial, clock.local(written_at)):
        if window.start > moment:
            return None
        if window.end is None or moment < window.end:
            return jiffin_day(window.start)
    return None


def ended(schedule: Schedule | None, at: datetime) -> bool:
    """Whether the period of a time is over, at the local time `at`: the reminder stays, and goes
    silent (ADR-0021)."""
    return (
        schedule is not None
        and schedule.period is not None
        and jiffin_day(_wall(at)) > schedule.period.last
    )


def _window(
    schedule: Schedule, perennial: bool, instance: Instance, following: Instance | None
) -> Window:
    unit = instance.start
    if schedule.frequency is not None:
        period = frequency_period(schedule.frequency, instance.day)
        unit = datetime.combine(period.first, DAY_STARTS_AT)
    end: datetime | None = instance.end
    one_off_date = isinstance(schedule.days, OnDate) and not perennial
    if isinstance(schedule.hours, Moment):
        if perennial:  # until its Jiffin day ends, at 04:00
            end = datetime.combine(instance.day + ONE_DAY, DAY_STARTS_AT)
        else:  # never lost: until the next moment, or with a date until it has rung
            end = None if one_off_date or following is None else following.start
    elif one_off_date:
        end = None
    if schedule.period is not None:  # never after the period
        over = datetime.combine(schedule.period.last + ONE_DAY, DAY_STARTS_AT)
        end = over if end is None else min(end, over)
    return Window(instance.start, end, unit)


def _wall(at: datetime) -> datetime:
    return at.replace(tzinfo=None)
