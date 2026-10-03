"""The time of a condition, as `read` gives it (ADR-0020).

The case files in tests/fixtures/time are #80's synthetic conditions: development.json, the 45 the
grammar was built on; held_out.json and held_out_2.json, written by sub-agents from the decided
meanings only. A case has:

- `condition`, and `created`, when it was written: Friday 2026-10-02 at 10:00 when missing;
- `time`: null for no time; "unclear" for time words not understood, which `unclear` names; or the
  schedule, as `days` ("every", {"weekdays": [...]}, {"date": d}, {"every_weeks": {"weekday",
  "weeks", "first"}}, {"month_weekday": {"weekday", "nth"}}, {"month_day": n}, {"year_day":
  {"month", "day"}}; -1 is the last), `hours` ("all_day", {"slot": [start, end]}, {"moment": at})
  and, if any, `period` ([first, last]), `frequency` ({"count", "unit", "first"}) and `past`;
- `remainder`: what the engine rewrites; the condition itself, byte for byte, without a time or
  with one not understood;
- `recurring`: true when words tick "Ogni volta" by themselves;
- `basis`: why. Its numbers are the meanings #80 measured: 1 the Jiffin day starts at 04:00; 2
  the parts of the day; 3 open slots start or end at 04:00; 4 moments on a 24-hour clock, moved
  by the words of the day; 5 the weekend and the working days; 6 a weekday without article is
  the next one, with it every week; 7 "oggi", "domani", "tra 3 giorni", "stasera" count from
  the day written; 8 "tra 2 ore" from the moment; 9 a date already past is next year's; 10 a time
  over when written is past; 11 negated days are the other days; 12 a moment before 04:00 is on
  the next calendar day;
- `known_failure`: why the case still fails, when it does.
"""

import json
import statistics
import time as clock
from datetime import UTC, date, datetime, time, timedelta
from itertools import islice
from pathlib import Path
from typing import Any

import pytest

