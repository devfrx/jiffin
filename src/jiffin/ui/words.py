"""The user's words, as the interface shows them, and the words of a time.

`core` reads a time into a `Schedule`; the interface writes it when it shows it (ADR-0020), so
"domani alle 21", written yesterday, reads "Oggi" today. The rules are #84's, with the forms of
#91 and #92: hours with two digits; a date with its weekday, "Oggi", "Domani" or "Ieri" in front
when it is one of them, and its year only when it is not the current one. Days count by the
Jiffin day, as the meanings do, so hours before 04:00 are the night after their day, and say so.
"""

from datetime import date, datetime, time

from jiffin.core.schedule import (
    DAY_STARTS_AT,
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

WEEKDAYS = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
MONTHS = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)  # fmt: skip
SUNDAY = 6
"""The one weekday that is feminine: "la domenica", "la prima domenica"."""
ORDINALS = {
    1: ("primo", "prima"),
    2: ("secondo", "seconda"),
    3: ("terzo", "terza"),
    4: ("quarto", "quarta"),
    -1: ("ultimo", "ultima"),
}
NUMBERS = {
    2: "due", 3: "tre", 4: "quattro", 5: "cinque", 6: "sei", 7: "sette", 8: "otto", 9: "nove",
    10: "dieci",
}  # fmt: skip
"""Counts up to ten in words, as they are written: "ogni due settimane", "ogni 15 giorni"."""
UNITS = {
    Unit.DAY: ("al giorno", "giorni"),
    Unit.WEEK: ("alla settimana", "settimane"),
    Unit.MONTH: ("al mese", "mesi"),
    Unit.YEAR: ("all'anno", "anni"),
}
NEAR = {-1: "ieri", 0: "oggi", 1: "domani"}


def sentence(text: str) -> str:
    """With a capital to start: "quando apro Figma" shows as "Quando apro Figma"."""
    text = text.strip()
    return text[:1].upper() + text[1:]


def tidy(text: str) -> str:
    """One space between words, as the reminder is saved: a pasted line break goes too."""
    return " ".join(text.split())


def when(schedule: Schedule, perennial: bool, today: date) -> str:
    """The time understood, on a line of its own: "Ogni giorno dalle 23:00 alle 04:00", "Oggi,
    venerdì 2 ottobre, alle 09:00". `today` is the Jiffin day it shows on. Every day goes unsaid
    before the hours of a one-off reminder, which may ring once: "Dalle 23:00 alle 04:00" (#84).

    With a frequency the days are every day or days of the week, as `meanings` reads them.
    """
    return sentence(_when(schedule, perennial, today))


def passed(schedule: Schedule, today: date) -> str:
    """A time over already when written, short, for Salva's warning: "Oggi alle 09:00" (#84).
    `meanings` finds one only on a date; any other time gets its whole line."""
    if not isinstance(schedule.days, OnDate):
        return when(schedule, False, today)
    return _on_day(schedule, schedule.days.day, today)


def alert_line(remainder: str, schedule: Schedule | None, day: date | None, today: date) -> str:
    """The one line of an alert, over what to do (#84): the condition without its time, then the
    time understood, "Quando apro Claude · dalle 23:00 alle 04:00", where every day goes unsaid,
    also for a perennial reminder, whose icon says it. With only a time, the day of the instance
    that rings and its hours, short: "Oggi alle 15:00", "Ieri alle 15:00" when it rings late.
    `day` is that instance's Jiffin day, if known; `today` the Jiffin day the alert shows on."""
    if schedule is None:
        return sentence(remainder)
    if remainder:
        return f"{sentence(remainder)} · {_when(schedule, False, today)}"
    return _on_day(schedule, day or today, today)


def appeared(remainder: str, at: datetime, today: date) -> str:
    """The line of an unseen alert in the tray list (#84): the condition without its time, then
    when the alert appeared, "Quando apro Claude, ieri alle 23:12"; with only a time, only when
    it appeared, "Ieri alle 23:12". `at` is local, and its day counts on the calendar."""
    days = (today - at.date()).days
    words = f"alle {at:%H:%M}"
    if days == 1:
        words = f"ieri {words}"
    elif days > 1:
        words = f"{dated(at.date(), today)} {words}"
    return f"{sentence(remainder)}, {words}" if remainder else sentence(words)


