"""A day of the app's log, and its numbers against the thresholds of ADR-0003.

The numbers come from the records `core` writes: evaluations with their candidates, and
alerts. The same records come from a copy of the database (`report`) or from `core` itself
(`replay`), so both are measured by the same code.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from jiffin.core.clock import Clock
from jiffin.core.context import Context
from jiffin.core.records import Alert, Evaluation, Outcome, Revision
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


@dataclass(frozen=True, slots=True)
class Pair:
    """An evaluated context and a reminder: a label says whether the condition is true there."""

    context: Context
    revision: Revision

    @property
    def key(self) -> str:
        return key(self.context, self.revision.condition)


@dataclass(frozen=True, slots=True)
class Day:
    day: date
    evaluations: tuple[Evaluation, ...]
    """The oldest first."""
    alerts: tuple[Alert, ...]
    """Those its evaluations raised."""
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
    shown: int
    """Alerts that reached the screen."""
    delays: tuple[float, ...]
    """Seconds from when each alert became due to when it reached the screen (ADR-0022)."""
    pairs: int
    labelled: int
    relevant: int
    missed: dict[str, int]
    """Relevant pairs never shown, by why: see `_CLOSEST`."""
    false_alarms: int
    """Alerts shown on pairs labelled not relevant."""
    unlabelled_alerts: int


def key(context: Context, condition: str) -> str:
    """Depends on the texts only: labels survive a new copy, a replay or another threshold."""
    text = json.dumps([context.app, context.title, context.address, condition], ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def select(log: Log, day: date | None, clock: Clock) -> Day:
    """The evaluations made on a local day, the last one with any by default."""
    if not log.evaluations:
        raise HarnessError("the log holds no evaluation")
    if day is None:
        day = clock.local(log.evaluations[-1].at).date()
    evaluations = tuple(e for e in log.evaluations if clock.local(e.at).date() == day)
    ids = {evaluation.id for evaluation in evaluations}
    alerts = tuple(alert for alert in log.alerts if alert.evaluation_id in ids)
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
class Missed:
    """A relevant pair never shown."""

    pair: Pair
    why: str
    d: float
    """The highest d the pair got in the day."""


def missed(day: Day, labels: Mapping[str, bool]) -> list[Missed]:
    shown = {key(a.context, a.revision.condition) for a in day.alerts if a.shown_at is not None}
    outcomes: dict[str, set[Outcome]] = {}
    highest: dict[str, float] = {}
    for evaluation in day.evaluations:
        for candidate in evaluation.candidates:
            pair_key = key(evaluation.context, day.revisions[candidate.revision_id].condition)
            outcomes.setdefault(pair_key, set()).add(candidate.outcome)
            highest[pair_key] = max(highest.get(pair_key, candidate.d), candidate.d)
    return [
        Missed(
            pair,
            next(why for outcome, why in _CLOSEST if outcome in outcomes[pair_key]),
            highest[pair_key],
        )
        for pair_key, pair in pairs(day).items()
        if labels.get(pair_key) is True and pair_key not in shown
    ]


def summarize(day: Day, labels: Mapping[str, bool]) -> Summary:
    shown = [alert for alert in day.alerts if alert.shown_at is not None]
    delays = tuple(
        (alert.shown_at - alert.due_at) / 1000 for alert in shown if alert.shown_at is not None
    )
    found = pairs(day)
    reasons: dict[str, int] = {}
    for pair in missed(day, labels):
        reasons[pair.why] = reasons.get(pair.why, 0) + 1
    alert_labels = [labels.get(key(alert.context, alert.revision.condition)) for alert in shown]
    first = day.evaluations[0].context_since if day.evaluations else 0
    last = day.evaluations[-1].at if day.evaluations else 0
    return Summary(
        day=day.day,
        evaluations=len(day.evaluations),
        judged=sum(any(not c.from_cache for c in e.candidates) for e in day.evaluations),
        failed=sum(evaluation.failed for evaluation in day.evaluations),
        hours=(last - first) / 3_600_000,
        reminders=_reminders(day.evaluations, day.revisions),
        shown=len(shown),
        delays=delays,
        pairs=len(found),
        labelled=sum(pair_key in labels for pair_key in found),
        relevant=sum(labels.get(pair_key) is True for pair_key in found),
        missed=reasons,
        false_alarms=alert_labels.count(False),
        unlabelled_alerts=alert_labels.count(None),
    )


def delay(summary: Summary, p: float) -> float | None:
    return metrics.percentile(summary.delays, p) if summary.delays else None


def _reminders(evaluations: Iterable[Evaluation], revisions: Mapping[int, Revision]) -> int:
    return len({revisions[c.revision_id].reminder_id for e in evaluations for c in e.candidates})