from jiffin.core.meanings import Reading, read
from jiffin.core.schedule import (
    EVERY_DAY,
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
    frequency_period,
    instances,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "time"
FRIDAY = datetime.fromisoformat("2026-10-02T10:00")
"""Local times are wall-clock times, without a zone, as in the case files."""
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def cases() -> list[Any]:
    found = []
    for name in ("development.json", "held_out.json", "held_out_2.json"):
        for case in json.loads((FIXTURES / name).read_text(encoding="utf-8"))["cases"]:
            failure = case.get("known_failure")
            marks = [pytest.mark.xfail(reason=failure, strict=True)] if failure else []
            found.append(pytest.param(case, id=case["id"], marks=marks))
    return found


def created(case: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(case["created"]) if "created" in case else FRIDAY


def schedule(time_: dict[str, Any]) -> Schedule:
    return Schedule(
        days_of(time_["days"]),
        hours_of(time_["hours"]),
        Period(*map(date.fromisoformat, time_["period"])) if "period" in time_ else None,
        frequency_of(time_["frequency"]) if "frequency" in time_ else None,
    )


def days_of(days: Any) -> Days:
    if days == "every":
        return EVERY_DAY
    (kind, value), *_ = days.items()
    match kind:
        case "weekdays":
            return Weekdays(frozenset(WEEKDAYS.index(day) for day in value))
        case "date":
            return OnDate(date.fromisoformat(value))
        case "every_weeks":
            first = date.fromisoformat(value["first"])
            return EveryNWeeks(WEEKDAYS.index(value["weekday"]), value["weeks"], first)
        case "month_weekday":
            return MonthWeekday(WEEKDAYS.index(value["weekday"]), value["nth"])
        case "month_day":
            return MonthDay(value)
        case "year_day":
            return YearDay(value["month"], value["day"])
    raise ValueError(kind)


def hours_of(hours: Any) -> Hours | None:
    if hours == "all_day":
        return None
    if "slot" in hours:
        start, end = hours["slot"]
        return Slot(time.fromisoformat(start), time.fromisoformat(end))
    return Moment(time.fromisoformat(hours["moment"]))


def frequency_of(frequency: dict[str, Any]) -> Frequency:
    first = date.fromisoformat(frequency["first"])
    return Frequency(frequency["count"], Unit(frequency["unit"]), first)


def words(reading: Reading, condition: str) -> list[str]:
    return [condition[start:end] for start, end in reading.unclear]


def first_days(reading: Reading, count: int, since: datetime = FRIDAY) -> list[date]:
    assert reading.schedule is not None
    return [instance.day for instance in islice(instances(reading.schedule, since), count)]


@pytest.mark.parametrize("case", cases())
def test_a_case_of_80_reads_as_expected(case: dict[str, Any]) -> None:
    condition = case["condition"]
    reading = read(condition, created(case))
    if case["time"] == "unclear":
        assert reading.schedule is None
        assert words(reading, condition) == case["unclear"]
    elif case["time"] is None:
        assert (reading.schedule, reading.unclear) == (None, ())
    else:
        assert reading.schedule == schedule(case["time"])
        assert reading.past == case["time"].get("past", False)
    assert reading.remainder == case["remainder"]
    assert reading.recurring == case.get("recurring", False)


# What #90 decided


def test_a_time_not_understood_names_its_words_wherever_they_are() -> None:
    condition = "verso sera, quando apro Telegram, o in pausa pranzo"
    reading = read(condition, FRIDAY)
    assert reading == Reading(None, condition, reading.unclear)
    assert words(reading, condition) == ["verso sera", "in pausa pranzo"]


@pytest.mark.parametrize(
    ("condition", "unclear"),
    [
        ("quando apro Excel il 31 aprile", ["il 31 aprile"]),
        ("lunedì 6 ottobre", ["lunedì 6 ottobre"]),
        ("alle 25", ["alle 25"]),
        ("ogni mese il 15", ["il 15"]),
        ("dal 10 al 20", ["dal 10 al 20"]),
        ("il 29 febbraio", ["il 29 febbraio"]),
        ("il prossimo lunedì", ["prossimo lunedì"]),
        ("intorno alle 9", ["intorno alle 9"]),
        ("da domani", ["da domani"]),
        ("ogni ora", ["ogni ora"]),
        ("entro un'ora", ["entro un'ora"]),
        ("tra un anno", ["tra un anno"]),
        ("domani fino a domenica", ["domani fino a domenica"]),
        ("domani tra 2 ore", ["domani tra 2 ore"]),
        ("stasera alle 7 di mattina", ["stasera alle 7 di mattina"]),
        ("lunedì e martedì", ["lunedì e martedì"]),
        ("alle 9 o alle 10", ["alle 9", "alle 10"]),
        ("una volta al mese, il 5 ottobre", ["una volta al mese", "il 5 ottobre"]),
        ("quando apro Excel prima del 20 ottobre", ["prima del 20 ottobre"]),
        ("prima di lunedì", ["prima di lunedì"]),
        ("quando apro Teams il weekend prossimo", ["il weekend prossimo"]),
        ("verso sera tardi", ["verso sera tardi"]),
        ("quando lavoro un giorno sì e uno no", ["sì e uno no"]),
        ("quando apro Excel per un paio d'ore", ["per un paio d'ore"]),
        (
            "tranne lunedì, martedì, mercoledì, giovedì, venerdì, sabato e domenica",
            ["tranne lunedì, martedì, mercoledì, giovedì, venerdì, sabato e domenica"],
        ),
        # Without these, the calendar would look for the next day for ever.
        ("ogni 0 settimane il lunedì", ["ogni 0 settimane il lunedì"]),
        ("ogni 0 giorni", ["ogni 0 giorni"]),
        ("per 0 giorni", ["per 0 giorni"]),
    ],
)
def test_words_that_do_not_make_a_decided_time_are_not_understood(
    condition: str, unclear: list[str]
) -> None:
    reading = read(condition, FRIDAY)
    assert (reading.schedule, reading.remainder) == (None, condition)
    assert words(reading, condition) == unclear


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("il 5/10/27", Schedule(OnDate(date(2027, 10, 5)))),
        ("il 1º ottobre", Schedule(OnDate(date(2027, 10, 1)))),
        ("tra 2 ore e mezza", Schedule(OnDate(date(2026, 10, 2)), Moment(time(12, 30)))),
        ("tra un'ora e 15 minuti", Schedule(OnDate(date(2026, 10, 2)), Moment(time(11, 15)))),
        ("tra un paio di giorni", Schedule(OnDate(date(2026, 10, 4)))),
        ("fino a domani", Schedule(period=Period(date(2026, 10, 2), date(2026, 10, 3)))),
        ("per una settimana", Schedule(period=Period(date(2026, 10, 2), date(2026, 10, 8)))),
        ("da lunedì al venerdì", Schedule(period=Period(date(2026, 10, 5), date(2026, 10, 9)))),
        (
            "ogni due settimane il lunedì e il giovedì",
            Schedule(
                Weekdays(frozenset({0, 3})), frequency=Frequency(2, Unit.WEEK, date(2026, 10, 2))
            ),
        ),
        (
            "dal lunedì al venerdì sera",
            Schedule(Weekdays(frozenset(range(5))), Slot(time(18), time(23))),
        ),
        ("tutti i giorni tranne il sabato", Schedule(Weekdays(frozenset({0, 1, 2, 3, 4, 6})))),
        ("la sera tra le 9 e le 11", Schedule(hours=Slot(time(21), time(23)))),
        ("tra le 2 e le 4 del pomeriggio", Schedule(hours=Slot(time(14), time(16)))),
        ("dalle 22 in poi", Schedule(hours=Slot(time(22), time(4)))),
        ("alle 12 di notte", Schedule(hours=Moment(time(0)))),
        ("alle 9 e dieci", Schedule(hours=Moment(time(9, 10)))),
        ("alle 7 meno 10", Schedule(hours=Moment(time(6, 50)))),
        ("a mezzanotte meno un quarto", Schedule(hours=Moment(time(23, 45)))),
    ],
)
def test_more_forms_of_the_decided_meanings(condition: str, expected: Schedule) -> None:
    reading = read(condition, FRIDAY)
    assert (reading.schedule, reading.remainder) == (expected, "")


