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
    requested: str
    requested_intro: str
    situations: str
    situations_intro: str
    kind: str
    start: str
    end: str
    app: str
    state: str
    call: str
    absence: str
    confirmed: str
    marked_wrong: str
    added: str
    unchecked: str
    units: str
    units_intro: str
    reasons: Mapping[str, str]
    """By the reason `harness.day` names: "below threshold"."""
    learned: Mapping[str, str]
    """By the reason `harness.day.under` names: "for Remind here"."""
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
    situations: str
    remainder: str
    action: str
    statement: str
    build: str
    active: str
    completed: str
    unclear: str
    no_time: str
    no_situation: str
    nothing_left: str
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
class Calls:
    title: str
    heading: str
    intro: str
    meaning: str
    loading: str
    kind: str
    app: str
    start: str
    end: str
    in_front: str
    mark: str
    add_heading: str
    add: str
    check: str
    recorded: str
    none: str
    call: str
    absence: str
    nothing: str
    wrong: str
    added: str
    none_added: str
    other_app: str
    remove: str
    remove_confirm: str
    times_needed: str
    ends_before: str
    not_checked: str
    checked_at: str
    saved: str
    not_saved: str
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
    calls: Calls
    sample: Sample


HARNESS = read(Harness, "harness.toml")
