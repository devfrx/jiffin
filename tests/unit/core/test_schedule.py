from datetime import UTC, date, datetime, time, timedelta, timezone
from itertools import islice

import pytest

from jiffin.core.schedule import (
    EveryNWeeks,
    Frequency,
    Instance,
    Moment,
    MonthDay,
    MonthWeekday,
    OnDate,
    Period,
    Schedule,
    Slot,
    Unit,
    Weekdays,
    YearDay,
    frequency_period,
    instances,
    jiffin_day,
)


def at(day: int, hour: int, minute: int = 0, month: int = 10) -> datetime:
    """A wall-clock time of 2026, without a zone, as the calendar gives them."""
    return datetime.combine(date(2026, month, day), time(hour, minute))


FRIDAY = at(2, 10)


def first(schedule: Schedule, count: int, since: datetime = FRIDAY) -> list[Instance]:
    return list(islice(instances(schedule, since), count))


def days(schedule: Schedule, count: int, since: datetime = FRIDAY) -> list[date]:
    return [instance.day for instance in first(schedule, count, since)]


def test_a_jiffin_day_starts_at_four() -> None:
    assert jiffin_day(at(3, 3, 59)) == date(2026, 10, 2)
    assert jiffin_day(at(3, 4)) == date(2026, 10, 3)


def test_a_whole_day_runs_from_four_to_four() -> None:
    assert first(Schedule(OnDate(date(2026, 10, 3))), 2) == [
        Instance(date(2026, 10, 3), at(3, 4), at(4, 4))
    ]


def test_a_slot_that_ends_after_midnight_ends_the_next_calendar_day() -> None:
    late = Schedule(hours=Slot(time(23), time(4)))
    night = Schedule(hours=Slot(time(23), time(6)))
    assert first(late, 1) == [Instance(date(2026, 10, 2), at(2, 23), at(3, 4))]
    assert first(night, 1) == [Instance(date(2026, 10, 2), at(2, 23), at(3, 6))]


def test_hours_before_four_are_on_the_next_calendar_day() -> None:
    after_midnight = Schedule(hours=Slot(time(0), time(4)))
    two = Schedule(OnDate(date(2026, 10, 3)), Moment(time(2)))
    assert first(after_midnight, 1) == [Instance(date(2026, 10, 2), at(3, 0), at(3, 4))]
    assert first(two, 1) == [Instance(date(2026, 10, 3), at(4, 2), at(4, 2))]


def test_the_instance_under_way_comes_first() -> None:
    late = Schedule(hours=Slot(time(22), time(2)))
    assert first(late, 2, since=at(3, 1)) == [
        Instance(date(2026, 10, 2), at(2, 22), at(3, 2)),
        Instance(date(2026, 10, 3), at(3, 22), at(4, 2)),
    ]


def test_an_instance_is_over_once_it_has_ended_a_moment_once_it_has_passed() -> None:
    evening = Schedule(hours=Slot(time(18), time(23)))
    three = Schedule(hours=Moment(time(15)))
    assert days(evening, 1, since=at(2, 23)) == [date(2026, 10, 3)]
    assert days(three, 1, since=at(2, 15)) == [date(2026, 10, 2)]
    assert days(three, 1, since=at(2, 15, 1)) == [date(2026, 10, 3)]


def test_a_date_has_one_instance() -> None:
    once = Schedule(OnDate(date(2026, 10, 5)), Moment(time(10)))
    assert first(once, 2) == [Instance(date(2026, 10, 5), at(5, 10), at(5, 10))]
    assert first(once, 1, since=at(5, 11)) == []


def test_weekdays_come_back_every_week() -> None:
    weekend = Schedule(Weekdays(frozenset({5, 6})))
    assert days(weekend, 3) == [date(2026, 10, 3), date(2026, 10, 4), date(2026, 10, 10)]


