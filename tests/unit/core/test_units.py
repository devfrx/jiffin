"""When a reminder may ring, and its units: ADR-0021's table of instances."""

from datetime import UTC, date, datetime, time
from itertools import islice

import pytest

from jiffin.core.clock import SimulatedClock
from jiffin.core.meanings import read
from jiffin.core.records import Revision
from jiffin.core.schedule import Moment, OnDate, Period, Schedule, Slot
from jiffin.core.units import (
    Times,
    Window,
    by_instance,
    ended,
    instance_day,
    next_occasion,
    windows,
)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A wall-clock time of October 2026, as the calendar gives them."""
    return datetime.combine(date(2026, 10, day), time(hour, minute))


FRIDAY = at(2, 10)
EVENING = Slot(time(18), time(23))


def revision(condition: str, perennial: bool = False, written_at: datetime = FRIDAY) -> Revision:
    """A revision as `core` makes it, its time read at `written_at`, in UTC."""
    reading = read(condition, written_at)
    written = round(written_at.replace(tzinfo=UTC).timestamp() * 1000)
    return Revision(
        1,
        1,
        1,
        condition,
        "chiamare Mario",
        reading.remainder,
        schedule=reading.schedule,
        written_at=written,
        perennial=perennial,
    )


def first(condition: str, count: int, perennial: bool = False) -> list[Window]:
    found = revision(condition, perennial)
    assert found.schedule is not None
    return list(islice(windows(found.schedule, perennial, FRIDAY), count))


# The windows


def test_a_one_off_moment_may_ring_until_the_next_one() -> None:
    assert first("alle 15", 2) == [
        Window(at(2, 15), at(3, 15), at(2, 15)),
        Window(at(3, 15), at(4, 15), at(3, 15)),
    ]


def test_a_perennial_moment_may_ring_until_four() -> None:
    assert first("alle 15", 1, perennial=True) == [Window(at(2, 15), at(3, 4), at(2, 15))]


def test_a_moment_past_when_written_starts_the_next_day() -> None:
    assert first("alle 9", 1)[0].start == at(3, 9)


def test_a_slot_or_a_whole_day_may_ring_until_it_ends() -> None:
    for perennial in (False, True):
        assert first("la sera", 1, perennial) == [Window(at(2, 18), at(2, 23), at(2, 18))]
        assert first("il lunedì", 1, perennial) == [Window(at(5, 4), at(6, 4), at(5, 4))]


@pytest.mark.parametrize(
    ("condition", "one_off", "perennial"),
    [
        ("domani alle 15", Window(at(3, 15), None, at(3, 15)), at(4, 4)),
        ("stasera", Window(at(2, 18), None, at(2, 18)), at(2, 23)),
        ("domani", Window(at(3, 4), None, at(3, 4)), at(4, 4)),
    ],
    ids=["moment", "slot", "day"],
)
def test_a_date_may_ring_forever_once_or_perennial_until_its_instance_ends(
    condition: str, one_off: Window, perennial: datetime
) -> None:
    assert first(condition, 2) == [one_off]
    assert first(condition, 2, perennial=True) == [Window(one_off.start, perennial, one_off.unit)]


def test_the_windows_of_a_frequency_share_the_unit_of_their_period() -> None:
    weekly = first("ogni settimana", 8)
    assert [window.start for window in weekly] == [at(day, 4) for day in range(2, 10)]
    assert [window.unit for window in weekly] == [at(2, 4)] * 7 + [at(9, 4)]


def test_nothing_rings_after_its_period() -> None:
    moments = first("alle 15 fino a domenica", 4)
    assert [(window.start, window.end) for window in moments] == [
        (at(2, 15), at(3, 15)),
        (at(3, 15), at(4, 15)),
        (at(4, 15), at(5, 4)),
    ]


# The units


@pytest.mark.parametrize(
    ("condition", "perennial", "once"),
    [
        ("alle 15", False, True),
        ("la sera", False, True),
        ("quando apro Claude alle 23", False, True),
        ("ogni settimana quando apro Teams", True, True),
        ("domani quando apro Teams", False, True),
        ("domani quando apro Teams", True, False),
        ("quando apro Claude dopo le 23", False, False),
        ("quando apro Outlook il lunedì", True, False),
        ("quando apro Figma", False, False),
    ],
    ids=[
        "only a time",
        "a slot alone",
        "a moment with an app",
        "a frequency with an app",
        "a one-off date with an app",
        "a perennial date with an app",
        "a slot with an app",
        "a day with an app",
        "no time",
    ],
)
def test_a_reminder_rings_once_per_instance_or_once_per_occasion(
    condition: str, perennial: bool, once: bool
) -> None:
    assert by_instance(revision(condition, perennial)) is once


# Reading them forward


def test_times_say_the_window_under_way_and_when_it_changes() -> None:
    times = Times(Schedule(hours=EVENING), False, FRIDAY)
    assert (times.at(at(2, 17)), times.next_change(at(2, 17))) == (None, at(2, 18))
    assert times.at(at(2, 18)) == Window(at(2, 18), at(2, 23), at(2, 18))
    assert times.next_change(at(2, 18)) == at(2, 23)
    assert (times.at(at(2, 23)), times.next_change(at(2, 23))) == (None, at(3, 18))


def test_times_start_again_when_the_clock_goes_back() -> None:
    times = Times(Schedule(hours=EVENING), False, FRIDAY)
    assert times.at(at(3, 19)) is not None
    assert times.at(at(2, 19)) == Window(at(2, 18), at(2, 23), at(2, 18))


def test_nothing_changes_after_the_last_window() -> None:
    once = Times(Schedule(OnDate(date(2026, 10, 2)), EVENING), True, FRIDAY)
    assert once.next_change(at(2, 23)) is None
    forever = Times(Schedule(OnDate(date(2026, 10, 2)), Moment(time(15))), False, FRIDAY)
    assert forever.next_change(at(5, 9)) is None


# What the interface asks


@pytest.mark.parametrize(
    ("condition", "perennial", "now", "expected"),
    [
        ("quando apro Figma", False, at(2, 12), True),
        ("alle 15", False, at(2, 15), True),
        ("domani alle 15", False, at(3, 15), False),
        ("stasera", False, at(2, 19), False),
        ("stasera quando apro Teams", False, at(2, 19), False),
        ("stasera quando apro Teams", True, at(2, 19), True),
        ("quando apro Teams la sera fino a domenica", False, at(4, 22), True),
        ("alle 15 fino a domenica", False, at(4, 15), False),
        ("una volta al mese", False, at(20, 9), True),
    ],
    ids=[
        "no time",
        "a moment that comes back",
        "a date",
        "tonight",
        "tonight, with an app",
        "tonight, perennial, with an app",
        "a slot still holding",
        "the last moment of a period",
        "a frequency",
    ],
)
def test_alla_prossima_volta_needs_a_next_unit(
    condition: str, perennial: bool, now: datetime, expected: bool
) -> None:
    clock = SimulatedClock(round(now.replace(tzinfo=UTC).timestamp() * 1000))
    assert next_occasion(revision(condition, perennial), clock, clock.now()) is expected


@pytest.mark.parametrize(
    ("condition", "rings", "day"),
    [
        ("alle 15", at(2, 15, 5), 2),
        ("alle 15", at(3, 9), 2),
        ("alle 15", at(3, 15), 3),
        ("oggi alle 15", at(4, 9), 2),
        ("alle 2", at(3, 2, 1), 2),
        ("la sera", at(3, 19), 3),
    ],
    ids=[
        "on time",
        "late, the next morning",
        "the next instance",
        "two days late, with a date",
        "at night, the day before's",
        "a slot",
    ],
)
def test_an_alert_rings_for_the_day_of_its_instance(
    condition: str, rings: datetime, day: int
) -> None:
    clock = SimulatedClock(0)
    moment = round(rings.replace(tzinfo=UTC).timestamp() * 1000)
    assert instance_day(revision(condition), clock, moment) == date(2026, 10, day)


def test_an_alert_without_a_window_has_no_instance_day() -> None:
    clock = SimulatedClock(0)
    before = round(at(2, 12).replace(tzinfo=UTC).timestamp() * 1000)
    assert instance_day(revision("alle 15"), clock, before) is None
    assert instance_day(revision("quando apro Figma"), clock, before) is None


def test_a_period_is_over_after_its_last_day() -> None:
    weekend = Schedule(period=Period(date(2026, 10, 2), date(2026, 10, 4)))
    assert not ended(weekend, at(5, 3, 59))
    assert ended(weekend, at(5, 4))
    assert not ended(Schedule(hours=EVENING), at(30, 12))
    assert not ended(None, at(30, 12))