@pytest.mark.parametrize(
    ("condition", "remainder"),
    [
        ("quando apro Excel e il lunedì", "quando apro Excel"),
        ("e quando apro Excel la sera", "quando apro Excel"),
        ("nel pomeriggio di domani", ""),
        ("quando apro il report di domani", "quando apro il report"),
        ("domani a casa", "a casa"),
        ("a casa la sera", "a casa"),
        ("il treno delle 7:40, prima delle 9", "il treno delle 7:40"),
        ("quando apro Outlook  (lunedì)  e  Teams", "quando apro Outlook e Teams"),
    ],
)
def test_the_remainder_loses_what_the_time_leaves_hanging(condition: str, remainder: str) -> None:
    assert read(condition, FRIDAY).remainder == remainder


def test_stanotte_is_the_night_of_today_and_before_four_the_night_under_way() -> None:
    tonight = Schedule(OnDate(date(2026, 10, 2)), Slot(time(23), time(6)))
    assert read("stanotte", FRIDAY).schedule == tonight
    under_way = read("stanotte", datetime.fromisoformat("2026-10-03T02:00"))
    assert (under_way.schedule, under_way.past) == (tonight, False)


def test_hours_before_four_belong_to_the_day_before() -> None:
    saturday_night = Schedule(OnDate(date(2026, 10, 3)), Moment(time(2)))
    friday_night = Schedule(OnDate(date(2026, 10, 2)), Moment(time(2)))
    assert read("domani alle 2 di notte", FRIDAY).schedule == saturday_night
    assert read("stanotte alle 2", FRIDAY).schedule == friday_night
    sunday_at_two = next(instances(saturday_night, FRIDAY)).start
    saturday_at_two = next(instances(friday_night, FRIDAY)).start
    assert sunday_at_two == datetime.fromisoformat("2026-10-04T02:00")
    assert saturday_at_two == datetime.fromisoformat("2026-10-03T02:00")


# The periods of #91


