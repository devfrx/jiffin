"""The words of a time, as the interface writes them: the examples decided on the map (#84, #91,
#92), then the forms deduced from their rules."""

from datetime import date, datetime, time

import pytest

from jiffin.core.meanings import read
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
from jiffin.ui.words import passed, when


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A wall-clock time of October 2026, as the clock of the creation window gives it."""
    return datetime.combine(date(2026, 10, day), time(hour, minute))


FRIDAY = date(2026, 10, 2)
"""Venerdì 2 ottobre 2026, the day the map's examples were written."""
WRITTEN = at(2, 10)


def written(condition: str, written_at: datetime = WRITTEN) -> Schedule:
    """The time of a condition, as `core` reads it."""
    schedule = read(condition, written_at).schedule
    assert schedule is not None
    return schedule


def week(*weekdays: int) -> Weekdays:
    return Weekdays(frozenset(weekdays))


@pytest.mark.parametrize(
    ("condition", "perennial", "line"),
    [
        # #84
        ("quando apro Claude dopo le 23", True, "Ogni giorno dalle 23:00 alle 04:00"),
        ("quando apro Claude dopo le 23", False, "Dalle 23:00 alle 04:00"),
        ("oggi alle 9", False, "Oggi, venerdì 2 ottobre, alle 09:00"),
        ("domani alle 15", False, "Domani, sabato 3 ottobre, alle 15:00"),
        ("lunedì alle 10", False, "Lunedì 5 ottobre, alle 10:00"),
        ("il 5 ottobre 2027", False, "Martedì 5 ottobre 2027"),
        ("il lunedì", False, "Ogni lunedì"),
        ("nei giorni feriali", False, "Dal lunedì al venerdì"),
        ("nel weekend", False, "Il sabato e la domenica"),
        # #91
        ("dal 10 al 20 ottobre", False, "Da sabato 10 a martedì 20 ottobre"),
        ("fino a domenica", False, "Da oggi a domenica 4 ottobre"),
        ("da lunedì a giovedì", False, "Da lunedì 5 a giovedì 8 ottobre"),
        (
            "dal 10 al 20 ottobre dopo le 23",
            False,
            "Da sabato 10 a martedì 20 ottobre, dalle 23:00 alle 04:00",
        ),
        ("il lunedì fino al 20 ottobre", False, "Ogni lunedì, fino a martedì 20 ottobre"),
        # #92
        (
            "quando apro Dropbox ogni due settimane",
            True,
            "Una volta ogni due settimane, da oggi, venerdì 2 ottobre",
        ),
        ("il primo lunedì del mese", True, "Il primo lunedì di ogni mese"),
        ("l'ultimo venerdì del mese", True, "L'ultimo venerdì di ogni mese"),
        ("il 15 di ogni mese", True, "Il 15 di ogni mese"),
        ("a fine mese", True, "L'ultimo giorno di ogni mese"),
        ("il 12 marzo di ogni anno", True, "Il 12 marzo di ogni anno"),
        ("un lunedì sì e uno no", True, "Un lunedì sì e uno no, da lunedì 5 ottobre"),
        ("una volta al mese", True, "Una volta al mese, da oggi, venerdì 2 ottobre"),
        ("il primo lunedì del mese alle 9", True, "Il primo lunedì di ogni mese, alle 09:00"),
        (
            "il 15 di ogni mese fino al 15 dicembre",
            True,
            "Il 15 di ogni mese, fino a martedì 15 dicembre",
        ),
        ("il 31 di ogni mese", True, "Il 31 di ogni mese"),
        ("il 29 febbraio di ogni anno", True, "Il 29 febbraio di ogni anno"),
    ],
)
def test_the_examples_of_the_map_read_as_decided(
    condition: str, perennial: bool, line: str
) -> None:
    assert when(written(condition), perennial, FRIDAY) == line