def test_a_period_holds_its_days_and_both_ends() -> None:
    museum = Schedule(period=Period(date(2026, 10, 10), date(2026, 10, 12)))
    instances_ = first(museum, 5)
    assert [instance.day for instance in instances_] == [
        date(2026, 10, 10),
        date(2026, 10, 11),
        date(2026, 10, 12),
    ]
    assert (instances_[0].start, instances_[-1].end) == (at(10, 4), at(13, 4))


def test_a_period_already_started_holds_from_now() -> None:
    week = Schedule(period=Period(date(2026, 9, 28), date(2026, 10, 4)))
    assert days(week, 5) == [date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 4)]


def test_a_weekday_every_two_weeks_starts_from_its_first() -> None:
    other_monday = Schedule(EveryNWeeks(0, 2, date(2026, 10, 5)))
    assert days(other_monday, 3) == [date(2026, 10, 5), date(2026, 10, 19), date(2026, 11, 2)]
    assert days(other_monday, 1, since=at(20, 10)) == [date(2026, 11, 2)]


def test_a_weekday_of_the_month_is_the_nth_or_the_last() -> None:
    first_monday = Schedule(MonthWeekday(0, 1))
    last_friday = Schedule(MonthWeekday(4, -1))
    assert days(first_monday, 3) == [date(2026, 10, 5), date(2026, 11, 2), date(2026, 12, 7)]
    assert days(last_friday, 3) == [date(2026, 10, 30), date(2026, 11, 27), date(2026, 12, 25)]


def test_a_day_of_the_month_is_the_last_day_of_a_shorter_month() -> None:
    thirty_first = Schedule(MonthDay(31))
    last = Schedule(MonthDay(-1))
    expected = [
        date(2026, 10, 31),
        date(2026, 11, 30),
        date(2026, 12, 31),
        date(2027, 1, 31),
        date(2027, 2, 28),
    ]
    assert days(thirty_first, 5) == expected
    assert days(last, 5) == expected


def test_29_february_is_the_28th_in_other_years() -> None:
    leap_day = Schedule(YearDay(2, 29))
    assert days(leap_day, 2) == [date(2027, 2, 28), date(2028, 2, 29)]


@pytest.mark.parametrize(
    ("frequency", "day", "period"),
    [
        (Frequency(2, Unit.WEEK, date(2026, 10, 2)), date(2026, 10, 15), (2, 15)),
        (Frequency(2, Unit.WEEK, date(2026, 10, 2)), date(2026, 10, 16), (16, 29)),
        (Frequency(3, Unit.DAY, date(2026, 10, 2)), date(2026, 10, 6), (5, 7)),
    ],
)
def test_the_periods_of_a_frequency_follow_each_other_from_the_day_written(
    frequency: Frequency, day: date, period: tuple[int, int]
) -> None:
    assert frequency_period(frequency, day) == Period(
        date(2026, 10, period[0]), date(2026, 10, period[1])
    )


def test_a_month_from_the_31st_ends_on_the_last_day_of_a_shorter_month() -> None:
    monthly = Frequency(1, Unit.MONTH, date(2027, 1, 31))
    assert frequency_period(monthly, date(2027, 2, 27)) == Period(
        date(2027, 1, 31), date(2027, 2, 27)
    )
    assert frequency_period(monthly, date(2027, 2, 28)) == Period(
        date(2027, 2, 28), date(2027, 3, 30)
    )


def test_a_year_from_29_february() -> None:
    yearly = Frequency(1, Unit.YEAR, date(2028, 2, 29))
    assert frequency_period(yearly, date(2029, 3, 1)) == Period(
        date(2029, 2, 28), date(2030, 2, 27)
    )


def test_only_the_wall_clock_of_a_time_counts() -> None:
    zone = timezone(timedelta(hours=2))
    evening = Schedule(hours=Slot(time(18), time(23)))
    assert first(evening, 1, since=FRIDAY.replace(tzinfo=zone)) == first(evening, 1)
    assert first(evening, 1, since=FRIDAY.replace(tzinfo=UTC)) == first(evening, 1)
