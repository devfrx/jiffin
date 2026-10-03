"""The time of a reminder, in real dates, and its calendar (ADR-0020).

A `Schedule` is what `meanings.read` makes of the time words of a condition, resolved when the
condition is written: "domani" becomes a date, "fino a domenica" a period that ends on one, so a
later change to the grammar never moves a saved time. Dates and times are local, as the user's
clock shows them; the calendar counts Jiffin days, from 04:00 to 04:00, and works on wall-clock
times, which `Clock.instant` turns into instants. A datetime given to it may carry a zone: only
its wall clock counts.
"""

import itertools
from calendar import monthrange
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

DAY_STARTS_AT = time(4)
"""When a Jiffin day starts: before 04:00 the night is not over, and it is still the day before."""

ONE_DAY = timedelta(days=1)


# The days


@dataclass(frozen=True, slots=True)
class Weekdays:
    """Every week, on these days: "il lunedì", "nei giorni feriali". All seven are every day."""

    weekdays: frozenset[int]
    """0 is Monday; never empty."""


EVERY_DAY = Weekdays(frozenset(range(7)))


@dataclass(frozen=True, slots=True)
class OnDate:
    """One day: "domani", "lunedì", "il 5 ottobre". A deadline, not a window (ADR-0021)."""

    day: date


@dataclass(frozen=True, slots=True)
class EveryNWeeks:
    """A weekday every N weeks, from its first: "un lunedì sì e uno no"."""

    weekday: int
    weeks: int
    first: date
    """A day on `weekday`: the next one when the condition was written, or that day."""


@dataclass(frozen=True, slots=True)
class MonthWeekday:
    """A weekday of every month: "il primo lunedì del mese", "l'ultimo venerdì del mese"."""

    weekday: int
    nth: int
    """1 to 4, or -1 for the last."""


@dataclass(frozen=True, slots=True)
class MonthDay:
    """A day of every month: "il 15 di ogni mese". In a shorter month 29 to 31 are its last day."""

    day: int
    """1 to 31, or -1 for the last: "a fine mese"."""


@dataclass(frozen=True, slots=True)
class YearDay:
    """A day of every year: "il 12 marzo di ogni anno". 29 February is the 28th in other years."""

    month: int
    day: int


type Days = Weekdays | OnDate | EveryNWeeks | MonthWeekday | MonthDay | YearDay


# The hours


@dataclass(frozen=True, slots=True)
class Slot:
    """From `start` to `end` of a Jiffin day: "la sera", "dopo le 23" (until 04:00).

    Hours before 04:00 are on the next calendar day, and an end not after the start too.
    """

    start: time
    end: time


@dataclass(frozen=True, slots=True)
class Moment:
    """ "alle 15", "tra 2 ore". Before 04:00, on the next calendar day."""

    at: time


type Hours = Slot | Moment


@dataclass(frozen=True, slots=True)
class Period:
    """A window of validity, from the first to the last Jiffin day, both included: "dal 10 al
    20 ottobre", "fino a domenica". Once over, the reminder stays and goes silent (ADR-0021)."""

    first: date
    last: date