@pytest.mark.parametrize(
    ("condition", "written_at", "today", "line"),
    [
        # ADR-0020: "domani alle 21", written yesterday, reads "Oggi" today.
        (
            "domani alle 21",
            at(1, 10),
            FRIDAY,
            "Oggi, venerdì 2 ottobre, alle 21:00",
        ),
        # #91: a period already over when written is next year's, which shows its year.
        (
            "dal 1 al 5 ottobre",
            at(10, 10),
            date(2026, 10, 10),
            "Da venerdì 1 a martedì 5 ottobre 2027",
        ),
        # #92: the start stays written once past.
        (
            "quando apro Dropbox ogni due settimane",
            WRITTEN,
            date(2026, 10, 10),
            "Una volta ogni due settimane, da venerdì 2 ottobre",
        ),
        ("fino a domenica", WRITTEN, date(2026, 10, 3), "Da venerdì 2 a domenica 4 ottobre"),
        (
            "il lunedì fino al 20 ottobre",
            WRITTEN,
            date(2026, 10, 10),
            "Ogni lunedì, da venerdì 2 a martedì 20 ottobre",
        ),
    ],
)
def test_a_time_is_written_for_the_day_it_is_shown_on(
    condition: str, written_at: datetime, today: date, line: str
) -> None:
    assert when(written(condition, written_at), False, today) == line


@pytest.mark.parametrize(
    ("schedule", "line"),
    [
        (
            Schedule(OnDate(date(2026, 10, 1)), Moment(time(15))),
            "Ieri, giovedì 1 ottobre, alle 15:00",
        ),
        (Schedule(OnDate(date(2026, 10, 3))), "Domani, sabato 3 ottobre"),
        (
            Schedule(OnDate(date(2026, 10, 2)), Moment(time(12, 30))),
            "Oggi, venerdì 2 ottobre, alle 12:30",
        ),
        (Schedule(OnDate(date(2027, 1, 4)), Moment(time(9))), "Lunedì 4 gennaio 2027, alle 09:00"),
    ],
)
def test_a_date_has_its_weekday_today_tomorrow_or_yesterday_and_its_year_when_another(
    schedule: Schedule, line: str
) -> None:
    assert when(schedule, False, FRIDAY) == line


@pytest.mark.parametrize(
    ("schedule", "perennial", "line"),
    [
        # Hours before 04:00 belong to the day before (#90): they say so.
        (
            Schedule(OnDate(date(2026, 10, 3)), Moment(time(2))),
            False,
            "Domani, sabato 3 ottobre, alle 02:00 di notte",
        ),
        (Schedule(week(0), Moment(time(2))), False, "Ogni lunedì alle 02:00 di notte"),
        (Schedule(hours=Moment(time(1, 30))), True, "Ogni giorno alle 01:30 di notte"),
        (
            Schedule(OnDate(date(2026, 10, 3)), Slot(time(2), time(5))),
            False,
            "Domani, sabato 3 ottobre, dalle 02:00 alle 05:00 di notte",
        ),
        (Schedule(hours=Moment(time(0))), False, "A mezzanotte"),
        (Schedule(hours=Moment(time(0))), True, "Ogni giorno a mezzanotte"),
        # A slot that starts at 04:00 or later is the day's: "prima delle 9" starts with it.
        (Schedule(hours=Slot(time(4), time(9))), True, "Ogni giorno dalle 04:00 alle 09:00"),
        (Schedule(hours=Slot(time(23), time(6))), False, "Dalle 23:00 alle 06:00"),
    ],
)
def test_the_hours_have_two_digits_and_the_night_says_so(
    schedule: Schedule, perennial: bool, line: str
) -> None:
    assert when(schedule, perennial, FRIDAY) == line


@pytest.mark.parametrize(
    ("days", "line"),
    [
        (week(6), "Ogni domenica"),
        (week(0, 3), "Il lunedì e il giovedì"),
        (week(0, 2, 4), "Il lunedì, il mercoledì e il venerdì"),
        (week(0, 1, 2, 3), "Dal lunedì al giovedì"),
        (week(4, 5, 6), "Dal venerdì alla domenica"),
        (week(6, 0, 1), "Dalla domenica al martedì"),
        (week(1, 2, 3, 4, 5), "Dal martedì al sabato"),
        (week(0, 1, 3, 4), "Il lunedì, il martedì, il giovedì e il venerdì"),
        (week(0, 1, 2, 3, 4, 6), "Ogni giorno tranne il sabato"),
        (week(0, 1, 3, 4, 5), "Ogni giorno tranne il mercoledì e la domenica"),
        (EVERY_DAY, "Ogni giorno"),
    ],
)
def test_the_days_of_the_week_read_as_a_list_a_run_or_what_is_left_out(
    days: Weekdays, line: str
) -> None:
    assert when(Schedule(days), False, FRIDAY) == line


