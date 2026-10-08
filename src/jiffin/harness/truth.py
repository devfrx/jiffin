"""The situations as they were, against which the report counts (ADR-0028, ADR-0031).

`core` rings a reminder on its situations as the capture read them; the owner gives the truth on
calls and absences (`calls`), and the other situations count as recorded. A situation holds with
a value over the union of the stretches whose values it holds with, as `core` follows it; an end
is where such a union ends, unless the situations stopped being read then, as at the app's
close: `core` hears no end there. The owner's times and the recorded ones may differ by up to a
minute: a stretch is wrong only beyond it (ADR-0031).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from jiffin.core.clock import Clock
from jiffin.core.records import Revision
from jiffin.core.reminders import MINUTE_MS
from jiffin.core.schedule import jiffin_day
from jiffin.core.situations import Ends, Holds, Lasts, Situation, SituationStretch, holds
from jiffin.core.units import Times
from jiffin.harness import calls as owners
from jiffin.harness.calls import Calls

TOLERANCE_MS = 60_000
"""How far the owner's times and the recorded ones may be apart and still agree (ADR-0031)."""
ALWAYS_VALUED = frozenset(
    {Situation.AWAY, Situation.POWER, Situation.DISPLAY, Situation.HEADPHONES}
)
"""The situations that have a value whenever they are read: one of them that ends with no other
value starting then was not read any more, as at the app's close."""


def unread(stretches: Iterable[SituationStretch]) -> frozenset[int]:
    """When the situations stopped being read, from the stretches of those always valued: one
    that ends with no other of its situation starting then."""
    found = list(stretches)
    starts = {(s.situation, s.since) for s in found}
    return frozenset(
        s.until
        for s in found
        if s.situation in ALWAYS_VALUED and (s.situation, s.until) not in starts
    )


@dataclass(frozen=True, slots=True)
class Truth:
    recorded: tuple[SituationStretch, ...]
    """The stretches the app recorded."""
    true: tuple[SituationStretch, ...]
    """The stretches as they were: those recorded, without the calls and absences the owner
    marked wrong and with those the owner added, once the owner checked them."""
    added: tuple[SituationStretch, ...]
    """Those the owner added: the capture missed or misread them."""
    wrong: tuple[SituationStretch, ...]
    """Those recorded that the owner marked wrong."""
    checked: bool
    """The owner checked the calls and absences: before, those recorded count as true."""
    unread: frozenset[int]
    """When the situations stopped being read, from those recorded: no end there."""

    @classmethod
    def of(cls, recorded: Sequence[SituationStretch], calls: Calls | None) -> "Truth":
        true = owners.truth(recorded, calls)
        return cls(
            recorded=tuple(recorded),
            true=tuple(true),
            added=tuple(s for s in true if s not in recorded),
            wrong=tuple(s for s in recorded if s not in true),
            checked=calls is not None and calls.checked is not None,
            unread=unread(recorded),
        )


def intervals(
    stretches: Iterable[SituationStretch], situation: Situation, value: str | None
) -> list[tuple[int, int]]:
    """When the situation held with `value`, as (since, until): the stretches of the values it
    holds with, merged where they touch, as `core` follows it (`Situations`)."""
    merged: list[tuple[int, int]] = []
    for since, until in sorted(
        (s.since, s.until)
        for s in stretches
        if s.situation is situation and holds(situation, value, frozenset({s.value}))
    ):
        if merged and since <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], until))
        else:
            merged.append((since, until))
    return merged


def ends(
    stretches: Iterable[SituationStretch],
    situation: Situation,
    value: str | None,
    unread_at: frozenset[int],
) -> list[int]:
    """When the situation stopped holding with `value`, by a change: not where it stopped being
    read."""
    return [until for _, until in intervals(stretches, situation, value) if until not in unread_at]


def holds_at(revision: Revision, at: int, truth: Truth, clock: Clock) -> bool:
    """Whether the situations of the revision held at `at`, by the truth, as `core` reads them
    (ADR-0028): an end counts from when it came, after the condition was written and within the
    window of its time, until the next one; with "Ogni volta", within its Jiffin day. The
    duration of the thing the judge checks is no situation: `day` reads it from the labels."""
    for term in revision.situations:
        match term:
            case Holds(situation, value):
                if not any(s <= at < u for s, u in intervals(truth.true, situation, value)):
                    return False
            case Lasts(minutes, situation, value) if situation is not None:
                spans = intervals(truth.true, situation, value)
                if not any(s + minutes * MINUTE_MS <= at < u for s, u in spans):
                    return False
            case Ends(situation, value):
                true_ends = ends(truth.true, situation, value, truth.unread)
                if _last_end(revision, true_ends, at, clock) is None:
                    return False
    return True


def supported(revision: Revision, at: int, truth: Truth) -> bool:
    """Whether the truth bears out the situations of an alert that became due at `at`, within a
    minute: what held, held then; the end it rang for came, within a minute of when the app
    recorded it."""
    for term in revision.situations:
        match term:
            case Holds(situation, value):
                spans = intervals(truth.true, situation, value)
                if not any(s - TOLERANCE_MS <= at <= u + TOLERANCE_MS for s, u in spans):
                    return False
            case Lasts(minutes, situation, value) if situation is not None:
                spans = intervals(truth.true, situation, value)
                reached = minutes * MINUTE_MS - TOLERANCE_MS
                if not any(s + reached <= at <= u + TOLERANCE_MS for s, u in spans):
                    return False
            case Ends(situation, value):
                rang = rang_for(term, at, truth)
                true_ends = ends(truth.true, situation, value, truth.unread)
                if rang is None or not any(abs(end - rang) <= TOLERANCE_MS for end in true_ends):
                    return False
    return True


def rang_for(term: Ends, at: int, truth: Truth) -> int | None:
    """The recorded end an alert that became due at `at` rang for: the last one by then."""
    recorded = ends(truth.recorded, term.situation, term.value, truth.unread)
    return max((end for end in recorded if end <= at), default=None)


def unit(revision: Revision, at: int, truth: Truth) -> int:
    """Where the unit of an alert of a reminder without a remainder began, by the stretches
    recorded (ADR-0028): the end it rang for, or the start of the stretch of its situations
    under way, the latest of its situations'; `at` when none is recorded."""
    starts = []
    for term in revision.situations:
        if isinstance(term, Ends):
            starts.append(rang_for(term, at, truth))
        elif term.situation is not None:
            spans = intervals(truth.recorded, term.situation, term.value)
            starts.append(next((s for s, u in spans if s <= at <= u), None))
    found = [start for start in starts if start is not None]
    return max(found, default=at)


def _last_end(revision: Revision, true_ends: Sequence[int], at: int, clock: Clock) -> int | None:
    written_at = revision.written_at
    found = [e for e in true_ends if e <= at and (written_at is None or e >= written_at)]
    if not found:
        return None
    end = max(found)
    if revision.perennial and jiffin_day(clock.local(end)) != jiffin_day(clock.local(at)):
        return None
    start = _window_start(revision, at, clock)
    return None if start is not None and end < start else end


def _window_start(revision: Revision, at: int, clock: Clock) -> int | None:
    """When the window of its time under way at `at` began; None without a time."""
    if revision.schedule is None or revision.written_at is None:
        return None
    times = Times(revision.schedule, revision.perennial, clock.local(revision.written_at))
    window = times.at(clock.local(at))
    return None if window is None else _instant(window.start, clock)


def _instant(at: datetime, clock: Clock) -> int:
    return clock.instant(at.date(), at.time())
