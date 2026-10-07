"""Jiffin's own Italian time grammar: it finds the time words of a condition and labels them.

Technique A of #80 (ADR-0020). The vocabulary is closed, and a phrasing it does not know is never
guessed: time words left over after the match, or a word beside a match that changes it ("verso
sera", "prima di lunedì"), make the time unclear, and the labels say where those words are.
Names are not time: quoted names, words with a digit or a dot inside, capitalized words after
the first, the number after a name ("Windows 11"), a number that counts something ("alle 20
pagine"). The labels say what the words say; `meanings` knows what they mean.

The words are the lexicon of `jiffin.lang.time` (ADR-0026); the rules that read them are here:
the patterns, in order, and what each match says.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

from jiffin.core.schedule import MonthDay, MonthWeekday, Unit, YearDay
from jiffin.lang.time import TIME, Fused


class Unclear(Exception):
    """Time words whose meaning was not decided, or that contradict each other."""


# The labels


@dataclass(frozen=True, slots=True)
class DayNames:
    """Weekdays as named: "lunedì", "il lunedì", "nel weekend", "tranne il venerdì"."""

    days: frozenset[int]
    """0 is Monday."""
    every: bool
    """Every week: "il lunedì", "ogni lunedì". "lunedì" alone is the next one."""
    negated: bool = False
    """"tranne il venerdì": the other days."""


@dataclass(frozen=True, slots=True)
class InDays:
    """ "oggi" is 0, "domani" 1, "tra 3 giorni" 3."""

    count: int


@dataclass(frozen=True, slots=True)
class DateWords:
    """A date as written: "il 5 ottobre", "lunedì 19 ottobre", "il 5/10/2027"."""

    day: int
    month: int
    year: int | None = None
    weekday: int | None = None
    """Written next to the date, which must fall on it."""


@dataclass(frozen=True, slots=True)
class WeekdayEveryWeeks:
    """ "un lunedì sì e uno no", "ogni due settimane il lunedì"."""

    weekday: int
    weeks: int


type DayLabel = (
    DayNames | InDays | DateWords | WeekdayEveryWeeks | MonthWeekday | MonthDay | YearDay
)
DAY_LABELS = (DayNames, InDays, DateWords, WeekdayEveryWeeks, MonthWeekday, MonthDay, YearDay)
RECURRING_DAYS = (WeekdayEveryWeeks, MonthWeekday, MonthDay, YearDay)


@dataclass(frozen=True, slots=True)
class Clock:
    hour: int
    """As written: "alle 3 del pomeriggio" is 3, with the part "pomeriggio"."""
    minute: int = 0


class Part(StrEnum):
    """A part of the day: "la sera", "stamattina"."""

    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


@dataclass(frozen=True, slots=True)
class At:
    """ "alle 15", "verso le 9", "a mezzogiorno"."""

    clock: Clock
    part: Part | None = None


@dataclass(frozen=True, slots=True)
class After:
    """ "dopo le 23", "dalle 22 in poi"."""

    clock: Clock
    part: Part | None = None


@dataclass(frozen=True, slots=True)
class Before:
    """ "prima delle 9", "fino alle 8"."""

    clock: Clock
    part: Part | None = None


@dataclass(frozen=True, slots=True)
class Between:
    """ "dalle 14 alle 18", "tra le 9 e le 12"."""

    start: Clock
    end: Clock
    start_part: Part | None = None
    end_part: Part | None = None


@dataclass(frozen=True, slots=True)
class InMinutes:
    """ "tra 2 ore", "fra mezz'ora"."""

    count: int


type ClockLabel = At | After | Before | Between
type HourLabel = Part | ClockLabel | InMinutes


@dataclass(frozen=True, slots=True)
class NextDayOfMonth:
    """ "fino al 20": the 20th of this month, or of the next one once past."""

    day: int


@dataclass(frozen=True, slots=True)
class Until:
    """ "fino a domenica", "entro domani", "fino al 20 ottobre": from today to that day."""

    last: DayNames | InDays | DateWords | NextDayOfMonth


@dataclass(frozen=True, slots=True)
class DateRange:
    """ "dal 10 al 20 ottobre", "dal 28 dicembre al 3 gennaio"."""

    first_day: int
    first_month: int
    """The last day's month when the first day has none."""
    last: DateWords


@dataclass(frozen=True, slots=True)
class ForDays:
    """ "per tre giorni": today and the days after it."""

    count: int


@dataclass(frozen=True, slots=True)
class ThisWeek:
    """ "questa settimana": from today to Sunday."""


@dataclass(frozen=True, slots=True)
class NextWeek:
    """ "la prossima settimana": from the next Monday to the Sunday after it."""


@dataclass(frozen=True, slots=True)
class WeekdaysOnce:
    """ "da lunedì a giovedì", without the articles: from the next Monday to the Thursday after."""

    first: int
    last: int


type PeriodLabel = Until | DateRange | ForDays | ThisWeek | NextWeek | WeekdaysOnce
PERIOD_LABELS = (Until, DateRange, ForDays, ThisWeek, NextWeek, WeekdaysOnce)


@dataclass(frozen=True, slots=True)
class Every:
    """ "ogni due settimane", "una volta al mese"."""

    count: int
    unit: Unit


type Piece = DayLabel | HourLabel | PeriodLabel | Every
"""What one match says."""