class Unit(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


@dataclass(frozen=True, slots=True)
class Frequency:
    """At most once every `count` units: "ogni due settimane", "una volta al mese".

    The periods follow each other from the Jiffin day the condition was written on. A period of
    months ends where the next one starts: from 31 January, on 28 February.
    """

    count: int
    unit: Unit
    first: date


@dataclass(frozen=True, slots=True)
class Schedule:
    """When a reminder may ring: the days, and in each of them the hours; within a period, if
    it has one; at most once per period of its frequency, if it has one."""

    days: Days = EVERY_DAY
    hours: Hours | None = None
    """None is the whole day."""
    period: Period | None = None
    frequency: Frequency | None = None


@dataclass(frozen=True, slots=True)
class Instance:
    """One time a schedule holds: the slot, the whole day or the moment of one Jiffin day, in
    wall-clock time. A moment ends when it starts."""

    day: date
    start: datetime
    end: datetime


# The calendar


def jiffin_day(at: datetime) -> date:
    """The Jiffin day of a local time."""
    if at.time() < DAY_STARTS_AT:
        return at.date() - ONE_DAY
    return at.date()


def instances(schedule: Schedule, since: datetime) -> Iterator[Instance]:
    """The instances not over at `since`, in order: the one under way, if any, then the next.

    A slot or a whole day is over once it has ended, a moment once it has passed. Endless unless
    the days or the period end; the frequency does not change them, see `frequency_period`.
    """
    since = _wall(since)
    # A slot of the day before can still be under way: "dalle 22 alle 2", or "la notte".
    first = jiffin_day(since) - ONE_DAY
    period = schedule.period
    if period is not None:
        first = max(first, period.first)
    for day in _days(schedule.days, first):
        if period is not None and day > period.last:
            return
        instance = _instance(day, schedule.hours)
        if not _over(instance, since):
            yield instance


def frequency_period(frequency: Frequency, day: date) -> Period:
    """The period of the frequency that holds the Jiffin day `day`: its instance (ADR-0021)."""
    if frequency.unit in (Unit.DAY, Unit.WEEK):
        length = frequency.count * (7 if frequency.unit is Unit.WEEK else 1)
        start = frequency.first + timedelta(days=(day - frequency.first).days // length * length)
        return Period(start, start + timedelta(days=length - 1))
    months = frequency.count * (12 if frequency.unit is Unit.YEAR else 1)
    elapsed = (day.year - frequency.first.year) * 12 + day.month - frequency.first.month
    nth = elapsed // months
    if _add_months(frequency.first, nth * months) > day:
        nth -= 1
    start = _add_months(frequency.first, nth * months)
    return Period(start, _add_months(frequency.first, (nth + 1) * months) - ONE_DAY)


def _wall(at: datetime) -> datetime:
    return at.replace(tzinfo=None)


def _on_day(day: date, at: time) -> datetime:
    """When the clock shows `at` in the Jiffin day `day`."""
    return datetime.combine(day + ONE_DAY if at < DAY_STARTS_AT else day, at)


def _instance(day: date, hours: Hours | None) -> Instance:
    match hours:
        case None:
            start = _on_day(day, DAY_STARTS_AT)
            return Instance(day, start, start + ONE_DAY)
        case Slot(begin, finish):
            start, end = _on_day(day, begin), _on_day(day, finish)
            if end <= start:
                end += ONE_DAY
            return Instance(day, start, end)
        case Moment(at):
            moment = _on_day(day, at)
            return Instance(day, moment, moment)


def _over(instance: Instance, at: datetime) -> bool:
    if instance.start == instance.end:
        return instance.start < at
    return instance.end <= at


def _days(days: Days, since: date) -> Iterator[date]:
    """The Jiffin days of `days` from `since` on, in order."""
    match days:
        case Weekdays(weekdays):
            for day in _dates(since):
                if day.weekday() in weekdays:
                    yield day
        case OnDate(day):
            if day >= since:
                yield day
        case EveryNWeeks(_, weeks, first):
            step = timedelta(weeks=weeks)
            day = first
            while day < since:
                day += step
            yield from _dates(day, step)
        case MonthWeekday(weekday, nth):
            for year, month in _months(since):
                day = _month_weekday(year, month, weekday, nth)
                if day >= since:
                    yield day
        case MonthDay(number):
            for year, month in _months(since):
                last = monthrange(year, month)[1]
                day = date(year, month, last if number == -1 else min(number, last))
                if day >= since:
                    yield day
        case YearDay(month, number):
            for year in itertools.count(since.year):
                day = date(year, month, min(number, monthrange(year, month)[1]))
                if day >= since:
                    yield day


def _dates(first: date, step: timedelta = ONE_DAY) -> Iterator[date]:
    day = first
    while True:
        yield day
        day += step


def _months(since: date) -> Iterator[tuple[int, int]]:
    """The year and month of `since`, then of every month after it."""
    for elapsed in itertools.count():
        years, month = divmod(since.month - 1 + elapsed, 12)
        yield since.year + years, month + 1


def _month_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    if nth == -1:
        last = date(year, month, monthrange(year, month)[1])
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))


def _add_months(day: date, months: int) -> date:
    years, month = divmod(day.month - 1 + months, 12)
    year = day.year + years
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))
