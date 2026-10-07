"""A day of the app's log, and its numbers against the thresholds of ADR-0022.

The numbers come from the records `core` writes: evaluations with their candidates, and
alerts. The same records come from a copy of the database (`report`) or from `core` itself
(`replay`), so both are measured by the same code.

A label says whether a reminder's remainder, its condition without the time, is true in a
context; the code checks the time (ADR-0021). The alerts of reminders with only a time are
never judged, and are counted apart: they are right when the time is read right (ADR-0022).
"""

import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date

from jiffin.core.clock import Clock
from jiffin.core.context import Context
from jiffin.core.records import Alert, Candidate, Evaluation, Outcome, Revision
from jiffin.core.units import instance_day
from jiffin.harness import metrics
from jiffin.harness.errors import HarnessError
from jiffin.store.store import Log

# Why a relevant pair was never shown, from the candidate that came closest to an alert.
_CLOSEST = (
    (Outcome.ALERT, "waited"),
    (Outcome.SAME_OCCASION, "same occasion"),
    (Outcome.HELD_BACK, "held back"),
    (Outcome.SNOOZED, "snoozed"),
    (Outcome.SILENCED, "silenced"),
    (Outcome.OUTSIDE_TIME, "out of time"),
    (Outcome.BELOW_THRESHOLD, "below threshold"),
)
# Of them, those that kept the pair quiet as already reminded: its reminder had rung in the same
# unit, or the user had answered it. Such a pair is not missed (ADR-0025).
_REMINDED = frozenset({"same occasion", "held back", "snoozed", "silenced"})


@dataclass(frozen=True, slots=True)
class Pair:
    """An evaluated context and a reminder: a label says whether the remainder is true there."""

    context: Context
    revision: Revision

    @property
    def key(self) -> str:
        return key(self.context, self.revision.remainder)


@dataclass(frozen=True, slots=True)
class Day:
    day: date
    evaluations: tuple[Evaluation, ...]
    """The oldest first."""
    alerts: tuple[Alert, ...]
    """Those its evaluations raised, and those of reminders with only a time made that day."""
    revisions: Mapping[int, Revision]


@dataclass(frozen=True, slots=True)
class Summary:
    day: date
    evaluations: int
    judged: int
    """Evaluations that asked the engine something: the rest came from the cache."""
    failed: int
    """Evaluations the engine could not answer."""
    hours: float
    """From the first context evaluated to the last evaluation."""
    reminders: int
    """Reminders judged at least once."""
    pauses: tuple[int, ...]
    """The return pauses the evaluations were judged with, in milliseconds, in order; none in
    version 0.1. The acceptance day keeps the default (ADR-0022)."""
    shown: int
    """Alerts that reached the screen."""
    time_only: int
    """Of them, alerts of reminders with only a time: right when the time is read right."""
    delays: tuple[float, ...]
    """Seconds from when each alert became due to when it reached the screen (ADR-0022)."""
    pairs: int
    labelled: int
    relevant: int
    """Pairs labelled true and judged at least once while their reminder's time held."""
    missed: dict[str, int]
    """Relevant pairs never shown nor kept quiet as already reminded, by why (ADR-0025)."""
    reminded: dict[str, int]
    """Relevant pairs never shown, kept quiet as already reminded, by why: not missed."""
    alerted: int
    """Pairs that reached the screen, each once however often it rang."""
    false_alarms: int
    """Of them, labelled not relevant: a wrong pair counts once, as Not here silences it
    (ADR-0022)."""
    unlabelled: int
    """Of them, not labelled yet."""