@dataclass(frozen=True, slots=True)
class Labels:
    """What the time words of a condition say."""

    spans: tuple[tuple[int, int], ...] = ()
    """Where the time words are, as [start, end) offsets of the condition."""
    unclear: tuple[tuple[int, int], ...] = ()
    """Where the words not understood are. When there are any, the time is unclear."""
    recurring: bool = False
    """Words that tick "Ogni volta" by themselves (#92)."""
    days: DayLabel | None = None
    hours: HourLabel | None = None
    period: PeriodLabel | None = None
    frequency: Every | None = None


# The vocabulary: the lexicon's words, as the patterns read them

WORDS = TIME.read
UNITS = TIME.units
NUMBERS = WORDS.numbers
MINUTE_WORDS = {**NUMBERS, **WORDS.minute_numbers}
FRACTIONS = WORDS.fractions
MONTHS = TIME.months
WEEKDAY_STARTS = tuple(day[:3] for day in TIME.weekdays)
"""A weekday by its first three letters, whatever its ending or its accent."""
SINGULAR_PARTS = {
    Part.MORNING: WORDS.parts.morning,
    Part.AFTERNOON: WORDS.parts.afternoon,
    Part.EVENING: WORDS.parts.evening,
    Part.NIGHT: WORDS.parts.night,
}
PLURAL_PARTS = {
    Part.MORNING: WORDS.part_plurals.morning,
    Part.AFTERNOON: WORDS.part_plurals.afternoon,
    Part.EVENING: WORDS.part_plurals.evening,
    Part.NIGHT: WORDS.part_plurals.night,
}
PARTS = {
    word: part
    for forms in (SINGULAR_PARTS, PLURAL_PARTS)
    for part, words in forms.items()
    for word in words
}
SHORT_PARTS = {
    **dict.fromkeys(WORDS.short_parts.this_morning, (0, Part.MORNING)),
    **dict.fromkeys(WORDS.short_parts.this_evening, (0, Part.EVENING)),
    **dict.fromkeys(WORDS.short_parts.tonight, (0, Part.NIGHT)),
    **dict.fromkeys(WORDS.short_parts.tomorrow_morning, (1, Part.MORNING)),
}
"""One word for a part of a day: the day, from today, and the part."""
RELATIVE_DAYS = {**WORDS.relative_days, **WORDS.split_relative_days}
NTH = {
    form: nth
    for nth, ordinal in (
        (1, TIME.ordinals.first),
        (2, TIME.ordinals.second),
        (3, TIME.ordinals.third),
        (4, TIME.ordinals.fourth),
        (-1, TIME.ordinals.last),
    )
    for form in (ordinal.masculine, ordinal.feminine)
}
HOUR_FORMS = (UNITS.hour.one, UNITS.hour.other)
MINUTE_FORMS = (UNITS.minute.one, UNITS.minute.other)
DAY_FORMS = (UNITS.day.one, UNITS.day.other)
WEEK_FORMS = (UNITS.week.one, UNITS.week.other)
UNIT_OF = {
    form: unit
    for unit, plural in (
        (Unit.DAY, UNITS.day),
        (Unit.WEEK, UNITS.week),
        (Unit.MONTH, UNITS.month),
        (Unit.YEAR, UNITS.year),
    )
    for form in (plural.one, plural.other)
}
"""The units a frequency counts."""
EVERY_DAY = DayNames(frozenset(range(7)), every=True)
WEEKEND = frozenset({5, 6})
WORKING_DAYS = frozenset(range(5))
AFTER_DINNER = Clock(21)
""""dopo cena" is "dopo le 21" (#90)."""

ACCENT = rf"(?:{'|'.join(re.escape(spelling) for spelling in TIME.final_i)})"
"""A final accented i, as it may be typed."""


def alternatives(forms: Iterable[str]) -> str:
    """The forms as one alternation, the longest first."""
    return "|".join(phrase(form) for form in sorted(forms, key=len, reverse=True))


def phrase(form: str) -> str:
    """A form as it may be typed: any space between its words, and a final accented i in any of
    its spellings ("lunedi'")."""
    return r"\s+".join(_word(word) for word in form.split())


def _word(word: str) -> str:
    accented = TIME.final_i[0]
    if word.endswith(accented):
        return re.escape(word.removesuffix(accented)) + ACCENT
    return re.escape(word)


def leading(forms: Iterable[str]) -> str:
    """Forms that lead into the next word: a space after them, or none after an elision, "un
    paio di ore", "un paio d'ore"."""
    return "|".join(
        phrase(form) + ("" if form.endswith("'") else r"\s+")
        for form in sorted(forms, key=len, reverse=True)
    )


