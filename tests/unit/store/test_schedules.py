"""A `Schedule` as JSON, in the `schedule` column of `revision` (ADR-0020)."""

import json
from datetime import date, time

import pytest

from jiffin.core.schedule import (
    EVERY_DAY,
    EveryNWeeks,
    Frequency,
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
)
from jiffin.store import schedules

FIRST = date(2026, 10, 2)


@pytest.mark.parametrize(
    "schedule",
    [
        Schedule(),
        Schedule(Weekdays(frozenset({5, 6})), Slot(time(23), time(4))),
        Schedule(OnDate(FIRST), Moment(time(15, 30))),
        Schedule(EveryNWeeks(0, 2, date(2026, 10, 5))),
        Schedule(MonthWeekday(4, -1), Moment(time(9))),
        Schedule(MonthDay(-1)),
        Schedule(YearDay(2, 29)),
        Schedule(EVERY_DAY, Slot(time(18), time(23)), Period(FIRST, date(2026, 10, 4))),
        Schedule(frequency=Frequency(2, Unit.WEEK, FIRST)),
    ],
    ids=[
        "every day",
        "weekend nights",
        "a date and a moment",
        "every other Monday",
        "the last Friday of the month",
        "the end of the month",
        "29 February",
        "a period",
        "a frequency",
    ],
)
def test_every_kind_of_time_comes_back(schedule: Schedule) -> None:
    assert schedules.loads(schedules.dumps(schedule)) == schedule


def test_the_shape_is_the_time_cases_one() -> None:
    written = schedules.dumps(Schedule(Weekdays(frozenset({4, 0})), Slot(time(18), time(23))))
    assert json.loads(written) == {
        "days": {"weekdays": [0, 4]},
        "hours": {"slot": ["18:00", "23:00"]},
        "period": None,
        "frequency": None,
    }


def test_days_of_an_unknown_kind_are_refused() -> None:
    text = json.dumps({"days": {"fortnight": 1}, "hours": None, "period": None, "frequency": None})
    with pytest.raises(ValueError, match="unknown kind"):
        schedules.loads(text)