@pytest.mark.parametrize(
    ("condition", "written", "expected"),
    [
        (
            "dal 10 al 20 ottobre",
            FRIDAY,
            Schedule(period=Period(date(2026, 10, 10), date(2026, 10, 20))),
        ),
        ("fino a domenica", FRIDAY, Schedule(period=Period(date(2026, 10, 2), date(2026, 10, 4)))),
        (
            "fino a domenica",
            datetime.fromisoformat("2026-10-04T10:00"),
            Schedule(period=Period(date(2026, 10, 4), date(2026, 10, 11))),
        ),
        ("entro domenica", FRIDAY, Schedule(period=Period(date(2026, 10, 2), date(2026, 10, 4)))),
        (
            "dal 1 al 5 ottobre",
            datetime.fromisoformat("2026-10-10T10:00"),
            Schedule(period=Period(date(2027, 10, 1), date(2027, 10, 5))),
        ),
        (
            "dal 28 dicembre al 3 gennaio",
            FRIDAY,
            Schedule(period=Period(date(2026, 12, 28), date(2027, 1, 3))),
        ),
        ("fino al 20", FRIDAY, Schedule(period=Period(date(2026, 10, 2), date(2026, 10, 20)))),
        (
            "fino al 20",
            datetime.fromisoformat("2026-10-25T10:00"),
            Schedule(period=Period(date(2026, 10, 25), date(2026, 11, 20))),
        ),
        (
            "fino al 20",
            datetime.fromisoformat("2026-10-20T10:00"),
            Schedule(period=Period(date(2026, 10, 20), date(2026, 10, 20))),
        ),
        ("per tre giorni", FRIDAY, Schedule(period=Period(date(2026, 10, 2), date(2026, 10, 4)))),
        (
            "per tre giorni",
            datetime.fromisoformat("2026-10-03T01:00"),
            Schedule(period=Period(date(2026, 10, 2), date(2026, 10, 4))),
        ),
        ("questa settimana", FRIDAY, Schedule(period=Period(date(2026, 10, 2), date(2026, 10, 4)))),
        (
            "la prossima settimana",
            FRIDAY,
            Schedule(period=Period(date(2026, 10, 5), date(2026, 10, 11))),
        ),
        (
            "da lunedì a giovedì",
            FRIDAY,
            Schedule(period=Period(date(2026, 10, 5), date(2026, 10, 8))),
        ),
        ("dal lunedì al giovedì", FRIDAY, Schedule(Weekdays(frozenset(range(4))))),
        (
            "dal 10 al 20 ottobre dopo le 23",
            FRIDAY,
            Schedule(
                hours=Slot(time(23), time(4)),
                period=Period(date(2026, 10, 10), date(2026, 10, 20)),
            ),
        ),
        (
            "il lunedì fino al 20 ottobre",
            FRIDAY,
            Schedule(
                Weekdays(frozenset({0})), period=Period(date(2026, 10, 2), date(2026, 10, 20))
            ),
        ),
        (
            "fino a martedì 20 ottobre",
            FRIDAY,
            Schedule(period=Period(date(2026, 10, 2), date(2026, 10, 20))),
        ),
    ],
)
def test_a_period_holds_both_its_ends(
    condition: str, written: datetime, expected: Schedule
) -> None:
    reading = read(condition, written)
    assert (reading.schedule, reading.remainder, reading.past) == (expected, "", False)


def test_a_period_already_started_holds_from_now() -> None:
    reading = read("dal 1 al 20 ottobre", FRIDAY)
    assert reading.schedule == Schedule(period=Period(date(2026, 10, 1), date(2026, 10, 20)))
    assert first_days(reading, 1) == [date(2026, 10, 2)]


def test_a_period_with_its_year_can_be_past() -> None:
    assert read("dal 1 al 5 ottobre 2026", datetime.fromisoformat("2026-10-10T10:00")).past


# The recurrences of #92, its table: written on Friday 2 October 2026 at 10:00


@pytest.mark.parametrize(
    ("condition", "remainder", "first"),
    [
        (
            "quando apro SAP il primo lunedì del mese",
            "quando apro SAP",
            [date(2026, 10, 5), date(2026, 11, 2), date(2026, 12, 7)],
        ),
        (
            "l'ultimo venerdì del mese",
            "",
            [date(2026, 10, 30), date(2026, 11, 27), date(2026, 12, 25)],
        ),
        (
            "il 31 di ogni mese",
            "",
            [
                date(2026, 10, 31),
                date(2026, 11, 30),
                date(2026, 12, 31),
                date(2027, 1, 31),
                date(2027, 2, 28),
            ],
        ),
        (
            "quando apro il foglio delle spese a fine mese",
            "quando apro il foglio delle spese",
            [date(2026, 10, 31), date(2026, 11, 30)],
        ),
        (
            "un lunedì sì e uno no",
            "",
            [date(2026, 10, 5), date(2026, 10, 19), date(2026, 11, 2)],
        ),
        ("il 29 febbraio di ogni anno", "", [date(2027, 2, 28), date(2028, 2, 29)]),
    ],
)
def test_a_recurrence_of_92_holds_its_days_and_ticks_ogni_volta(
    condition: str, remainder: str, first: list[date]
) -> None:
    reading = read(condition, FRIDAY)
    assert (reading.remainder, reading.recurring, reading.past) == (remainder, True, False)
    assert first_days(reading, len(first)) == first


