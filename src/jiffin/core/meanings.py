"""What the time words of a condition mean, and `read`, the only way in (ADR-0020, ADR-0028).

`grammar` finds the words of the time and of the situations and labels them; here the labels of
the time become a `Schedule` in real dates, counted from when the condition is written, with
every meaning decided on the 0.2 map in one place, and those of the situations its terms. The
remainder is the condition without those words: what the engine rewrites.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from jiffin.core.grammar import (
    After,
    At,
    Before,
    Between,
    Clock,
    ClockLabel,
    DateRange,
    DateWords,
    DayLabel,
    DayNames,
    Every,
    ForDays,
    InDays,
    InMinutes,
    Labels,
    NextDayOfMonth,
    NextWeek,
    Part,
    PeriodLabel,
    SituationLabels,
    ThisWeek,
    Unclear,
    Until,
    WeekdayEveryWeeks,
    WeekdaysOnce,
    alternatives,
    labels,
    phrases,
    situation_labels,
    situation_phrases,
)
from jiffin.core.schedule import (
    DAY_STARTS_AT,
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
    Weekdays,
    YearDay,
    instances,
    jiffin_day,
)
from jiffin.core.situations import Term
from jiffin.lang.situations import SITUATIONS
from jiffin.lang.time import TIME

PARTS = {
    Part.MORNING: Slot(time(6), time(12)),
    Part.AFTERNOON: Slot(time(12), time(18)),
    Part.EVENING: Slot(time(18), time(23)),
    Part.NIGHT: Slot(time(23), time(6)),
}
"""The parts of the day (#81)."""
MOVED_FROM = {Part.AFTERNOON: 1, Part.EVENING: 1, Part.NIGHT: 6}
"""The first hour that a part of the day moves by 12, up to 11: "alle 7 di sera" is 19:00,
"alle 10 di notte" 22:00, "alle 2 di notte" 02:00."""
CONNECTORS = frozenset(TIME.read.remainder.connectors)
"""Words a removed time leaves hanging: "quando apro Steam, ma non nel weekend"."""
LEADS = frozenset(TIME.read.remainder.leads)
"""Prepositions that lead into a removed time, and go with it: "nel pomeriggio di domani". After
a time they stay: "domani a Milano"."""
EMPTY_BRACKETS = re.compile(r"\(\s*\)|\[\s*\]")
""""quando apro Outlook (lunedì dopo le 14)" leaves "()"."""
LEFT_ALONE = (
    *SITUATIONS.read.openers,
    *SITUATIONS.read.call.holds_verbs,
    *SITUATIONS.read.power.battery_verbs,
    *SITUATIONS.read.power.plugged_verbs,
    *SITUATIONS.read.network.verbs,
)
"""What the situations may leave of a condition that has nothing else: "quando" of "quando sono
in call", "quando sono" of "quando sono da più di un'ora in call"."""
OPENERS_ONLY = re.compile(
    rf"(?:(?:{alternatives(set(LEFT_ALONE))})(?![\w'])[\s,;]*)*", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class Reading:
    """What the time and the situations of a condition mean."""

    schedule: Schedule | None
    """None when the condition has no time, or one not understood."""
    remainder: str
    """The condition without the words of its time and of its situations, and without the
    connectors they leave hanging; the whole condition, byte for byte, when it has neither, or a
    time not understood."""
    unclear: tuple[tuple[int, int], ...] = ()
    """Where the words not understood are, as [start, end) offsets, to name them."""
    past: bool = False
    """The time is over already, when written: Save turns off (#84)."""
    recurring: bool = False
    """Words that tick "Ogni volta" by themselves: "ogni…", or a recurrence of the month or of
    the year (#92)."""
    situations: tuple[Term, ...] = ()
    """The situations of the condition (ADR-0028); none when they are not understood, and with a
    time not understood."""


def read(condition: str, written_at: datetime) -> Reading:
    """The time and the situations of `condition`, written at the local time `written_at` (only
    its wall clock counts). A pure function: the creation window calls it at every key.

    Situations not understood leave the condition as it reads without them, its time included: a
    reminder works without its situations (ADR-0028). A time not understood leaves it whole."""
    written_at = written_at.replace(tzinfo=None, second=0, microsecond=0)
    found = situation_phrases(condition)
    time = labels(condition, [(start, end) for start, end, _ in found])
    situations = situation_labels(condition, found, time.spans)
    spans = (*time.spans, *situations.spans)
    remainder = _remainder(condition, spans, situated=True) if situations.terms else None
    if situations.terms and situations.lasting and not remainder:  # how long, but of nothing
        situations = SituationLabels(situations.spans, situations.lasting)
    if situations.unclear:
        time = labels(condition)
        spans, remainder = time.spans, None
    unclear = phrases(condition, (*time.unclear, *situations.unclear))
    # Without a time or situations, or with a time not understood, the condition stays byte for
    # byte: the statement the engine writes from it stays today's (ADR-0008).
    if time.unclear or not spans:
        return Reading(None, condition, unclear, recurring=time.recurring)
    try:
        schedule = _schedule(time, written_at) if time.spans else None
    except (Unclear, ValueError):  # ValueError: a date that does not exist, "il 31 aprile"
        unclear = phrases(condition, (*time.spans, *situations.unclear))
        return Reading(None, condition, unclear, recurring=time.recurring)
    return Reading(
        schedule,
        _remainder(condition, spans) if remainder is None else remainder,
        unclear,
        past=schedule is not None and next(instances(schedule, written_at), None) is None,
        recurring=time.recurring,
        situations=situations.terms,
    )


def _remainder(
    condition: str, spans: tuple[tuple[int, int], ...], *, situated: bool = False
) -> str:
    """The condition without the spans, and without what they leave hanging: connectors,
    commas, empty brackets, a preposition that led into a time; and, `situated`, the words that
    open a condition when nothing else is left of it."""
    pieces = []
    cursor = 0
    for start, end in sorted(spans):
        pieces.append(_trim(condition[cursor:start], CONNECTORS | LEADS))
        cursor = end
    pieces.append(_trim(condition[cursor:], CONNECTORS))
    joined = EMPTY_BRACKETS.sub(" ", " ".join(piece for piece in pieces if piece))
    remainder = _trim(" ".join(joined.split()), CONNECTORS)
    if situated and OPENERS_ONLY.fullmatch(remainder.replace("’", "'")):
        return ""
    return remainder


def _trim(piece: str, last_words: frozenset[str]) -> str:
    """Without commas and connectors at its sides, and without `last_words` at its end."""
    while True:
        piece = piece.strip()
        words = piece.split()
        if piece[-1:] in (",", ";"):
            piece = piece[:-1]
        elif piece[:1] in (",", ";"):
            piece = piece[1:]
        elif words and words[-1].lower() in last_words:
            piece = piece[: piece.rfind(words[-1])]
        elif words and words[0].lower() in CONNECTORS:
            piece = piece[len(words[0]) :]
        else:
            return piece


def _schedule(found: Labels, written_at: datetime) -> Schedule:
    today = jiffin_day(written_at)
    if isinstance(found.hours, InMinutes):
        when = written_at + timedelta(minutes=found.hours.count)
        return Schedule(OnDate(jiffin_day(when)), Moment(when.time()))
    return Schedule(
        _days(found.days, today),
        _hours(found.hours),
        _period(found.period, today),
        _frequency(found.frequency, today),
    )


def _days(label: DayLabel | None, today: date) -> Days:
    match label:
        case None:
            return EVERY_DAY
        case DayNames(days, every, negated) if every or negated:
            chosen = frozenset(range(7)) - days if negated else days
            if not chosen:
                raise Unclear("every day, negated")
            return Weekdays(chosen)
        case DayNames(days):
            return OnDate(_next_weekday(today, _one(days)))
        case InDays(count):
            return OnDate(today + timedelta(days=count))
        case DateWords():
            return OnDate(_date(label, today))
        case WeekdayEveryWeeks(weekday, weeks):
            if weeks < 1:
                raise Unclear("every 0 weeks")
            if weeks == 1:
                return Weekdays(frozenset({weekday}))
            # From the next one, or today if today is the day (#92).
            return EveryNWeeks(
                weekday, weeks, today + timedelta(days=(weekday - today.weekday()) % 7)
            )
        case MonthWeekday() | MonthDay() | YearDay():
            return label


def _hours(label: Part | ClockLabel | None) -> Hours | None:
    match label:
        case None:
            return None
        case Part():
            return PARTS[label]
        case At(clock, part):
            return Moment(_shift(clock, part))
        case After(clock, part):
            return Slot(_shift(clock, part), DAY_STARTS_AT)
        case Before(clock, part):
            return Slot(DAY_STARTS_AT, _shift(clock, part))
        case Between(start, end, start_part, end_part):
            finish = _shift(end, end_part)
            begin = _shift(start, start_part)
            # "tra le 2 e le 4 del pomeriggio": the part said once, at the end, moves the start
            # too, when it keeps the start before the end ("dalle 10 alle 2 del pomeriggio" not).
            if start_part is None and end_part is not None and _shift(start, end_part) < finish:
                begin = _shift(start, end_part)
            return Slot(begin, finish)


def _period(label: PeriodLabel | None, today: date) -> Period | None:
    match label:
        case None:
            return None
        case Until(until):
            return Period(today, _until(until, today))
        case DateRange(first_day, first_month, last_words):
            # The last day as a date: this year's, or next year's once past (#91).
            last = _date(last_words, today)
            first = date(last.year, first_month, first_day)
            if first > last:  # "dal 28 dicembre al 3 gennaio"
                first = date(last.year - 1, first_month, first_day)
            return Period(first, last)
        case ForDays(count):
            if count < 1:
                raise Unclear("for 0 days")
            return Period(today, today + timedelta(days=count - 1))
        case ThisWeek():
            return Period(today, today + timedelta(days=6 - today.weekday()))
        case NextWeek():
            monday = today + timedelta(days=7 - today.weekday())
            return Period(monday, monday + timedelta(days=6))
        case WeekdaysOnce(first_weekday, last_weekday):
            first = _next_weekday(today, first_weekday)
            return Period(first, first + timedelta(days=(last_weekday - first_weekday) % 7))


def _frequency(label: Every | None, today: date) -> Frequency | None:
    if label is None:
        return None
    if label.count < 1:
        raise Unclear("every 0 days")
    return Frequency(label.count, label.unit, today)


def _until(last: DayNames | InDays | DateWords | NextDayOfMonth, today: date) -> date:
    match last:
        case DayNames(days):
            # "fino a domenica" written on a Sunday is the next one, as "lunedì" (#91).
            return _next_weekday(today, _one(days))
        case InDays(count):
            return today + timedelta(days=count)
        case DateWords():
            return _date(last, today)
        case NextDayOfMonth(day):
            # "fino al 20" written on the 20th is that day: it is not over yet (#91).
            if day >= today.day:
                return date(today.year, today.month, day)
            year, month = divmod(today.month, 12)
            return date(today.year + year, month + 1, day)


def _date(words: DateWords, today: date) -> date:
    """A date written without its year is this year's, or next year's once past (#89)."""
    found = date(words.year or today.year, words.month, words.day)
    if words.year is None and found < today:
        found = date(today.year + 1, words.month, words.day)
    if words.weekday is not None and found.weekday() != words.weekday:
        raise Unclear("the weekday is not the date's")
    return found


def _next_weekday(today: date, weekday: int) -> date:
    """ "lunedì": the next Monday, the one of next week when written on a Monday (#89)."""
    return today + timedelta(days=(weekday - today.weekday() - 1) % 7 + 1)


def _one(days: frozenset[int]) -> int:
    if len(days) != 1:
        raise Unclear("more than one next weekday")
    return next(iter(days))


def _shift(clock: Clock, part: Part | None) -> time:
    """The hour as on a 24-hour clock (#89), moved by the words of the day: "alle 3 del
    pomeriggio" is 15:00, "alle 11 di sera" 23:00."""
    hour = clock.hour
    if part in MOVED_FROM and MOVED_FROM[part] <= hour <= 11:
        hour += 12
    elif part is Part.NIGHT and hour == 12:
        hour = 0
    return time(hour, clock.minute)
