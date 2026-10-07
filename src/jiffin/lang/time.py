"""The words of a time (ADR-0026), from `it/time.toml`: `TIME`, what the grammar of `core`
reads in a condition and what `ui/words.py` writes back. The rules that put them together are
theirs."""

from collections.abc import Mapping
from dataclasses import dataclass

from jiffin.lang import Plural, read


@dataclass(frozen=True, slots=True)
class Gendered:
    masculine: str
    feminine: str


@dataclass(frozen=True, slots=True)
class Ordinals:
    first: Gendered
    second: Gendered
    third: Gendered
    fourth: Gendered
    last: Gendered


@dataclass(frozen=True, slots=True)
class Units:
    hour: Plural
    minute: Plural
    day: Plural
    week: Plural
    month: Plural
    year: Plural


@dataclass(frozen=True, slots=True)
class PartWords:
    """By `core.grammar.Part`."""

    morning: tuple[str, ...]
    afternoon: tuple[str, ...]
    evening: tuple[str, ...]
    night: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShortParts:
    this_morning: tuple[str, ...]
    this_evening: tuple[str, ...]
    tonight: tuple[str, ...]
    tomorrow_morning: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Fused:
    """A preposition fused with the article that follows it, and alone: "dal", "da"."""

    joined: str
    plain: str


@dataclass(frozen=True, slots=True)
class Leftover:
    words: tuple[str, ...]
    before_span: tuple[str, ...]
    span_of: str
    spans: tuple[str, ...]
    this_year: tuple[str, ...]
    after_span: tuple[str, ...]
    during_day: tuple[str, ...]
    days: tuple[str, ...]
    before_meal: tuple[str, ...]
    meals: tuple[str, ...]
    dawn_and_dusk: tuple[str, ...]
    before_number: tuple[str, ...]
    now_and_then: str


@dataclass(frozen=True, slots=True)
class Modifiers:
    before: tuple[str, ...]
    after: tuple[str, ...]
    links: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Names:
    hyphenated: tuple[str, ...]
    counted: tuple[str, ...]
    by_time: str


@dataclass(frozen=True, slots=True)
class Remainder:
    connectors: tuple[str, ...]
    leads: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Read:
    weekday_plurals: tuple[str, ...]
    first_of_month: tuple[str, ...]
    within: tuple[str, ...]
    pair: tuple[str, ...]
    lasting: str
    up_to: str
    by: str
    before: str
    after: str
    toward: str
    starting_from: str
    onwards: str
    every: str
    conjunction: str
    list_joins: tuple[str, ...]
    minus: str
    hours_word: str
    hour_abbreviation: str
    sharp: str
    noon: str
    midnight: str
    hour_article: str
    midnight_article: str
    elided_article: str
    one_oclock: tuple[str, ...]
    day_article: str
    of: str
    every_year: tuple[str, ...]
    of_month: tuple[str, ...]
    before_month_weekday: tuple[str, ...]
    before_month_day: tuple[str, ...]
    month_end: tuple[str, ...]
    month_last_day: tuple[str, ...]
    this_week: tuple[str, ...]
    next_week: tuple[str, ...]
    indefinite: tuple[str, ...]
    yes: str
    no: str
    once: str
    per: tuple[str, ...]
    after_dinner: tuple[str, ...]
    relative_days: Mapping[str, int]
    split_relative_days: Mapping[str, int]
    weekend: tuple[str, ...]
    before_weekend: tuple[str, ...]
    working_days: tuple[str, ...]
    every_day: tuple[str, ...]
    before_weekdays: tuple[str, ...]
    next: tuple[str, ...]
    before_parts: tuple[str, ...]
    but: str
    negations: tuple[str, ...]
    part_prepositions: tuple[str, ...]
    every_time: str
    all_of: tuple[str, ...]
    numbers: Mapping[str, int]
    minute_numbers: Mapping[str, int]
    fractions: Mapping[str, int]
    minus_fractions: Mapping[str, int]
    durations: Mapping[str, int]
    added_minutes: Mapping[str, int]
    parts: PartWords
    part_plurals: PartWords
    short_parts: ShortParts
    from_the: Fused
    to_the: Fused
    of_the: Fused
    leftover: Leftover
    modifiers: Modifiers
    names: Names
    remainder: Remainder


@dataclass(frozen=True, slots=True)
class HourWords:
    moment: str
    midnight: str
    slot: str
    moment_night: str
    slot_night: str


@dataclass(frozen=True, slots=True)
class DayWords:
    every_day: str
    every: str
    every_day_but: str
    the: str
    the_feminine: str
    run: str
    run_from_feminine: str
    run_to_feminine: str
    dated: str
    dated_elided: str


@dataclass(frozen=True, slots=True)
class RecurringWords:
    alternate: str
    alternate_feminine: str
    every_weeks: str
    every_weeks_feminine: str
    month_weekday: str
    month_weekday_feminine: str
    month_weekday_elided: str
    month_last_day: str
    month_day: str
    year_day: str
    numbered: str
    numbered_elided: str
    first_of_month: str


@dataclass(frozen=True, slots=True)
class PeriodWords:
    since: str
    until: str
    from_today: str
    range: str


@dataclass(frozen=True, slots=True)
class ByUnit:
    """By `core.schedule.Unit`."""

    day: str
    week: str
    month: str
    year: str


@dataclass(frozen=True, slots=True)
class Write:
    yesterday: str
    today: str
    tomorrow: str
    numbers: Mapping[str, str]
    """Counts written in words, by the count: "2" is "due"."""
    hours: HourWords
    days: DayWords
    recurring: RecurringWords
    period: PeriodWords
    once: ByUnit
    once_every: ByUnit


@dataclass(frozen=True, slots=True)
class Time:
    final_i: tuple[str, ...]
    weekdays: tuple[str, ...]
    """Monday first."""
    months: tuple[str, ...]
    """January first."""
    ordinals: Ordinals
    units: Units
    read: Read
    write: Write


TIME = read(Time, "time.toml")