def dated(day: date, today: date) -> str:
    """A day in the middle of a line, with its article: "il 20 ottobre", "l'8 ottobre", "l'1
    ottobre"; its year only when it is not the current one."""
    article = "l'" if day.day in (1, 8, 11) else "il "
    return f"{article}{day.day} {MONTHS[day.month - 1]}{_year(day, today)}"


def _on_day(schedule: Schedule, day: date, today: date) -> str:
    """The hours of a time on one of its days, short: "Oggi alle 09:00", "Venerdì 2 ottobre dalle
    23:00 alle 04:00"."""
    words = NEAR.get((day - today).days) or _plain(day, today)
    if schedule.hours is not None:
        words += f" {_hours(schedule.hours)}"
    return sentence(words)


def _when(schedule: Schedule, perennial: bool, today: date) -> str:
    days, hours, period = schedule.days, schedule.hours, schedule.period
    if schedule.frequency is not None:
        return _frequency(schedule, schedule.frequency, today)
    match days:
        case Weekdays(weekdays) if len(weekdays) == 7:
            if period is not None:
                line = _period(period, today)
                return line if hours is None else f"{line}, {_hours(hours)}"
            if hours is None:
                return "ogni giorno"
            return f"ogni giorno {_hours(hours)}" if perennial else _hours(hours)
        case Weekdays(weekdays):
            line = _weekdays(weekdays, every=True)
            if hours is not None:
                line += f" {_hours(hours)}"
        case OnDate(day):
            line = _date(day, today)
            if hours is not None:
                line += f", {_hours(hours)}"
        case EveryNWeeks() | MonthWeekday() | MonthDay() | YearDay():
            line = _recurring(days, today)
            if hours is not None:
                line += f", {_hours(hours)}"
    if period is not None:
        line += f", {_until(period, today, today)}"
    return line


def _frequency(schedule: Schedule, frequency: Frequency, today: date) -> str:
    """ "Una volta ogni due settimane, il lunedì, dalle 18:00 alle 23:00, da oggi, venerdì 2
    ottobre": how often, then on which days and hours, then from when the periods count."""
    each, many = UNITS[frequency.unit]
    count = frequency.count
    parts = [f"una volta {each}" if count == 1 else f"una volta ogni {_count(count)} {many}"]
    if isinstance(schedule.days, Weekdays) and len(schedule.days.weekdays) < 7:
        parts.append(_weekdays(schedule.days.weekdays, every=False))
    if schedule.hours is not None:
        parts.append(_hours(schedule.hours))
    parts.append(f"da {_date(frequency.first, today)}")
    if schedule.period is not None:
        parts.append(_until(schedule.period, frequency.first, today))
    return ", ".join(parts)


def _hours(hours: Hours) -> str:
    match hours:
        case Moment(at) if at == time(0):
            return "a mezzanotte"
        case Moment(at):
            return f"alle {at:%H:%M}{_night(at)}"
        case Slot(start, end):
            return f"dalle {start:%H:%M} alle {end:%H:%M}{_night(start)}"


def _night(start: time) -> str:
    """Hours before 04:00 are the night after their day (#90): "alle 02:00 di notte"."""
    return " di notte" if start < DAY_STARTS_AT else ""


def _weekdays(weekdays: frozenset[int], *, every: bool) -> str:
    """ "ogni lunedì", "dal lunedì al venerdì", "il sabato e la domenica", "ogni giorno tranne il
    sabato". A single day is "il lunedì" after a frequency, which says how often."""
    days = sorted(weekdays)
    if len(days) == 7:
        return "ogni giorno"
    if len(days) == 1:
        return f"ogni {WEEKDAYS[days[0]]}" if every else _the(days[0])
    if len(days) == 6 or (len(days) == 5 and _run(weekdays) is None):
        return "ogni giorno tranne " + _and([_the(d) for d in range(7) if d not in weekdays])
    run = _run(weekdays)
    if run is not None and len(days) >= 3:
        first, last = run
        start = "dalla" if first == SUNDAY else "dal"
        end = "alla" if last == SUNDAY else "al"
        return f"{start} {WEEKDAYS[first]} {end} {WEEKDAYS[last]}"
    return _and([_the(day) for day in days])