def test_a_frequency_rings_once_per_period_counted_from_the_day_written() -> None:
    reading = read("quando apro Dropbox ogni due settimane", FRIDAY)
    frequency = Frequency(2, Unit.WEEK, date(2026, 10, 2))
    assert reading.schedule == Schedule(frequency=frequency)
    assert (reading.remainder, reading.recurring) == ("quando apro Dropbox", True)
    starts = [
        frequency_period(frequency, FRIDAY.date() + timedelta(weeks=2 * n)).first for n in range(4)
    ]
    assert starts == [date(2026, 10, 2), date(2026, 10, 16), date(2026, 10, 30), date(2026, 11, 13)]


def test_il_lunedi_is_every_monday_and_does_not_tick_ogni_volta() -> None:
    reading = read("quando apro Teams il lunedì", FRIDAY)
    assert reading.schedule == Schedule(Weekdays(frozenset({0})))
    assert not reading.recurring


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("ogni tre giorni", Schedule(frequency=Frequency(3, Unit.DAY, date(2026, 10, 2)))),
        ("una volta al mese", Schedule(frequency=Frequency(1, Unit.MONTH, date(2026, 10, 2)))),
        ("ogni anno", Schedule(frequency=Frequency(1, Unit.YEAR, date(2026, 10, 2)))),
        (
            "una volta alla settimana, la sera",
            Schedule(
                hours=Slot(time(18), time(23)),
                frequency=Frequency(1, Unit.WEEK, date(2026, 10, 2)),
            ),
        ),
        (
            "ogni due settimane il lunedì",
            Schedule(EveryNWeeks(0, 2, date(2026, 10, 5))),
        ),
        ("ogni giorno", Schedule(EVERY_DAY)),
        ("il 15 del mese", Schedule(MonthDay(15))),
        ("il primo del mese", Schedule(MonthDay(1))),
    ],
)
def test_the_other_forms_of_92(condition: str, expected: Schedule) -> None:
    reading = read(condition, FRIDAY)
    assert (reading.schedule, reading.recurring) == (expected, True)


def test_a_weekday_every_two_weeks_starts_today_when_today_is_the_day() -> None:
    reading = read("un venerdì sì e uno no", FRIDAY)
    assert reading.schedule == Schedule(EveryNWeeks(4, 2, date(2026, 10, 2)))


def test_ogni_volta_ticks_the_box_but_is_not_a_time() -> None:
    reading = read("ogni volta che apro Discord", FRIDAY)
    assert reading == Reading(None, "ogni volta che apro Discord", recurring=True)


def test_ogni_ticks_the_box_even_when_the_time_is_not_understood() -> None:
    reading = read("ogni lunedì verso sera", FRIDAY)
    assert (reading.schedule, reading.recurring) == (None, True)


# What every reading keeps


@pytest.mark.parametrize(
    "condition",
    [
        "  quando apro  Excel, ma non per lavoro ",
        "quando supero il 50% della batteria",
        # A known limit: a time word capitalized after the first word is a name.
        "quando apro Excel Lunedì",
    ],
)
def test_a_condition_without_time_keeps_its_bytes(condition: str) -> None:
    assert read(condition, FRIDAY) == Reading(None, condition)


def test_a_day_a_month_does_not_have_is_not_understood() -> None:
    reading = read("fino al 31", datetime.fromisoformat("2026-11-02T10:00"))
    assert (reading.schedule, words(reading, "fino al 31")) == (None, ["fino al 31"])


def test_a_time_over_when_written_is_past_to_the_minute() -> None:
    assert read("oggi alle 9", FRIDAY).past
    assert not read("oggi alle 10", FRIDAY.replace(second=30)).past
    assert read("il 5 ottobre 2025", FRIDAY).past


def test_only_the_wall_clock_of_the_writing_counts() -> None:
    aware = FRIDAY.replace(tzinfo=UTC)
    assert read("tra 2 ore", aware) == read("tra 2 ore", FRIDAY)


def test_reading_takes_under_a_millisecond() -> None:
    conditions = [(case.values[0]["condition"], created(case.values[0])) for case in cases()]
    took = []
    for condition, written in conditions:
        start = clock.perf_counter_ns()
        read(condition, written)
        took.append(clock.perf_counter_ns() - start)
    assert statistics.median(took) < 1_000_000