def key(context: Context, remainder: str) -> str:
    """Depends on the texts only: labels survive a new copy, a replay or another threshold. In
    version 0.1 the remainder is the whole condition, so its labels keep their keys."""
    text = json.dumps([context.app, context.title, context.address, remainder], ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def select(log: Log, day: date | None, clock: Clock) -> Day:
    """The evaluations made on a local day, the last one with any by default, and their alerts;
    with the alerts of reminders with only a time made that day, which have no evaluation."""
    if not log.evaluations:
        raise HarnessError("the log holds no evaluation")
    if day is None:
        day = clock.local(log.evaluations[-1].at).date()
    evaluations = tuple(e for e in log.evaluations if clock.local(e.at).date() == day)
    ids = {evaluation.id for evaluation in evaluations}
    alerts = tuple(
        alert
        for alert in log.alerts
        if alert.evaluation_id in ids
        or (alert.evaluation_id is None and clock.local(alert.created_at).date() == day)
    )
    return Day(day, evaluations, alerts, log.revisions)


def pairs(day: Day) -> dict[str, Pair]:
    """Every (evaluated context, reminder) the engine judged, by key, in order of appearance."""
    found: dict[str, Pair] = {}
    for evaluation in day.evaluations:
        for candidate in evaluation.candidates:
            pair = Pair(evaluation.context, day.revisions[candidate.revision_id])
            found.setdefault(pair.key, pair)
    return found


@dataclass(frozen=True, slots=True)
class Unshown:
    """A relevant pair never shown."""

    pair: Pair
    why: str
    """From the candidate that came closest to an alert: see `_CLOSEST`."""
    d: float
    """The highest d the pair got in the day."""

    @property
    def missed(self) -> bool:
        """A missed reminder, unless kept quiet as already reminded (ADR-0025)."""
        return self.why not in _REMINDED


def unshown(day: Day, labels: Mapping[str, bool], clock: Clock) -> list[Unshown]:
    """The relevant pairs never shown: labelled true, and judged at least once while their
    reminder's time held, since a pair true only out of its time must stay silent."""
    shown = {Pair(alert.context, alert.revision).key for alert in _judged_shown(day)}
    found: dict[str, Pair] = {}
    outcomes: dict[str, set[Outcome]] = {}
    highest: dict[str, float] = {}
    for candidate, pair in _in_time(day, clock):
        found.setdefault(pair.key, pair)
        outcomes.setdefault(pair.key, set()).add(candidate.outcome)
        highest[pair.key] = max(highest.get(pair.key, candidate.d), candidate.d)
    return [
        Unshown(
            pair,
            next(why for outcome, why in _CLOSEST if outcome in outcomes[pair_key]),
            highest[pair_key],
        )
        for pair_key, pair in found.items()
        if labels.get(pair_key) is True and pair_key not in shown
    ]


def summarize(day: Day, labels: Mapping[str, bool], clock: Clock) -> Summary:
    shown = [alert for alert in day.alerts if alert.shown_at is not None]
    delays = tuple(
        (alert.shown_at - alert.due_at) / 1000 for alert in shown if alert.shown_at is not None
    )
    found = pairs(day)
    missed: dict[str, int] = {}
    reminded: dict[str, int] = {}
    for pair in unshown(day, labels, clock):
        reasons = missed if pair.missed else reminded
        reasons[pair.why] = reasons.get(pair.why, 0) + 1
    alerted = {Pair(alert.context, alert.revision).key for alert in _judged_shown(day)}
    in_time = {pair.key for _, pair in _in_time(day, clock)}
    first = day.evaluations[0].context_since if day.evaluations else 0
    last = day.evaluations[-1].at if day.evaluations else 0
    pauses = (e.return_pause for e in day.evaluations if e.return_pause is not None)
    return Summary(
        day=day.day,
        evaluations=len(day.evaluations),
        judged=sum(any(not c.from_cache for c in e.candidates) for e in day.evaluations),
        failed=sum(evaluation.failed for evaluation in day.evaluations),
        hours=(last - first) / 3_600_000,
        reminders=_reminders(day.evaluations, day.revisions),
        pauses=tuple(dict.fromkeys(pauses)),
        shown=len(shown),
        time_only=sum(alert.evaluation_id is None for alert in shown),
        delays=delays,
        pairs=len(found),
        labelled=sum(pair_key in labels for pair_key in found),
        relevant=sum(labels.get(pair_key) is True for pair_key in in_time),
        missed=missed,
        reminded=reminded,
        alerted=len(alerted),
        false_alarms=sum(labels.get(pair_key) is False for pair_key in alerted),
        unlabelled=sum(pair_key not in labels for pair_key in alerted),
    )


def delay(summary: Summary, p: float) -> float | None:
    return metrics.percentile(summary.delays, p) if summary.delays else None


def _judged_shown(day: Day) -> list[Alert]:
    """The alerts shown of reminders the engine judged: those with only a time are apart."""
    return [a for a in day.alerts if a.shown_at is not None and a.evaluation_id is not None]


def _in_time(day: Day, clock: Clock) -> Iterator[tuple[Candidate, Pair]]:
    """Every candidate judged while its reminder's time held, as `core` reads the time, with its
    pair: the label is on the remainder, and the code checks the time (ADR-0021)."""
    for evaluation in day.evaluations:
        for candidate in evaluation.candidates:
            revision = day.revisions[candidate.revision_id]
            timed = revision.schedule is not None and revision.written_at is not None
            if not timed or instance_day(revision, clock, evaluation.at) is not None:
                yield candidate, Pair(evaluation.context, revision)


def _reminders(evaluations: Iterable[Evaluation], revisions: Mapping[int, Revision]) -> int:
    return len({revisions[c.revision_id].reminder_id for e in evaluations for c in e.candidates})
