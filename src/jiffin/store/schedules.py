"""A `Schedule` as JSON, for the `schedule` column of `revision` (ADR-0020).

The shape is the store's, on the types of `core.schedule`, and the same as the time cases in
`tests/fixtures/time`, save that every day is written as its seven weekdays:

    {"days": {"weekdays": [0, 2]}, "hours": {"slot": ["18:00", "23:00"]},
     "period": ["2026-10-10", "2026-10-20"], "frequency": {"count": 2, "unit": "week",
     "first": "2026-10-03"}}

`days` is one of {"weekdays": [...]}, {"date": d}, {"every_weeks": {"weekday", "weeks",
"first"}}, {"month_weekday": {"weekday", "nth"}}, {"month_day": n} and {"year_day": {"month",
"day"}}, with 0 for Monday and -1 for the last; `hours` is null for the whole day, a slot or a
moment; `period` and `frequency` may be null.
"""

import json
from datetime import date, time
from typing import Any

from jiffin.core.schedule import (
    Days,
    EveryNWeeks,
    Frequency,
    Hours,
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


def dumps(schedule: Schedule) -> str:
    period, frequency = schedule.period, schedule.frequency
    return json.dumps(
        {
            "days": _days(schedule.days),
            "hours": _hours(schedule.hours),
            "period": None
            if period is None
            else [period.first.isoformat(), period.last.isoformat()],
            "frequency": None
            if frequency is None
            else {
                "count": frequency.count,
                "unit": frequency.unit.value,
                "first": frequency.first.isoformat(),
            },
        }
    )


def loads(text: str) -> Schedule:
    found = json.loads(text)
    period, frequency = found["period"], found["frequency"]
    return Schedule(
        _days_of(found["days"]),
        _hours_of(found["hours"]),
        None if period is None else Period(*map(date.fromisoformat, period)),
        None
        if frequency is None
        else Frequency(
            frequency["count"], Unit(frequency["unit"]), date.fromisoformat(frequency["first"])
        ),
    )


def _days(days: Days) -> dict[str, Any]:
    match days:
        case Weekdays(weekdays):
            return {"weekdays": sorted(weekdays)}
        case OnDate(day):
            return {"date": day.isoformat()}
        case EveryNWeeks(weekday, weeks, first):
            return {"every_weeks": {"weekday": weekday, "weeks": weeks, "first": first.isoformat()}}
        case MonthWeekday(weekday, nth):
            return {"month_weekday": {"weekday": weekday, "nth": nth}}
        case MonthDay(day):
            return {"month_day": day}
        case YearDay(month, day):
            return {"year_day": {"month": month, "day": day}}


def _days_of(found: dict[str, Any]) -> Days:
    [(kind, value)] = found.items()
    match kind:
        case "weekdays":
            return Weekdays(frozenset(value))
        case "date":
            return OnDate(date.fromisoformat(value))
        case "every_weeks":
            first = date.fromisoformat(value["first"])
            return EveryNWeeks(value["weekday"], value["weeks"], first)
        case "month_weekday":
            return MonthWeekday(value["weekday"], value["nth"])
        case "month_day":
            return MonthDay(value)
        case "year_day":
            return YearDay(value["month"], value["day"])
    raise ValueError(f"days of an unknown kind: {kind}")


def _hours(hours: Hours | None) -> dict[str, Any] | None:
    match hours:
        case None:
            return None
        case Slot(start, end):
            return {"slot": [_clock(start), _clock(end)]}
        case Moment(at):
            return {"moment": _clock(at)}


def _hours_of(found: dict[str, Any] | None) -> Hours | None:
    if found is None:
        return None
    if "slot" in found:
        start, end = found["slot"]
        return Slot(time.fromisoformat(start), time.fromisoformat(end))
    return Moment(time.fromisoformat(found["moment"]))


def _clock(at: time) -> str:
    return at.isoformat(timespec="minutes")