EVERY = phrase(WORDS.every)
AND = phrase(WORDS.conjunction)
OF = phrase(WORDS.of)
UP_TO = phrase(WORDS.up_to)
BY = phrase(WORDS.by)
ELIDED = phrase(WORDS.elided_article)
DAY_ARTICLE = phrase(WORDS.day_article)
WITHIN = alternatives(WORDS.within)
INDEFINITE = alternatives(WORDS.indefinite)
OF_MONTH = alternatives(WORDS.of_month)
WEEKDAY = rf"(?:{alternatives((*TIME.weekdays, *WORDS.weekday_plurals))})(?![\w'])"
MONTH = rf"(?:{alternatives(MONTHS)})(?!\w)"
PART_WORD = (
    rf"(?:{alternatives(word for words in SINGULAR_PARTS.values() for word in words)})(?!\w)"
)
NUMBER = rf"(?:\d{{1,2}}|{alternatives(NUMBERS)})(?![\w'])"
PAIR = rf"(?:{leading(WORDS.pair)})"
""""un paio d'ore" is 2 hours (#90); a pair of days is two days too."""
DAY_NUMBER = rf"(?:\d{{1,2}}|{alternatives(WORDS.first_of_month)})"
HOUR_WORD = alternatives(word for word, number in NUMBERS.items() if number <= 24)
MINUTES = rf"(?:[0-5]?\d(?!\d)|(?:{alternatives(MINUTE_WORDS)})(?![\w']))"
AND_MINUTES = (
    rf"(?:\s+{AND}\s+(?:{alternatives(FRACTIONS)}|{MINUTES})"
    rf"|\s+{phrase(WORDS.minus)}\s+(?:{alternatives(WORDS.minus_fractions)}|{MINUTES}))"
)
CLOCK = (
    rf"(?:(?:{phrase(WORDS.hours_word)}\s+)?(?:\d{{1,2}}(?:[:.,][0-5]\d(?!\d))?"
    rf"|(?:{HOUR_WORD})(?!\w)){AND_MINUTES}?(?:\s+{phrase(WORDS.sharp)})?)"
)
WITH_ARTICLE = (
    rf"(?:{phrase(WORDS.hour_article)}\s+{CLOCK}"
    rf"|{ELIDED}(?:{alternatives(WORDS.one_oclock)}){AND_MINUTES}?"
    rf"|{phrase(WORDS.midnight_article)}\s+{phrase(WORDS.midnight)}{AND_MINUTES}?)"
)
BARE = rf"(?:{phrase(WORDS.noon)}{AND_MINUTES}?|{phrase(WORDS.midnight)}{AND_MINUTES}?)"
NOON_OR_MIDNIGHT = rf"(?:{alternatives((WORDS.noon, WORDS.midnight))})"
TIME_ARTICLES = (
    rf"(?:{alternatives((WORDS.hour_article, WORDS.elided_article, WORDS.midnight_article))})"
)
"""The articles a time may start with, which a preposition before it fuses with: "dalle"."""
SUFFIX = rf"(?:{alternatives(WORDS.part_prepositions)})\s+{PART_WORD}"
NEGATION = rf"(?P<neg>(?:\b{phrase(WORDS.but)}\s+)?\b(?:{alternatives(WORDS.negations)})\s+)"
ARTICLE = rf"(?:{alternatives(WORDS.before_weekdays)})"
LIST_JOINS = "|".join(rf"\b{phrase(join)}\b" for join in WORDS.list_joins)
TIME_PREFIXES = (
    f"{WORDS.hour_article} ",
    f"{WORDS.midnight_article} ",
    WORDS.elided_article,
)
"""What a time may start with, before its hour: "le 9", "la mezzanotte", "l'una"."""
PLUS_OR_MINUS = rf"[:.,](\d{{2}})|({re.escape(WORDS.conjunction)}|{re.escape(WORDS.minus)}) (.+)"


def timed(n: int) -> str:
    """A time with its article ("le 9", "l'una", "mezzogiorno") and a part of the day."""
    return rf"(?P<t{n}>{WITH_ARTICLE}|{BARE})(?:\s+(?P<p{n}>{SUFFIX}))?"


def fused(preposition: Fused) -> str:
    """A preposition before timed(): fused with the article ("alle 9") or not ("a mezzogiorno")."""
    return (
        rf"(?:\b{phrase(preposition.joined)}(?={TIME_ARTICLES})"
        rf"|\b{phrase(preposition.plain)}\s+(?={NOON_OR_MIDNIGHT}))"
    )