@pytest.mark.parametrize(
    ("schedule", "perennial", "line"),
    [
        (written("tutti i giorni tranne il sabato"), True, "Ogni giorno tranne il sabato"),
        (written("ogni giorno quando apro Teams"), False, "Ogni giorno"),
        (
            Schedule(week(0, 1, 2, 3, 4), Slot(time(9), time(18))),
            False,
            "Dal lunedì al venerdì dalle 09:00 alle 18:00",
        ),
        (Schedule(week(0), Moment(time(9))), True, "Ogni lunedì alle 09:00"),
    ],
)
def test_days_of_the_week_take_their_hours_without_a_comma(
    schedule: Schedule, perennial: bool, line: str
) -> None:
    assert when(schedule, perennial, FRIDAY) == line


@pytest.mark.parametrize(
    ("days", "line"),
    [
        (MonthWeekday(6, 1), "La prima domenica di ogni mese"),
        (MonthWeekday(2, 3), "Il terzo mercoledì di ogni mese"),
        (MonthWeekday(5, 4), "Il quarto sabato di ogni mese"),
        (MonthWeekday(6, -1), "L'ultima domenica di ogni mese"),
        (MonthWeekday(1, 2), "Il secondo martedì di ogni mese"),
        (MonthDay(1), "Il primo di ogni mese"),
        (MonthDay(8), "L'8 di ogni mese"),
        (MonthDay(11), "L'11 di ogni mese"),
        (YearDay(5, 1), "Il primo maggio di ogni anno"),
        (YearDay(12, 8), "L'8 dicembre di ogni anno"),
        (EveryNWeeks(6, 2, date(2026, 10, 4)), "Una domenica sì e una no, da domenica 4 ottobre"),
        (EveryNWeeks(0, 3, date(2026, 10, 5)), "Un lunedì ogni tre settimane, da lunedì 5 ottobre"),
        (
            EveryNWeeks(5, 2, date(2026, 10, 3)),
            "Un sabato sì e uno no, da domani, sabato 3 ottobre",
        ),
    ],
)
def test_the_days_of_a_month_or_a_year_read_as_in_the_condition(
    days: MonthWeekday | MonthDay | YearDay | EveryNWeeks, line: str
) -> None:
    assert when(Schedule(days), True, FRIDAY) == line


@pytest.mark.parametrize(
    ("schedule", "line"),
    [
        (
            Schedule(MonthDay(15), Moment(time(9)), Period(FRIDAY, date(2026, 12, 15))),
            "Il 15 di ogni mese, alle 09:00, fino a martedì 15 dicembre",
        ),
        (
            Schedule(EveryNWeeks(0, 2, date(2026, 10, 5)), Moment(time(9))),
            "Un lunedì sì e uno no, da lunedì 5 ottobre, alle 09:00",
        ),
        (
            Schedule(week(0), period=Period(date(2026, 10, 10), date(2026, 10, 20))),
            "Ogni lunedì, da sabato 10 a martedì 20 ottobre",
        ),
    ],
)
def test_the_hours_and_the_period_follow_the_days_after_a_comma(
    schedule: Schedule, line: str
) -> None:
    assert when(schedule, True, FRIDAY) == line


