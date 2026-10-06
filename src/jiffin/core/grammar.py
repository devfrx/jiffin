"""Jiffin's own Italian time grammar: it finds the time words of a condition and labels them.

Technique A of #80 (ADR-0020). The vocabulary is closed, and a phrasing it does not know is never
guessed: time words left over after the match, or a word beside a match that changes it ("verso
sera", "prima di lunedì"), make the time unclear, and the labels say where those words are.
Names are not time: quoted names, words with a digit or a dot inside, capitalized words after
the first, the number after a name ("Windows 11"), a number that counts something ("alle 20
pagine"). The labels say what the words say; `meanings` knows what they mean.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from jiffin.core.schedule import MonthDay, MonthWeekday, Unit, YearDay


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


@dataclass(frozen=True, slots=True)
class Part:
    """A part of the day: "la sera", "stamattina"."""

    name: str


@dataclass(frozen=True, slots=True)
class At:
    """ "alle 15", "verso le 9", "a mezzogiorno"."""

    clock: Clock
    part: str | None = None


@dataclass(frozen=True, slots=True)
class After:
    """ "dopo le 23", "dalle 22 in poi"."""

    clock: Clock
    part: str | None = None


@dataclass(frozen=True, slots=True)
class Before:
    """ "prima delle 9", "fino alle 8"."""

    clock: Clock
    part: str | None = None


@dataclass(frozen=True, slots=True)
class Between:
    """ "dalle 14 alle 18", "tra le 9 e le 12"."""

    start: Clock
    end: Clock
    start_part: str | None = None
    end_part: str | None = None


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


# The vocabulary

NUMBERS = {
    "un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6,
    "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11, "dodici": 12, "tredici": 13,
    "quattordici": 14, "quindici": 15, "sedici": 16, "diciassette": 17, "diciotto": 18,
    "diciannove": 19, "venti": 20, "ventuno": 21, "ventidue": 22, "ventitré": 23,
    "ventitre": 23, "ventiquattro": 24, "venticinque": 25, "ventisei": 26, "ventisette": 27,
    "ventotto": 28, "ventinove": 29, "trenta": 30, "trentuno": 31,
}  # fmt: skip
MINUTE_WORDS = {
    **NUMBERS, "quaranta": 40, "quarantacinque": 45, "cinquanta": 50, "cinquantacinque": 55,
}  # fmt: skip
FRACTIONS = {"mezza": 30, "mezzo": 30, "un quarto": 15, "tre quarti": 45}
MONTHS = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
    "settembre", "ottobre", "novembre", "dicembre",
)  # fmt: skip
SHORT_PARTS = {
    "stamattina": "mattina",
    "stamani": "mattina",
    "stamane": "mattina",
    "stasera": "sera",
    "stanotte": "notte",
    "domattina": "mattina",
}
PLURAL_PARTS = {
    "mattino": "mattina",
    "mattine": "mattina",
    "pomeriggi": "pomeriggio",
    "sere": "sera",
    "notti": "notte",
}
RELATIVE_DAYS = {"oggi": 0, "domani": 1, "dopodomani": 2}
NTH = {"prim": 1, "second": 2, "terz": 3, "quart": 4, "ultim": -1}
UNITS = {"giorn": Unit.DAY, "settiman": Unit.WEEK, "mes": Unit.MONTH, "ann": Unit.YEAR}
EVERY_DAY = DayNames(frozenset(range(7)), every=True)
WEEKEND = frozenset({5, 6})
WORKING_DAYS = frozenset(range(5))
AFTER_DINNER = Clock(21)
""""dopo cena" is "dopo le 21" (#90)."""


def _alternatives(words: dict[str, int]) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


ACCENT = r"(?:ì|í|i'|i)"
WEEKDAY = (
    rf"(?:luned{ACCENT}|marted{ACCENT}|mercoled{ACCENT}|gioved{ACCENT}|venerd{ACCENT}"
    r"|sabat[oi]|domenic(?:a|he))(?![\w'])"
)
MONTH = rf"(?:{'|'.join(MONTHS)})(?!\w)"
PART_WORD = r"(?:mattin[ao]|pomeriggio|sera|notte)(?!\w)"
NUMBER = rf"(?:\d{{1,2}}|{_alternatives(NUMBERS)})(?![\w'])"
PAIR = r"un\s+paio\s+d(?:i\s+|')"
""""un paio d'ore" is 2 hours (#90); a pair of days is two days too."""
DAY_NUMBER = r"(?:\d{1,2}|primo|1°|1º)"
HOUR_WORD = _alternatives({word: number for word, number in NUMBERS.items() if number <= 24})
MINUTES = rf"(?:[0-5]?\d(?!\d)|(?:{_alternatives(MINUTE_WORDS)})(?![\w']))"
AND_MINUTES = (
    rf"(?:\s+e\s+(?:mezza|mezzo|un\s+quarto|tre\s+quarti|{MINUTES})"
    rf"|\s+meno\s+(?:un\s+quarto|{MINUTES}))"
)
CLOCK = (
    rf"(?:(?:ore\s+)?(?:\d{{1,2}}(?:[:.,][0-5]\d(?!\d))?|(?:{HOUR_WORD})(?!\w))"
    rf"{AND_MINUTES}?(?:\s+in\s+punto)?)"
)
WITH_ARTICLE = rf"(?:le\s+{CLOCK}|l'(?:una|1){AND_MINUTES}?|la\s+mezzanotte{AND_MINUTES}?)"
BARE = rf"(?:mezzogiorno{AND_MINUTES}?|mezzanotte{AND_MINUTES}?)"
SUFFIX = rf"(?:di|del|della|al|alla)\s+{PART_WORD}"
NEGATION = r"(?P<neg>(?:\bma\s+)?(?:\bnon|\btranne(?:\s+che)?|\beccetto|\bsalvo|\besclus[oaie])\s+)"
ARTICLE = r"(?:ogni|tutti\s+i|tutte\s+le|il|la|i|le|di|nei|nelle)"


def timed(n: int) -> str:
    """A time with its article ("le 9", "l'una", "mezzogiorno") and a part of the day."""
    return rf"(?P<t{n}>{WITH_ARTICLE}|{BARE})(?:\s+(?P<p{n}>{SUFFIX}))?"


def fused(joined: str, plain: str) -> str:
    """A preposition before timed(): fused with the article ("alle 9") or not ("a mezzogiorno")."""
    return rf"(?:\b{joined}(?=l)|\b{plain}\s+(?=mezz))"


def parse_time(text: str) -> Clock | None:
    words = re.sub(r"\s+", " ", text).strip()
    words = re.sub(r"^(?:le |la |l')", "", words)
    words = re.sub(r"^ore ", "", words)
    words = re.sub(r" in punto$", "", words)
    for name, hour in (("mezzogiorno", 12), ("mezzanotte", 0)):
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
        found = re.fullmatch(r"[:.,](\d{2})|(e|meno) (.+)", rest)
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
            minutes = amount if found[2] == "e" else -amount
    if not 0 <= hour <= 24 or minutes > 59 or (hour == 24 and minutes > 0):
        return None
    total = (hour * 60 + minutes) % (24 * 60)
    return Clock(total // 60, total % 60)


def part_name(text: str) -> str:
    word = text.split()[-1]
    return PLURAL_PARTS.get(word, word)


def optional_part(text: str | None) -> str | None:
    return None if text is None else part_name(text)


def weekday_index(text: str) -> int:
    return ("lun", "mar", "mer", "gio", "ven", "sab", "dom").index(text[:3])


def counted(match: re.Match[str]) -> int:
    """The number of a match with the groups `n` and `pair`."""
    if match["pair"]:
        return 2
    number = match["n"]
    return int(number) if number.isdigit() else NUMBERS[number]


def day_number(text: str) -> int:
    return 1 if text in ("primo", "1°", "1º") else int(text)


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
        whole = re.sub(r"\s+", " ", match["w"])
        minutes = {"un'ora": 60, "mezz'ora": 30, "mezzora": 30, "un quarto d'ora": 15}.get(
            whole, 45
        )
    else:
        minutes = counted(match) * (60 if match["pair"] or match["u"].startswith("or") else 1)
    if match["xm"]:
        minutes += int(match["xm"])
    elif match["x"]:
        minutes += 15 if "quarto" in match["x"] else 30
    return [InMinutes(minutes)]


def on_days_in(match: re.Match[str]) -> list[Piece]:
    return [InDays(counted(match) * (7 if match["u"].startswith("settiman") else 1))]


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
    return [Until(InDays(RELATIVE_DAYS[match["r"]]))]


def on_until_date(match: re.Match[str]) -> list[Piece]:
    if match["mo"]:
        return [Until(date_words(match))]
    return [Until(NextDayOfMonth(day_number(match["d"])))]


def on_for_days(match: re.Match[str]) -> list[Piece]:
    return [ForDays(counted(match) * (7 if match["u"].startswith("settiman") else 1))]


def on_week(match: re.Match[str]) -> list[Piece]:
    return [NextWeek() if match["next"] else ThisWeek()]


def on_every_other_week(match: re.Match[str]) -> list[Piece]:
    return [WeekdayEveryWeeks(weekday_index(match["wd"]), 2)]


def on_month_weekday(match: re.Match[str]) -> list[Piece]:
    return [MonthWeekday(weekday_index(match["wd"]), NTH[match["nth"][:-1]])]


def on_month_day(match: re.Match[str]) -> list[Piece]:
    return [MonthDay(day_number(match["d"]))]


def on_month_end(match: re.Match[str]) -> list[Piece]:
    return [MonthDay(-1)]


def on_every(match: re.Match[str]) -> list[Piece]:
    number = counted(match) if match["n"] or match["pair"] else 1
    unit = next(unit for stem, unit in UNITS.items() if match["u"].startswith(stem))
    return [Every(number, unit)]


def on_relative(match: re.Match[str]) -> list[Piece]:
    if match["s"]:
        return [InDays(int(match["s"] == "domattina")), Part(SHORT_PARTS[match["s"]])]
    found: list[Piece] = [InDays(RELATIVE_DAYS[re.sub(r"\s+", "", match["r"])])]
    if match["rp"]:
        found.append(Part(part_name(match["rp"])))
    return found


def on_day_range(match: re.Match[str]) -> list[Piece]:
    first, last = weekday_index(match["a"]), weekday_index(match["b"])
    found: list[Piece]
    if match["from"] == "da":
        found = [WeekdaysOnce(first, last)]
    else:
        days = frozenset((first + step) % 7 for step in range((last - first) % 7 + 1))
        found = [DayNames(days, every=True)]
    if match["part"]:
        found.append(Part(part_name(match["part"])))
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
    plural = any(name in ("sabati", "domeniche") for name in names)
    every = (match["art"] is not None or plural) and match["next"] is None
    found: list[Piece] = [DayNames(days, every, negated=match["neg"] is not None)]
    if match["part"]:
        found.append(Part(part_name(match["part"])))
    return found


def on_part(match: re.Match[str]) -> list[Piece]:
    return [Part(part_name(match["part"]))]


# Tried in order; a match may not overlap an earlier one.
PATTERNS: list[tuple[str, Handler]] = [
    (
        (
            rf"\b(?:tra|fra)\s+(?:(?P<n>{NUMBER})\s+(?P<u>ore|ora|minuti|minuto)(?!\w)"
            rf"|(?P<pair>{PAIR})ore(?!\w)"
            r"|(?P<w>un'ora|mezz'ora|mezzora|un\s+quarto\s+d'ora|tre\s+quarti\s+d'ora))"
            r"(?:\s+e\s+(?P<x>mezza|mezzo|un\s+quarto|(?P<xm>\d{1,2})\s+minuti))?"
        ),
        on_minutes,
    ),
    (
        (
            rf"\b(?:tra|fra)\s+(?:(?P<n>{NUMBER})\s+|(?P<pair>{PAIR}))"
            r"(?P<u>giorni|giorno|settimane|settimana)(?!\w)"
        ),
        on_days_in,
    ),
    (rf"\b(?:tra|fra)\s+{timed(1)}\s+e\s+{timed(2)}", on_between),
    (
        rf"{fused('dal', 'da')}{timed(1)}\s+(?:fino\s+)?{fused('al', 'a')}{timed(2)}",
        on_between,
    ),
    (
        (
            rf"\bdal(?:l'|\s+)(?P<d1>{DAY_NUMBER})(?:\s+(?:di\s+)?(?P<mo1>{MONTH}))?"
            rf"\s+(?:fino\s+)?al(?:l'|\s+)(?P<d2>{DAY_NUMBER})\s+(?:di\s+)?(?P<mo2>{MONTH})"
            r"(?:\s+(?P<y>\d{4}))?"
        ),
        on_date_range,
    ),
    (
        (
            rf"\b(?:fino\s+a|entro)\s+(?:(?P<wd>{WEEKDAY})(?:\s+(?P<d>{DAY_NUMBER})\s+"
            rf"(?:di\s+)?(?P<mo>{MONTH})(?:\s+(?P<y>\d{{4}}))?)?"
            r"|(?P<r>oggi|domani|dopodomani)(?!\w))"
        ),
        on_until,
    ),
    (
        (
            rf"\b(?:fino\s+al(?:l'|\s+)|entro\s+(?:il\s+|l'))(?P<d>{DAY_NUMBER})"
            rf"(?:\s+(?:di\s+)?(?P<mo>{MONTH})(?:\s+(?P<y>\d{{4}}))?)?(?![\d/])"
        ),
        on_until_date,
    ),
    (
        (
            rf"\bper\s+(?:(?P<n>{NUMBER})\s+|(?P<pair>{PAIR}))"
            r"(?P<u>giorni|giorno|settimane|settimana)(?!\w)"
        ),
        on_for_days,
    ),
    (
        (
            r"\b(?:(?:in\s+)?questa\s+settimana"
            r"|(?P<next>(?:la\s+|nella\s+)?(?:prossima\s+settimana|settimana\s+prossima)))(?!\w)"
        ),
        on_week,
    ),
    (
        rf"\bun[oa]?\s+(?P<wd>{WEEKDAY})\s+s{ACCENT}\s+e\s+un[oa]?\s+(?:{WEEKDAY}\s+)?no(?!\w)",
        on_every_other_week,
    ),
    (
        (
            rf"(?:\b(?:ogni|il|la)\s+|\bl')?(?P<nth>prim[oa]|second[oa]|terz[oa]|quart[oa]"
            rf"|ultim[oa])\s+(?P<wd>{WEEKDAY})\s+(?:del|di\s+ogni)\s+mese(?!\w)"
        ),
        on_month_weekday,
    ),
    (
        rf"(?:\b(?:ogni|il)\s+|\bl')?(?<!\d)(?P<d>{DAY_NUMBER})\s+(?:del|di\s+ogni)\s+mese(?!\w)",
        on_month_day,
    ),
    (
        (
            r"\b(?:a|ogni)\s+fine\s+mese(?!\w)"
            r"|(?:\bl'|\bogni\s+)ultimo\s+giorno\s+(?:del|di\s+ogni)\s+mese(?!\w)"
        ),
        on_month_end,
    ),
    (
        (
            rf"(?:(?P<wd>{WEEKDAY})\s+)?(?:\bil\s+|\bl')?(?<!\d)(?P<d>{DAY_NUMBER})\s+(?:di\s+)?"
            rf"(?P<mo>{MONTH})(?:\s+(?P<y>\d{{4}})|(?P<every>\s+(?:di\s+)?ogni\s+anno(?!\w)))?"
        ),
        on_date,
    ),
    (
        (
            rf"(?:(?P<wd>{WEEKDAY})\s+)?(?:\bil\s+|\bl')(?P<d>\d{{1,2}})/(?P<mo>\d{{1,2}})"
            r"(?:/(?P<y>\d{4}|\d{2}))?(?![\d/])"
        ),
        on_date,
    ),
    # "una volta ogni due settimane" before "ogni due settimane", or "una volta" would stay.
    (
        (
            rf"\buna\s+volta\s+(?:a(?:l|lla|ll')?\s*"
            rf"|ogni\s+(?:(?P<n>{NUMBER})\s+|(?P<pair>{PAIR}))?)"
            r"(?P<u>giorno|giorni|settimana|settimane|mese|mesi|anno|anni)(?!\w)"
        ),
        on_every,
    ),
    (
        (
            rf"\bogni\s+(?:(?P<n>{NUMBER})\s+|(?P<pair>{PAIR}))?"
            r"(?P<u>giorni|settimane|settimana|mesi|mese|anni|anno)(?!\w)"
        ),
        on_every,
    ),
    (r"\bdopo\s+(?:la\s+)?cena(?!\w)", on_after_dinner),
    (
        rf"(?:\bprima\s+{fused('del', 'di')}|\bfino\s+{fused('al', 'a')}|\bentro\s+){timed(1)}",
        on_clock(Before),
    ),
    (
        (
            rf"(?:\bdopo\s+|\ba\s+partire\s+{fused('dal', 'da')}|{fused('dal', 'da')}){timed(1)}"
            r"(?:\s+in\s+poi(?!\w))?"
        ),
        on_clock(After),
    ),
    (rf"(?:\bverso\s+|{fused('al', 'a')}){timed(1)}", on_clock(At)),
    (
        rf"\bore\s+(?P<t1>\d{{1,2}}(?:[:.,][0-5]\d(?!\d))?)(?:\s+(?P<p1>{SUFFIX}))?",
        on_clock(At),
    ),
    (
        (
            rf"\b(?P<r>oggi|domani|dopodomani|dopo\s+domani)(?:\s+(?P<rp>{PART_WORD}))?(?!\w)"
            r"|\b(?P<s>stamattina|stamani|stamane|stasera|stanotte|domattina)(?!\w)"
        ),
        on_relative,
    ),
    (
        (
            rf"\b(?P<from>dal|da)\s+(?P<a>{WEEKDAY})\s+al?\s+(?P<b>{WEEKDAY})"
            rf"(?:\s+(?P<part>{PART_WORD}))?"
        ),
        on_day_range,
    ),
    (
        (
            rf"{NEGATION}?\b(?:nel|nei|il|durante\s+il|durante\s+i|ogni|tutti\s+i|i|di|per\s+il"
            r"|al)\s+(?:weekend|week-end|fine\s+settimana|fine-settimana|finesettimana)(?!\w)"
        ),
        on_set(WEEKEND),
    ),
    (
        (
            rf"{NEGATION}?\b(?:(?:nei|i|durante\s+i|tutti\s+i|di)\s+giorni\s+"
            r"(?:feriali|lavorativi)|nei\s+feriali|in\s+settimana)(?!\w)"
        ),
        on_set(WORKING_DAYS),
    ),
    (r"\b(?:ogni\s+giorno|tutti\s+i\s+giorni)(?!\w)", on_every_day),
    (
        (
            rf"{NEGATION}?(?:\b(?P<art>{ARTICLE})\s+)?\b(?P<list>{WEEKDAY}"
            rf"(?:\s*(?:,|\be\b|\bed\b)\s*(?:{ARTICLE}\s+)?{WEEKDAY})*)"
            rf"(?:\s+(?P<next>prossim[oa])(?!\w))?(?:\s+(?P<part>{PART_WORD}))?"
        ),
        on_weekdays,
    ),
    (
        (
            r"\b(?:la|di|alla|ogni|nella|il|nel|al|tutte\s+le|le|tutti\s+i|i)\s+"
            r"(?P<part>mattin[ao]|mattine|pomeriggio|pomeriggi|sera|sere|notte|notti)(?!\w)"
        ),
        on_part,
    ),
]
COMPILED = [(re.compile(pattern), handle) for pattern, handle in PATTERNS]

LEFTOVER = re.compile(
    r"(?<![\w'])(?:"
    r"(?:luned|marted|mercoled|gioved|venerd)(?:ì|í|i'|i)|sabat[oi]|domenic(?:a|he)"
    rf"|{'|'.join(MONTHS)}"
    r"|mattin[aoe]|mattinat[ae]|pomerigg(?:io|i)|ser[ae]|serat[ae]|nott[ei]|nottat[ae]"
    r"|oggi|domani|dopodomani|ieri|altroieri|avantieri|stamattina|stamani|stamane|stasera"
    r"|stanotte|domattina|weekend|week-end|finesettimana|feriali|festivi|prefestivi|lavorativi"
    r"|mezzogiorno|mezzanotte|mezz'ora|mezzora|un'ora|tardi|orario"
    r")(?![\w'])"
    r"|(?<![\w'])(?:quest[oa]|prossim[oa]|scors[oa]|ogni|fine|inizio|met[àa]|entro"
    r"|tutt[oa]\s+(?:il|la)|durante\s+la|nella|per\s+la)\s+(?:del\s+)?"
    r"(?:settimana|mese|anno|giorno|giornata)(?!\w)"
    r"|(?<![\w'])tutt[ie]\s+(?:i|le|gli)\s+(?:settimane|mesi|anni)(?!\w)"
    r"|(?<![\w'])quest'(?:anno|oggi)(?!\w)"
    r"|(?<![\w'])(?:settimana|mese)\s+(?:prossim[oa]|scors[oa])(?!\w)"
    r"|(?<![\w'])(?:di|durante\s+il|in)\s+(?:giorno|giornata)(?!\w)"
    r"|(?<![\w'])(?:dopo|prima\s+di|prima\s+del(?:la)?|prima\s+dell'|verso|durante\s+(?:la|il)"
    r"|in\s+pausa|a|all'ora\s+di)\s*(?:colazione|pranzo|cena|merenda|aperitivo)(?!\w)"
    r"|(?<![\w'])(?:all'alba|al\s+tramonto)(?!\w)"
    # An hour, or a day of the month without its month: "alle 25", "ogni mese il 15".
    r"|(?<![\w'])(?:alle|dalle|delle|le|l'|ore|h|il|dal|dall'|al|all')\s*\d+(?:[:.,]\d+)?"
    r"(?![\d%°])"
    # A count of hours or minutes, whole: "da 20 minuti", "dopo 1,5 ore".
    r"|\d+(?:[:.,]\d+)?\s*(?:ore|minuti|h)(?!\w)"
    rf"|(?<![\w'])s{ACCENT}\s+e\s+(?:un[oa]?\s+)?no(?!\w)"
    r"|(?<![\w'])ogni\s+tanto(?!\w)"
    rf"|(?<![\w'])(?:tra|fra|per|ogni|entro)\s+(?:{PAIR}|(?:[\w']+\s+){{0,2}})"
    r"(?:minut[oi]|or[ae]|giorn[oi]|settiman[ae]|mes[ei]|ann[oi])(?!\w)"
)
MODIFIERS_BEFORE = {
    "verso", "intorno", "circa", "attorno", "questo", "questa", "quel", "quella", "prossimo",
    "prossima", "scorso", "scorsa", "ultimo", "ultima", "primo", "prima", "secondo", "seconda",
    "terzo", "terza", "quarto", "quarta", "quinto", "quinta", "tardo", "tarda", "fine",
    "inizio", "metà", "da", "dal", "dalla", "fino", "entro", "oltre", "dopo",
}  # fmt: skip
"""Words before a time that change it: "verso sera", "il secondo lunedì", "un quarto alle 9"."""
MODIFIERS_AFTER = {
    "circa", "prossimo", "prossima", "scorso", "scorsa", "inoltrata", "tardi", "presto",
    "passate", "precise", "esatte",
}  # fmt: skip
LINKS = {
    "di", "del", "della", "dello", "dell'", "dei", "degli", "delle", "il", "lo", "la", "l'",
    "i", "gli", "le", "a", "al", "alla", "all'", "ai", "alle", "in", "nel", "nella", "e", "ed",
}  # fmt: skip
"""Words a modifier reaches across: "prima del 20 ottobre", "dopo il 5 ottobre", "prima e dopo
cena", "il primo e il terzo lunedì del mese"."""
WORD_BEFORE = re.compile(r"([\w']+)\s*$")
WORD_AFTER = re.compile(r"\s*([\w']+)")

QUOTED = re.compile(r'"[^"]*"|“[^”]*”|«[^»]*»')
NAME_INSIDE = re.compile(r"[^\W\d_][-._/@\\]\w|\w[-._/@\\][^\W\d_]|[^\W\d_]\d|\d[^\W\d_]")
NOT_NAMES = re.compile(r"week-end|fine-settimana|h\d{1,2}|\d{1,2}h|\d{1,2}º")
COUNTED = (
    r"(?:pagin[ae]|righ[ae]|parol[ae]|slide|e-?mail|messaggi|persone|euro|punti|km|chilometri"
    r"|passi|file|foto|video|episodi|capitoli|esercizi|domande)"
)
QUANTITY = re.compile(rf"(?<![\w'])(?:\d+|{_alternatives(NUMBERS)})\s+{COUNTED}(?!\w)")
"""A number that counts something is not an hour: "se arrivo alle 20 pagine"."""
DURATION = re.compile(
    rf"(?<![\w'])le\s+(?P<amount>(?:\d+|{_alternatives(NUMBERS)})\s+(?:ore|minuti))(?!\w)"
)
""""le 8 ore di lavoro": hours counted, not a time."""
NAMED_BY_TIME = re.compile(r"(?<![\w'])delle\s+\d{1,2}(?:[:.,][0-5]\d)?(?!\d)")
""""il treno delle 7:40": a time that names a thing; but "prima delle 9" is a time."""
EVERY_TIME = re.compile(r"\bogni\s+volta\b")
EVERY_WORDS = re.compile(r"\bogni\b|\btutt[ie]\s+(?:i|le|gli)\b")


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
        if re.search(r"\bprima\s+$", text[: found.start()]) is None:
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
    parts = {piece.name for piece in pieces if isinstance(piece, Part)}
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
    return day, (Part(part) if part else None), period, every


def with_part(hours: ClockLabel, part: str | None) -> ClockLabel:
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