def parse_time(text: str) -> Clock | None:
    words = re.sub(r"\s+", " ", text).strip()
    for prefix in TIME_PREFIXES:
        if words.startswith(prefix):
            words = words.removeprefix(prefix)
            break
    words = words.removeprefix(f"{WORDS.hours_word} ")
    words = words.removesuffix(f" {WORDS.sharp}")
    for name, hour in ((WORDS.noon, 12), (WORDS.midnight, 0)):
        if words.startswith(name):
            rest = words[len(name) :]
            break
    else:
        head = re.match(r"\d{1,2}|[^\W\d]+", words)
        if head is None:
            return None
        token = head.group()
        found_hour = int(token) if token.isdigit() else NUMBERS.get(token)
        if found_hour is None:
            return None
        hour, rest = found_hour, words[head.end() :]
    minutes = 0
    if rest := rest.strip():
        found = re.fullmatch(PLUS_OR_MINUS, rest)
        if found is None:
            return None
        if found[1]:
            minutes = int(found[1])
        else:
            amount = FRACTIONS.get(found[3]) or MINUTE_WORDS.get(found[3])
            if amount is None and found[3].isdigit():
                amount = int(found[3])
            if amount is None or not 0 < amount < 60:
                return None
            # "le 7 meno un quarto" is 06:45.
            minutes = amount if found[2] == WORDS.conjunction else -amount
    if not 0 <= hour <= 24 or minutes > 59 or (hour == 24 and minutes > 0):
        return None
    total = (hour * 60 + minutes) % (24 * 60)
    return Clock(total // 60, total % 60)


def part_of(text: str) -> Part:
    """The part of the day a phrase ends with: "della sera", "mattine"."""
    return PARTS[text.split()[-1]]


def optional_part(text: str | None) -> Part | None:
    return None if text is None else part_of(text)


def weekday_index(text: str) -> int:
    return WEEKDAY_STARTS.index(text[:3])


def counted(match: re.Match[str]) -> int:
    """The number of a match with the groups `n` and `pair`."""
    if match["pair"]:
        return 2
    number = match["n"]
    return int(number) if number.isdigit() else NUMBERS[number]


def day_number(text: str) -> int:
    return 1 if text in WORDS.first_of_month else int(text)


def date_words(match: re.Match[str]) -> DateWords:
    found = match.groupdict()
    month = found["mo"]
    year = int(found["y"]) if found.get("y") else None
    if year is not None and year < 100:
        year += 2000
    weekday = found.get("wd")
    return DateWords(
        day_number(found["d"]),
        int(month) if month.isdigit() else MONTHS.index(month) + 1,
        year,
        weekday_index(weekday) if weekday else None,
    )


# The handlers: what a match says; None when it says nothing after all.

type Handler = Callable[[re.Match[str]], list[Piece] | None]


def on_minutes(match: re.Match[str]) -> list[Piece]:
    if match["w"]:
        minutes = WORDS.durations[" ".join(match["w"].split())]
    else:
        minutes = counted(match) * (60 if match["pair"] or match["u"] in HOUR_FORMS else 1)
    if match["xm"]:
        minutes += int(match["xm"])
    elif match["x"]:
        minutes += WORDS.added_minutes[" ".join(match["x"].split())]
    return [InMinutes(minutes)]


def on_days_in(match: re.Match[str]) -> list[Piece]:
    return [InDays(counted(match) * (7 if match["u"] in WEEK_FORMS else 1))]


def on_between(match: re.Match[str]) -> list[Piece] | None:
    start, end = parse_time(match["t1"]), parse_time(match["t2"])
    if start is None or end is None:
        return None
    return [Between(start, end, optional_part(match["p1"]), optional_part(match["p2"]))]


def on_clock(kind: type[At | After | Before]) -> Handler:
    def handle(match: re.Match[str]) -> list[Piece] | None:
        clock = parse_time(match["t1"])
        return None if clock is None else [kind(clock, optional_part(match["p1"]))]

    return handle


def on_after_dinner(match: re.Match[str]) -> list[Piece]:
    return [After(AFTER_DINNER)]


def on_date(match: re.Match[str]) -> list[Piece]:
    words = date_words(match)
    if match.groupdict().get("every"):
        return [YearDay(words.month, words.day)]
    return [words]


def on_date_range(match: re.Match[str]) -> list[Piece]:
    month = MONTHS.index(match["mo2"]) + 1
    last = DateWords(day_number(match["d2"]), month, int(match["y"]) if match["y"] else None)
    first_month = MONTHS.index(match["mo1"]) + 1 if match["mo1"] else month
    return [DateRange(day_number(match["d1"]), first_month, last)]


def on_until(match: re.Match[str]) -> list[Piece]:
    if match["d"]:
        return [Until(date_words(match))]
    if match["wd"]:
        return [Until(DayNames(frozenset({weekday_index(match["wd"])}), every=False))]
    return [Until(InDays(WORDS.relative_days[match["r"]]))]


def on_until_date(match: re.Match[str]) -> list[Piece]:
    if match["mo"]:
        return [Until(date_words(match))]
    return [Until(NextDayOfMonth(day_number(match["d"])))]


def on_for_days(match: re.Match[str]) -> list[Piece]:
    return [ForDays(counted(match) * (7 if match["u"] in WEEK_FORMS else 1))]


def on_week(match: re.Match[str]) -> list[Piece]:
    return [NextWeek() if match["next"] else ThisWeek()]


def on_every_other_week(match: re.Match[str]) -> list[Piece]:
    return [WeekdayEveryWeeks(weekday_index(match["wd"]), 2)]


def on_month_weekday(match: re.Match[str]) -> list[Piece]:
    return [MonthWeekday(weekday_index(match["wd"]), NTH[match["nth"]])]


def on_month_day(match: re.Match[str]) -> list[Piece]:
    return [MonthDay(day_number(match["d"]))]


def on_month_end(match: re.Match[str]) -> list[Piece]:
    return [MonthDay(-1)]


def on_every(match: re.Match[str]) -> list[Piece]:
    number = counted(match) if match["n"] or match["pair"] else 1
    return [Every(number, UNIT_OF[match["u"]])]


def on_relative(match: re.Match[str]) -> list[Piece]:
    if match["s"]:
        days, part = SHORT_PARTS[match["s"]]
        return [InDays(days), part]
    found: list[Piece] = [InDays(RELATIVE_DAYS[" ".join(match["r"].split())])]
    if match["rp"]:
        found.append(part_of(match["rp"]))
    return found


def on_day_range(match: re.Match[str]) -> list[Piece]:
    first, last = weekday_index(match["a"]), weekday_index(match["b"])
    found: list[Piece]
    # Without its article, the first preposition makes it once: "da lunedì a giovedì".
    if match["from"] == WORDS.from_the.plain:
        found = [WeekdaysOnce(first, last)]
    else:
        days = frozenset((first + step) % 7 for step in range((last - first) % 7 + 1))
        found = [DayNames(days, every=True)]
    if match["part"]:
        found.append(part_of(match["part"]))
    return found


def on_set(days: frozenset[int]) -> Handler:
    def handle(match: re.Match[str]) -> list[Piece]:
        return [DayNames(days, every=True, negated=match["neg"] is not None)]

    return handle


def on_every_day(match: re.Match[str]) -> list[Piece]:
    return [EVERY_DAY]


def on_weekdays(match: re.Match[str]) -> list[Piece]:
    names = re.findall(WEEKDAY, match["list"])
    days = frozenset(weekday_index(name) for name in names)
    plural = any(name in WORDS.weekday_plurals for name in names)
    every = (match["art"] is not None or plural) and match["next"] is None
    found: list[Piece] = [DayNames(days, every, negated=match["neg"] is not None)]
    if match["part"]:
        found.append(part_of(match["part"]))
    return found


def on_part(match: re.Match[str]) -> list[Piece]:
    return [part_of(match["part"])]


EVERY_UNIT_FORMS = (
    UNITS.day.other,
    *(form for unit in (UNITS.week, UNITS.month, UNITS.year) for form in (unit.one, unit.other)),
)
"""The units after "ogni": not one day, which is every day ("ogni giorno"), read further on."""
ALL_UNIT_FORMS = tuple(UNIT_OF)

# Tried in order; a match may not overlap an earlier one.
PATTERNS: list[tuple[str, Handler]] = [
    (
        (
            rf"\b(?:{WITHIN})\s+(?:(?P<n>{NUMBER})\s+"
            rf"(?P<u>{alternatives((*HOUR_FORMS, *MINUTE_FORMS))})(?!\w)"
            rf"|(?P<pair>{PAIR}){phrase(UNITS.hour.other)}(?!\w)"
            rf"|(?P<w>{alternatives(WORDS.durations)}))"
            rf"(?:\s+{AND}\s+(?P<x>{alternatives(WORDS.added_minutes)}"
            rf"|(?P<xm>\d{{1,2}})\s+{phrase(UNITS.minute.other)}))?"
        ),
        on_minutes,
    ),
    (
        (
            rf"\b(?:{WITHIN})\s+(?:(?P<n>{NUMBER})\s+|(?P<pair>{PAIR}))"
            rf"(?P<u>{alternatives((*DAY_FORMS, *WEEK_FORMS))})(?!\w)"
        ),
        on_days_in,
    ),
    (rf"\b(?:{WITHIN})\s+{timed(1)}\s+{AND}\s+{timed(2)}", on_between),
    (
        rf"{fused(WORDS.from_the)}{timed(1)}\s+(?:{UP_TO}\s+)?{fused(WORDS.to_the)}{timed(2)}",
        on_between,
    ),
    (
        (
            rf"\b{phrase(WORDS.from_the.joined)}(?:{ELIDED}|\s+)(?P<d1>{DAY_NUMBER})"
            rf"(?:\s+(?:{OF}\s+)?(?P<mo1>{MONTH}))?"
            rf"\s+(?:{UP_TO}\s+)?{phrase(WORDS.to_the.joined)}(?:{ELIDED}|\s+)"
            rf"(?P<d2>{DAY_NUMBER})\s+(?:{OF}\s+)?(?P<mo2>{MONTH})"
            r"(?:\s+(?P<y>\d{4}))?"
        ),
        on_date_range,
    ),
    (
        (
            rf"\b(?:{UP_TO}\s+{phrase(WORDS.to_the.plain)}|{BY})\s+(?:(?P<wd>{WEEKDAY})"
            rf"(?:\s+(?P<d>{DAY_NUMBER})\s+(?:{OF}\s+)?(?P<mo>{MONTH})(?:\s+(?P<y>\d{{4}}))?)?"
            rf"|(?P<r>{alternatives(WORDS.relative_days)})(?!\w))"
        ),
        on_until,
    ),
    (
        (
            rf"\b(?:{UP_TO}\s+{phrase(WORDS.to_the.joined)}(?:{ELIDED}|\s+)"
            rf"|{BY}\s+(?:{DAY_ARTICLE}\s+|{ELIDED}))(?P<d>{DAY_NUMBER})"
            rf"(?:\s+(?:{OF}\s+)?(?P<mo>{MONTH})(?:\s+(?P<y>\d{{4}}))?)?(?![\d/])"
        ),
        on_until_date,
    ),
    (
        (
            rf"\b{phrase(WORDS.lasting)}\s+(?:(?P<n>{NUMBER})\s+|(?P<pair>{PAIR}))"
            rf"(?P<u>{alternatives((*DAY_FORMS, *WEEK_FORMS))})(?!\w)"
        ),
        on_for_days,
    ),
    (
        (
            rf"\b(?:{alternatives(WORDS.this_week)}"
            rf"|(?P<next>{alternatives(WORDS.next_week)}))(?!\w)"
        ),
        on_week,
    ),
    (
        (
            rf"\b(?:{INDEFINITE})\s+(?P<wd>{WEEKDAY})\s+{phrase(WORDS.yes)}\s+{AND}"
            rf"\s+(?:{INDEFINITE})\s+(?:{WEEKDAY}\s+)?{phrase(WORDS.no)}(?!\w)"
        ),
        on_every_other_week,
    ),
    (
        (
            rf"(?:\b(?:{alternatives(WORDS.before_month_weekday)})\s+|\b{ELIDED})?"
            rf"(?P<nth>{alternatives(NTH)})\s+(?P<wd>{WEEKDAY})\s+(?:{OF_MONTH})(?!\w)"
        ),
        on_month_weekday,
    ),
    (
        (
            rf"(?:\b(?:{alternatives(WORDS.before_month_day)})\s+|\b{ELIDED})?(?<!\d)"
            rf"(?P<d>{DAY_NUMBER})\s+(?:{OF_MONTH})(?!\w)"
        ),
        on_month_day,
    ),
    (
        (
            rf"\b(?:{alternatives(WORDS.month_end)})(?!\w)"
            rf"|\b(?:{alternatives(WORDS.month_last_day)})\s+(?:{OF_MONTH})(?!\w)"
        ),
        on_month_end,
    ),
    (
        (
            rf"(?:(?P<wd>{WEEKDAY})\s+)?(?:\b{DAY_ARTICLE}\s+|\b{ELIDED})?(?<!\d)"
            rf"(?P<d>{DAY_NUMBER})\s+(?:{OF}\s+)?(?P<mo>{MONTH})(?:\s+(?P<y>\d{{4}})"
            rf"|(?P<every>\s+(?:{alternatives(WORDS.every_year)})(?!\w)))?"
        ),
        on_date,
    ),
    (
        (
            rf"(?:(?P<wd>{WEEKDAY})\s+)?(?:\b{DAY_ARTICLE}\s+|\b{ELIDED})"
            r"(?P<d>\d{1,2})/(?P<mo>\d{1,2})(?:/(?P<y>\d{4}|\d{2}))?(?![\d/])"
        ),
        on_date,
    ),
    # "una volta ogni due settimane" before "ogni due settimane", or "una volta" would stay.
    (
        (
            rf"\b{phrase(WORDS.once)}\s+(?:(?:{alternatives(WORDS.per)})\s*"
            rf"|{EVERY}\s+(?:(?P<n>{NUMBER})\s+|(?P<pair>{PAIR}))?)"
            rf"(?P<u>{alternatives(ALL_UNIT_FORMS)})(?!\w)"
        ),
        on_every,
    ),
    (
        (
            rf"\b{EVERY}\s+(?:(?P<n>{NUMBER})\s+|(?P<pair>{PAIR}))?"
            rf"(?P<u>{alternatives(EVERY_UNIT_FORMS)})(?!\w)"
        ),
        on_every,
    ),
    (rf"\b(?:{alternatives(WORDS.after_dinner)})(?!\w)", on_after_dinner),
    (
        (
            rf"(?:\b{phrase(WORDS.before)}\s+{fused(WORDS.of_the)}"
            rf"|\b{UP_TO}\s+{fused(WORDS.to_the)}|\b{BY}\s+){timed(1)}"
        ),
        on_clock(Before),
    ),
    (
        (
            rf"(?:\b{phrase(WORDS.after)}\s+|\b{phrase(WORDS.starting_from)}\s+"
            rf"{fused(WORDS.from_the)}|{fused(WORDS.from_the)}){timed(1)}"
            rf"(?:\s+{phrase(WORDS.onwards)}(?!\w))?"
        ),
        on_clock(After),
    ),
    (rf"(?:\b{phrase(WORDS.toward)}\s+|{fused(WORDS.to_the)}){timed(1)}", on_clock(At)),
    (
        (
            rf"\b{phrase(WORDS.hours_word)}\s+(?P<t1>\d{{1,2}}(?:[:.,][0-5]\d(?!\d))?)"
            rf"(?:\s+(?P<p1>{SUFFIX}))?"
        ),
        on_clock(At),
    ),
    (
        (
            rf"\b(?P<r>{alternatives(RELATIVE_DAYS)})(?:\s+(?P<rp>{PART_WORD}))?(?!\w)"
            rf"|\b(?P<s>{alternatives(SHORT_PARTS)})(?!\w)"
        ),
        on_relative,
    ),
    (
        (
            rf"\b(?P<from>{alternatives((WORDS.from_the.joined, WORDS.from_the.plain))})"
            rf"\s+(?P<a>{WEEKDAY})\s+(?:{alternatives((WORDS.to_the.joined, WORDS.to_the.plain))})"
            rf"\s+(?P<b>{WEEKDAY})(?:\s+(?P<part>{PART_WORD}))?"
        ),
        on_day_range,
    ),
    (
        (
            rf"{NEGATION}?\b(?:{alternatives(WORDS.before_weekend)})\s+"
            rf"(?:{alternatives(WORDS.weekend)})(?!\w)"
        ),
        on_set(WEEKEND),
    ),
    (rf"{NEGATION}?\b(?:{alternatives(WORDS.working_days)})(?!\w)", on_set(WORKING_DAYS)),
    (rf"\b(?:{alternatives(WORDS.every_day)})(?!\w)", on_every_day),
    (
        (
            rf"{NEGATION}?(?:\b(?P<art>{ARTICLE})\s+)?\b(?P<list>{WEEKDAY}"
            rf"(?:\s*(?:,|{LIST_JOINS})\s*(?:{ARTICLE}\s+)?{WEEKDAY})*)"
            rf"(?:\s+(?P<next>{alternatives(WORDS.next)})(?!\w))?(?:\s+(?P<part>{PART_WORD}))?"
        ),
        on_weekdays,
    ),
    (
        (rf"\b(?:{alternatives(WORDS.before_parts)})\s+(?P<part>{alternatives(PARTS)})(?!\w)"),
        on_part,
    ),
]
COMPILED = [(re.compile(pattern), handle) for pattern, handle in PATTERNS]

LEFT = WORDS.leftover
LEFTOVER_WORDS = (
    *TIME.weekdays,
    *WORDS.weekday_plurals,
    *MONTHS,
    *PARTS,
    *WORDS.relative_days,
    *SHORT_PARTS,
    WORDS.noon,
    WORDS.midnight,
    *LEFT.words,
)
LEFTOVER = re.compile(
    rf"(?<![\w'])(?:{alternatives(LEFTOVER_WORDS)})(?![\w'])"
    rf"|(?<![\w'])(?:{alternatives(LEFT.before_span)})\s+(?:{phrase(LEFT.span_of)}\s+)?"
    rf"(?:{alternatives(LEFT.spans)})(?!\w)"
    rf"|(?<![\w'])(?:{alternatives(WORDS.all_of)})\s+"
    rf"(?:{alternatives((UNITS.week.other, UNITS.month.other, UNITS.year.other))})(?!\w)"
    rf"|(?<![\w'])(?:{alternatives(LEFT.this_year)})(?!\w)"
    rf"|(?<![\w'])(?:{alternatives((UNITS.week.one, UNITS.month.one))})\s+"
    rf"(?:{alternatives(LEFT.after_span)})(?!\w)"
    rf"|(?<![\w'])(?:{alternatives(LEFT.during_day)})\s+(?:{alternatives(LEFT.days)})(?!\w)"
    rf"|(?<![\w'])(?:{alternatives(LEFT.before_meal)})\s*(?:{alternatives(LEFT.meals)})(?!\w)"
    rf"|(?<![\w'])(?:{alternatives(LEFT.dawn_and_dusk)})(?!\w)"
    # An hour, or a day of the month without its month: "alle 25", "ogni mese il 15".
    rf"|(?<![\w'])(?:{alternatives(LEFT.before_number)})\s*\d+(?:[:.,]\d+)?(?![\d%°])"
    # A count of hours or minutes, whole: "da 20 minuti", "dopo 1,5 ore", "da 1 ora".
    rf"|\d+(?:[:.,]\d+)?\s*"
    rf"(?:{alternatives((*HOUR_FORMS, *MINUTE_FORMS, WORDS.hour_abbreviation))})(?!\w)"
    rf"|(?<![\w']){phrase(WORDS.yes)}\s+{AND}\s+(?:(?:{INDEFINITE})\s+)?{phrase(WORDS.no)}(?!\w)"
    rf"|(?<![\w']){phrase(LEFT.now_and_then)}(?!\w)"
    rf"|(?<![\w'])(?:{alternatives((*WORDS.within, WORDS.lasting, WORDS.every, WORDS.by))})\s+"
    rf"(?:{PAIR}|(?:[\w']+\s+){{0,2}})"
    rf"(?:{alternatives((*HOUR_FORMS, *MINUTE_FORMS, *ALL_UNIT_FORMS))})(?!\w)"
)
MODIFIERS_BEFORE = frozenset(WORDS.modifiers.before)
"""Words before a time that change it: "verso sera", "il secondo lunedì", "un quarto alle 9"."""
MODIFIERS_AFTER = frozenset(WORDS.modifiers.after)
LINKS = frozenset(WORDS.modifiers.links)
"""Words a modifier reaches across: "prima del 20 ottobre", "dopo il 5 ottobre", "prima e dopo
cena", "il primo e il terzo lunedì del mese"."""
WORD_BEFORE = re.compile(r"([\w']+)\s*$")
WORD_AFTER = re.compile(r"\s*([\w']+)")

QUOTED = re.compile(r'"[^"]*"|“[^”]*”|«[^»]*»')
NAME_INSIDE = re.compile(r"[^\W\d_][-._/@\\]\w|\w[-._/@\\][^\W\d_]|[^\W\d_]\d|\d[^\W\d_]")
HOUR_SIGN = phrase(WORDS.hour_abbreviation)
NOT_NAMES = re.compile(
    rf"{alternatives(WORDS.names.hyphenated)}|{HOUR_SIGN}\d{{1,2}}|\d{{1,2}}{HOUR_SIGN}|\d{{1,2}}º"
)
QUANTITY = re.compile(
    rf"(?<![\w'])(?:\d+|{alternatives(NUMBERS)})\s+(?:{alternatives(WORDS.names.counted)})(?!\w)"
)
"""A number that counts something is not an hour: "se arrivo alle 20 pagine"."""
DURATION = re.compile(
    rf"(?<![\w']){phrase(WORDS.hour_article)}\s+(?P<amount>(?:\d+|{alternatives(NUMBERS)})\s+"
    rf"(?:{alternatives((UNITS.hour.other, UNITS.minute.other))}))(?!\w)"
)
""""le 8 ore di lavoro": hours counted, not a time."""
NAMED_BY_TIME = re.compile(
    rf"(?<![\w']){phrase(WORDS.names.by_time)}\s+\d{{1,2}}(?:[:.,][0-5]\d)?(?!\d)"
)
""""il treno delle 7:40": a time that names a thing; but "prima delle 9" is a time."""
BEFORE_IT = re.compile(rf"\b{phrase(WORDS.before)}\s+$")
EVERY_TIME = re.compile(rf"\b{phrase(WORDS.every_time)}\b")
EVERY_WORDS = re.compile(rf"\b{EVERY}\b|\b(?:{alternatives(WORDS.all_of)})\b")


def masked(condition: str) -> str:
    """The condition in lower case, its names blanked out. The length does not change, so the
    offsets of a match are those of the condition."""
    chars = list(condition.replace("’", "'"))

    def blank(start: int, end: int) -> None:
        chars[start:end] = "\0" * (end - start)

    for found in QUOTED.finditer(condition):
        blank(*found.span())
    previous_name = False
    for index, token in enumerate(re.finditer(r"\S+", condition)):
        word = token.group().strip(',;:.!?«»"“”()[]')
        name = (
            (NAME_INSIDE.search(word) is not None and NOT_NAMES.fullmatch(word.lower()) is None)
            or (index > 0 and word[:1].isupper())
            or (previous_name and re.fullmatch(r"\d+(?:[.,]\d+)*", word) is not None)
        )
        if name:
            blank(*token.span())
        previous_name = name
    chars = [c.lower() if len(c.lower()) == 1 else c for c in chars]
    text = "".join(chars)
    for found in QUANTITY.finditer(text):
        blank(*found.span())
    for found in DURATION.finditer(text):
        blank(*found.span("amount"))
    for found in NAMED_BY_TIME.finditer(text):
        if BEFORE_IT.search(text[: found.start()]) is None:
            blank(*found.span())
    return "".join(chars)


def labels(condition: str) -> Labels:
    text = masked(condition)
    claimed: list[tuple[int, int]] = []
    pieces: list[Piece] = []
    for pattern, handle in COMPILED:
        for match in pattern.finditer(text):
            start, end = match.span()
            if start == end or any(start < e and s < end for s, e in claimed):
                continue
            found = handle(match)
            if found is not None:
                claimed.append((start, end))
                pieces.extend(found)
    spans = tuple(sorted(claimed))
    recurring = (
        EVERY_TIME.search(text) is not None
        or any(isinstance(piece, (Every, *RECURRING_DAYS)) for piece in pieces)
        or any(EVERY_WORDS.search(text, start, end) for start, end in spans)
    )
    unclear = _unclear(text, spans)
    if unclear:
        return Labels(spans, unclear, recurring)
    try:
        days, hours, period, frequency = combine(pieces)
    except Unclear:
        return Labels(spans, phrases(text, spans), recurring)
    return Labels(spans, (), recurring, days, hours, period, frequency)


def combine(
    pieces: list[Piece],
) -> tuple[DayLabel | None, HourLabel | None, PeriodLabel | None, Every | None]:
    """One label of each kind, or Unclear when the words disagree."""
    days: list[DayLabel] = [piece for piece in pieces if isinstance(piece, DAY_LABELS)]
    parts = {piece for piece in pieces if isinstance(piece, Part)}
    hours: list[ClockLabel] = [
        piece for piece in pieces if isinstance(piece, (At, After, Before, Between))
    ]
    minutes = [piece for piece in pieces if isinstance(piece, InMinutes)]
    periods: list[PeriodLabel] = [piece for piece in pieces if isinstance(piece, PERIOD_LABELS)]
    everies = [piece for piece in pieces if isinstance(piece, Every)]
    # "tutti i giorni tranne il sabato": the days left are the negation's.
    if len(days) == 2 and EVERY_DAY in days:
        other = days[1 - days.index(EVERY_DAY)]
        if isinstance(other, DayNames) and other.negated:
            days = [other]
    if any(len(found) > 1 for found in (days, parts, hours, minutes, periods, everies)):
        raise Unclear("the time words disagree")
    if minutes:
        if days or parts or hours or periods or everies:
            raise Unclear("«tra N ore» with other time words")
        return None, minutes[0], None, None
    day = days[0] if days else None
    period = periods[0] if periods else None
    every = everies[0] if everies else None
    # "ogni due settimane il lunedì" is a weekday every two weeks (#92).
    if (
        every is not None
        and every.unit is Unit.WEEK
        and isinstance(day, DayNames)
        and day.every
        and not day.negated
        and len(day.days) == 1
    ):
        day, every = WeekdayEveryWeeks(next(iter(day.days)), every.count), None
    weekly = isinstance(day, DayNames) and (day.every or day.negated)
    if (
        period is not None
        and day is not None
        and not weekly
        and not isinstance(day, RECURRING_DAYS)
    ):
        raise Unclear("a period and a date")
    if every is not None and day is not None and not weekly:
        raise Unclear("a frequency and a date, or a day of the month")
    part = next(iter(parts), None)
    if hours:
        return day, with_part(hours[0], part), period, every
    return day, part, period, every


def with_part(hours: ClockLabel, part: Part | None) -> ClockLabel:
    """ "stasera alle 9", "la sera tra le 9 e le 11": the part of the day moves the hours."""
    if part is None:
        return hours
    if isinstance(hours, Between):
        return Between(hours.start, hours.end, hours.start_part or part, hours.end_part or part)
    if hours.part not in (None, part):
        raise Unclear("two parts of the day")
    return type(hours)(hours.clock, part)


def _unclear(text: str, spans: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
    """Where the words not understood are: time words outside the spans, and a span with a word
    beside it that changes it ("verso sera", "il weekend prossimo"), with that word."""
    rest = list(text)
    for start, end in spans:
        rest[start:end] = " " * (end - start)
    regions = [[found.start(), found.end()] for found in LEFTOVER.finditer("".join(rest))]
    for start, end in spans:
        modifier = _modifier_before(text, start)
        after = WORD_AFTER.match(text, end)
        if modifier is not None:
            regions.append([modifier, end])
        elif after and after[1] in MODIFIERS_AFTER:
            regions.append([start, after.end(1)])
    for region in regions:
        modifier = _modifier_before(text, region[0])
        if modifier is not None:
            region[0] = modifier
    return phrases(text, [(start, end) for start, end in regions])


def phrases(text: str, spans: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """The spans as phrases, to name them: spans with only spaces between them are one."""
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and not text[merged[-1][1] : start].strip():
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return tuple((start, end) for start, end in merged)


def _modifier_before(text: str, start: int) -> int | None:
    """Where a word before `start` that changes what follows begins, if there is one."""
    found = WORD_BEFORE.search(text, 0, start)
    if found is None:
        return None
    if _modifies(found[1]):
        return found.start(1)
    if found[1] in LINKS:
        further = WORD_BEFORE.search(text, 0, found.start(1))
        if further is not None and _modifies(further[1]):
            return further.start(1)
    return None


def _modifies(word: str) -> bool:
    """Whether a word before a time changes it, also behind an elided article: "l'ultimo"."""
    return word.rpartition("'")[2] in MODIFIERS_BEFORE