@pytest.mark.parametrize(
    ("period", "line"),
    [
        (
            Period(date(2026, 10, 31), date(2026, 11, 3)),
            "Da sabato 31 ottobre a martedì 3 novembre",
        ),
        (
            Period(date(2026, 12, 31), date(2027, 1, 2)),
            "Da giovedì 31 dicembre a sabato 2 gennaio 2027",
        ),
        (
            Period(date(2027, 1, 30), date(2027, 2, 2)),
            "Da sabato 30 gennaio a martedì 2 febbraio 2027",
        ),
        (
            Period(date(2027, 12, 30), date(2028, 1, 2)),
            "Da giovedì 30 dicembre 2027 a domenica 2 gennaio 2028",
        ),
        (Period(FRIDAY, date(2026, 10, 3)), "Da oggi a sabato 3 ottobre"),
        (Period(FRIDAY, FRIDAY), "Oggi, venerdì 2 ottobre"),
        (Period(date(2026, 10, 10), date(2026, 10, 10)), "Sabato 10 ottobre"),
    ],
)
def test_a_period_names_its_month_and_year_once_when_they_are_the_same(
    period: Period, line: str
) -> None:
    assert when(Schedule(period=period), False, FRIDAY) == line


@pytest.mark.parametrize(
    ("count", "unit", "line"),
    [
        (1, Unit.DAY, "Una volta al giorno, da oggi, venerdì 2 ottobre"),
        (1, Unit.WEEK, "Una volta alla settimana, da oggi, venerdì 2 ottobre"),
        (1, Unit.YEAR, "Una volta all'anno, da oggi, venerdì 2 ottobre"),
        (3, Unit.DAY, "Una volta ogni tre giorni, da oggi, venerdì 2 ottobre"),
        (2, Unit.MONTH, "Una volta ogni due mesi, da oggi, venerdì 2 ottobre"),
        (2, Unit.YEAR, "Una volta ogni due anni, da oggi, venerdì 2 ottobre"),
        (15, Unit.DAY, "Una volta ogni 15 giorni, da oggi, venerdì 2 ottobre"),
    ],
)
def test_a_frequency_says_how_often_and_from_when(count: int, unit: Unit, line: str) -> None:
    schedule = Schedule(frequency=Frequency(count, unit, FRIDAY))
    assert when(schedule, True, FRIDAY) == line


@pytest.mark.parametrize(
    ("schedule", "today", "line"),
    [
        (
            written("ogni due settimane il lunedì e il giovedì"),
            FRIDAY,
            "Una volta ogni due settimane, il lunedì e il giovedì, da oggi, venerdì 2 ottobre",
        ),
        (
            Schedule(week(0), frequency=Frequency(1, Unit.MONTH, FRIDAY)),
            FRIDAY,
            "Una volta al mese, il lunedì, da oggi, venerdì 2 ottobre",
        ),
        (
            written("una volta alla settimana la sera"),
            FRIDAY,
            "Una volta alla settimana, dalle 18:00 alle 23:00, da oggi, venerdì 2 ottobre",
        ),
        (
            written("una volta alla settimana fino al 20 ottobre"),
            FRIDAY,
            "Una volta alla settimana, da oggi, venerdì 2 ottobre, fino a martedì 20 ottobre",
        ),
        (
            written("una volta alla settimana fino al 20 ottobre"),
            date(2026, 10, 10),
            "Una volta alla settimana, da venerdì 2 ottobre, fino a martedì 20 ottobre",
        ),
    ],
)
def test_a_frequency_takes_its_days_hours_and_period_after_it(
    schedule: Schedule, today: date, line: str
) -> None:
    assert when(schedule, True, today) == line


@pytest.mark.parametrize(
    ("condition", "written_at", "words"),
    [
        ("oggi alle 9", WRITTEN, "Oggi alle 09:00"),
        ("stasera", at(2, 23, 30), "Oggi dalle 18:00 alle 23:00"),
        # At 02:00 it is still the Jiffin day before (#90, #91).
        ("oggi alle 15", at(3, 2), "Oggi alle 15:00"),
        ("oggi alle 2 di notte", at(3, 3), "Oggi alle 02:00 di notte"),
    ],
)
def test_a_time_already_over_is_named_short_for_salvas_warning(
    condition: str, written_at: datetime, words: str
) -> None:
    reading = read(condition, written_at)
    assert reading.past
    assert reading.schedule is not None
    assert passed(reading.schedule, FRIDAY) == words


def test_a_time_not_on_a_date_is_named_by_its_whole_line() -> None:
    assert passed(Schedule(week(0), Moment(time(9))), FRIDAY) == "Ogni lunedì alle 09:00"
