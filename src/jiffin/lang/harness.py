"""The texts of the harness's pages (ADR-0026), from `it/harness.toml`: `HARNESS`, read by the
harness alone. Neither this module nor its file ships with the app (ADR-0017)."""

from collections.abc import Mapping
from dataclasses import dataclass

from jiffin.lang import read


@dataclass(frozen=True, slots=True)
class Report:
    title: str
    heading: str
    from_copy: str
    replayed: str
    intro: str
    alerts: str
    time: str
    context: str
    reminder: str
    label: str
    answer: str
    delay: str
    time_only: str
    right: str
    false_alarm: str
    why: str
    highest_d: str
    missed: str
    missed_intro: str
    reminded: str
    reminded_intro: str
    reasons: Mapping[str, str]
    """By the reason `harness.day` names: "below threshold"."""
    answers: Mapping[str, str]
    """By the answer as `store` keeps it: "not_here"."""


@dataclass(frozen=True, slots=True)
class Statements:
    title: str
    heading: str
    intro: str
    state: str
    condition: str
    time: str
    remainder: str
    action: str
    statement: str
    build: str
    active: str
    completed: str
    unclear: str
    no_time: str
    time_only: str
    no_statement: str
    not_written: str
    written_by: str


@dataclass(frozen=True, slots=True)
class Label:
    title: str
    loading: str
    question: str
    yes: str
    no: str
    back: str
    next: str
    hint: str
    done: str
    finished: str
    all_labelled: str
    may_close: str
    some_left: str
    position: str
    was_on: str
    untitled: str
    the_reminder: str
    remind_me: str
    labelled: str
    saved: str
    not_saved: str
    nothing: str
    not_loaded: str


@dataclass(frozen=True, slots=True)
class Sample:
    condition_starts: tuple[str, ...]
    remind_me: str
    of: str


@dataclass(frozen=True, slots=True)
class Harness:
    report: Report
    statements: Statements
    label: Label
    sample: Sample


HARNESS = read(Harness, "harness.toml")