def _run(weekdays: frozenset[int]) -> tuple[int, int] | None:
    """The first and the last of days in a row, also through Sunday: (4, 6) is "dal venerdì alla
    domenica", (6, 1) "dalla domenica al martedì"; None when they are not in a row."""
    for first in weekdays:
        if (first - 1) % 7 not in weekdays:
            if all((first + step) % 7 in weekdays for step in range(len(weekdays))):
                return first, (first + len(weekdays) - 1) % 7
            return None
    return None


def _the(weekday: int) -> str:
    return f"{'la' if weekday == SUNDAY else 'il'} {WEEKDAYS[weekday]}"


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1]


def _recurring(days: EveryNWeeks | MonthWeekday | MonthDay | YearDay, today: date) -> str:
    match days:
        case EveryNWeeks(weekday, weeks, first):
            one, other = ("una", "una") if weekday == SUNDAY else ("un", "uno")
            name = WEEKDAYS[weekday]
            if weeks == 2:
                every = f"{one} {name} sì e {other} no"
            else:
                every = f"{one} {name} ogni {_count(weeks)} settimane"
            return f"{every}, da {_date(first, today)}"
        case MonthWeekday(weekday, nth):
            feminine = weekday == SUNDAY
            article = "l'" if nth == -1 else "la " if feminine else "il "
            return f"{article}{ORDINALS[nth][feminine]} {WEEKDAYS[weekday]} di ogni mese"
        case MonthDay(-1):
            return "l'ultimo giorno di ogni mese"
        case MonthDay(day):
            return f"{_numbered(day)} di ogni mese"
        case YearDay(month, day):
            return f"{_numbered(day)} {MONTHS[month - 1]} di ogni anno"


def _numbered(day: int) -> str:
    """A day of the month with its article: "il 15", "l'8", "l'11", "il primo"."""
    if day == 1:
        return "il primo"
    return f"l'{day}" if day in (8, 11) else f"il {day}"


def _date(day: date, today: date) -> str:
    """ "oggi, venerdì 2 ottobre", "lunedì 5 ottobre", "martedì 5 ottobre 2027"."""
    near = NEAR.get((day - today).days)
    plain = _plain(day, today)
    return plain if near is None else f"{near}, {plain}"


def _plain(day: date, today: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}{_year(day, today)}"


def _year(day: date, today: date) -> str:
    return "" if day.year == today.year else f" {day.year}"


def _period(period: Period, today: date) -> str:
    """A period of every day, first on its line: "da sabato 10 a martedì 20 ottobre", "da oggi a
    domenica 4 ottobre"; a period of one day is its date."""
    if period.first == period.last:
        return _date(period.first, today)
    if period.first == today:
        return f"da oggi a {_plain(period.last, today)}"
    return f"da {_range(period, today)}"


def _until(period: Period, since: date, today: date) -> str:
    """A period after the days, or after a frequency that starts with it at `since`: "fino a
    martedì 20 ottobre"; its start stays written once past (#92)."""
    if period.first == since:
        return f"fino a {_plain(period.last, today)}"
    return f"da {_range(period, today)}"


def _range(period: Period, today: date) -> str:
    """ "sabato 10 a martedì 20 ottobre": the month and the year once, when they are the same."""
    first, last = period.first, period.last
    start = f"{WEEKDAYS[first.weekday()]} {first.day}"
    if (first.year, first.month) != (last.year, last.month):
        start += f" {MONTHS[first.month - 1]}"
    if first.year != last.year:
        start += _year(first, today)
    return f"{start} a {_plain(last, today)}"


def _count(count: int) -> str:
    return NUMBERS.get(count, str(count))
