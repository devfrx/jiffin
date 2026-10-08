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
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from jiffin.core.clock import Clock
from jiffin.core.context import Context
from jiffin.core.records import (
    Alert,
    Candidate,
    ContextAnswer,
    Evaluation,
    Here,
    Left,
    Outcome,
    Reminder,
    Revision,
)
from jiffin.core.reminders import MINUTE_MS, RETURN_PAUSE_MS
from jiffin.core.situations import Ends, Holds, Lasts, SituationStretch, holds
from jiffin.core.units import instance_day
from jiffin.harness import metrics
from jiffin.harness import truth as truths
from jiffin.harness.errors import HarnessError
from jiffin.harness.truth import Truth
from jiffin.store.store import Log

# Why a relevant pair was never shown, from the candidate that came closest to an alert. Outside
# its situation, a pair relevant by the true situations was read outside them (ADR-0028).
_CLOSEST = (
    (Outcome.ALERT, "waited"),
    (Outcome.SAME_OCCASION, "same occasion"),
    (Outcome.HELD_BACK, "held back"),
    (Outcome.SNOOZED, "snoozed"),
    (Outcome.SILENCED, "silenced"),
    (Outcome.OUTSIDE_SITUATION, "outside its situation"),
    (Outcome.OUTSIDE_TIME, "out of time"),
    (Outcome.BELOW_THRESHOLD, "below threshold"),
)
# Of them, those that kept the pair quiet as already reminded: its reminder had rung in the same
# unit, or the user had answered it. Such a pair is not missed (ADR-0025).
_REMINDED = frozenset({"same occasion", "held back", "snoozed", "silenced"})
NOT_READ = "situation not read"
"""Why the unit of a true situation, which the owner added, never rang: the capture missed or
misread it (ADR-0031)."""
FOR_YES = "for Remind here"
LOWERED = "under a lowered threshold"


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
    """Those its evaluations raised, and those of reminders without a remainder made that day;
    not those asked for with Remind here."""
    revisions: Mapping[int, Revision]
    requested: tuple[Alert, ...] = ()
    """The alerts asked for with Remind here that day: never the judge's (ADR-0029)."""
    answers: tuple[ContextAnswer, ...] = ()
    """The answers per place up to the end of the day, the oldest first: what counted in each
    place at any moment (ADR-0029)."""
    situations: tuple[SituationStretch, ...] = ()
    """The stretches of the situations' values that touch the day (ADR-0028)."""
    left: tuple[Left, ...] = ()
    """When the stable contexts left the foreground, from version 0.2 on."""
    reminders: tuple[Reminder, ...] = ()
    """The reminders as at the end of the day, with when each was created and completed: when
    those that are never judged could ring."""


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
    """The (context, reminder) pairs judged."""
    labelled: int
    relevant: int
    """Pairs labelled true and judged at least once while their reminder could ring, by its time
    and its situations as they were; and the units of the situations where a reminder without a
    remainder could ring (ADR-0031)."""
    missed: dict[str, int]
    """Relevant pairs never shown nor kept quiet as already reminded, by why (ADR-0025)."""
    reminded: dict[str, int]
    """Relevant pairs never shown, kept quiet as already reminded, by why: not missed."""
    alerted: int
    """Pairs that reached the screen, each once however often it rang: (context, reminder), and
    (reminder, unit) for a reminder without a remainder on situations."""
    false_alarms: int
    """Of them, wrong: labelled not relevant, or rung on a situation read wrong (ADR-0031). A
    wrong pair counts once, as Not here silences it (ADR-0022)."""
    unlabelled: int
    """Of them, not labelled yet."""
    situated: int = 0
    """Of the alerts shown, those of reminders without a remainder on situations."""
    situated_pairs: int = 0
    """Their (reminder, unit) pairs."""
    situated_wrong: int = 0
    """Of them, rung on a situation read wrong: false alarms."""
    misread: int = 0
    """The (context, reminder) pairs shown on a situation read wrong: false alarms, whatever
    their label."""
    requested: int = 0
    """Alerts asked for with Remind here: never the judge's (ADR-0029)."""
    learned: dict[str, int] = field(default_factory=dict)
    """Alerts shown under the threshold, by why: Remind here said there, or the reminder's
    threshold lowered by Remind here near the cut (ADR-0029)."""


def key(context: Context, remainder: str) -> str:
    """Depends on the texts only: labels survive a new copy, a replay or another threshold. In
    version 0.1 the remainder is the whole condition, so its labels keep their keys."""
    text = json.dumps([context.app, context.title, context.address, remainder], ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def select(log: Log, day: date | None, clock: Clock) -> Day:
    """The evaluations made on a local day, the last one with any by default, and their alerts;
    with the alerts of reminders without a remainder made that day, which have no evaluation.
    The alerts asked for with Remind here, which have none either, are apart: they are never the
    judge's (ADR-0029)."""
    if not log.evaluations:
        raise HarnessError("the log holds no evaluation")
    if day is None:
        day = clock.local(log.evaluations[-1].at).date()
    evaluations = tuple(e for e in log.evaluations if clock.local(e.at).date() == day)
    ids = {evaluation.id for evaluation in evaluations}
    unjudged = {
        alert.id
        for alert in log.alerts
        if alert.evaluation_id is None and clock.local(alert.created_at).date() == day
    }
    alerts = tuple(
        alert
        for alert in log.alerts
        if alert.evaluation_id in ids or (alert.id in unjudged and not alert.requested)
    )
    start, end = bounds(day, clock)
    return Day(
        day,
        evaluations,
        alerts,
        log.revisions,
        requested=tuple(a for a in log.alerts if a.id in unjudged and a.requested),
        answers=tuple(answer for answer in log.answers if answer.at < end),
        situations=tuple(s for s in log.situations if s.until > start and s.since < end),
        left=log.left,
        reminders=log.reminders,
    )


def bounds(day: date, clock: Clock) -> tuple[int, int]:
    """When a local day starts and ends."""
    return clock.instant(day, time()), clock.instant(day + timedelta(days=1), time())


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


def unshown(
    day: Day, labels: Mapping[str, bool], clock: Clock, truth: Truth | None = None
) -> list[Unshown]:
    """The relevant pairs never shown: labelled true, and judged at least once while their
    reminder could ring, since a pair true only out of its time or of its situations must stay
    silent. The situations are the true ones; the day's as recorded without `truth`."""
    shown = {Pair(alert.context, alert.revision).key for alert in _judged_shown(day)}
    found: dict[str, Pair] = {}
    outcomes: dict[str, set[Outcome]] = {}
    highest: dict[str, float] = {}
    for candidate, pair in _may_ring(day, labels, clock, truth or Truth.of(day.situations, None)):
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


@dataclass(frozen=True, slots=True)
class Unit:
    """A pair of a reminder without a remainder on situations: the reminder and a unit of its
    situations (ADR-0031)."""

    revision: Revision
    at: int
    """When the unit began: the start of a stretch of its situations, an end, or a duration
    reached."""

    @property
    def key(self) -> tuple[int, int]:
        return self.revision.reminder_id, self.at


@dataclass(frozen=True, slots=True)
class Situated:
    """The pairs of the reminders without a remainder on situations, right when the situation is
    read right (ADR-0028): those shown, by the truth, and those never shown on a true situation
    the capture missed or misread."""

    right: tuple[Unit, ...]
    wrong: tuple[Unit, ...]
    """Shown on a situation the truth does not bear out: false alarms."""
    missed: tuple[Unit, ...]
    """Units of the stretches the owner added where the reminder could ring, and did not."""


def situated(day: Day, truth: Truth, clock: Clock) -> Situated:
    """A unit is wrong when any of its alerts is: each counts once."""
    rang: dict[tuple[int, int], tuple[Unit, bool]] = {}
    for alert in _situated_shown(day):
        unit = Unit(alert.revision, truths.unit(alert.revision, alert.due_at, truth))
        supported = truths.supported(alert.revision, alert.due_at, truth)
        _, before = rang.get(unit.key, (unit, True))
        rang[unit.key] = (unit, before and supported)
    return Situated(
        right=tuple(unit for unit, ok in rang.values() if ok),
        wrong=tuple(unit for unit, ok in rang.values() if not ok),
        missed=tuple(_missed_units(day, truth, clock)),
    )


def summarize(
    day: Day, labels: Mapping[str, bool], clock: Clock, truth: Truth | None = None
) -> Summary:
    """The day's numbers. The situations are the true ones; the day's as recorded without
    `truth`."""
    truth = truth or Truth.of(day.situations, None)
    shown = [alert for alert in day.alerts if alert.shown_at is not None]
    delays = tuple(
        (alert.shown_at - alert.due_at) / 1000 for alert in shown if alert.shown_at is not None
    )
    found = pairs(day)
    units = situated(day, truth, clock)
    missed: dict[str, int] = {NOT_READ: len(units.missed)} if units.missed else {}
    reminded: dict[str, int] = {}
    for pair in unshown(day, labels, clock, truth):
        reasons = missed if pair.missed else reminded
        reasons[pair.why] = reasons.get(pair.why, 0) + 1
    alerted = {Pair(alert.context, alert.revision).key for alert in _judged_shown(day)}
    misread = {
        Pair(alert.context, alert.revision).key
        for alert in _judged_shown(day)
        if not truths.supported(alert.revision, alert.due_at, truth)
    }
    may_ring = {pair.key for _, pair in _may_ring(day, labels, clock, truth)}
    first, last = span(day)
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
        time_only=sum(a.evaluation_id is None and not a.revision.situations for a in shown),
        delays=delays,
        pairs=len(found),
        labelled=sum(pair_key in labels for pair_key in found),
        relevant=sum(labels.get(pair_key) is True for pair_key in may_ring)
        + len(units.right)
        + len(units.missed),
        missed=missed,
        reminded=reminded,
        alerted=len(alerted) + len(units.right) + len(units.wrong),
        false_alarms=sum(labels.get(k) is False or k in misread for k in alerted)
        + len(units.wrong),
        unlabelled=sum(k not in labels and k not in misread for k in alerted),
        situated=len(_situated_shown(day)),
        situated_pairs=len(units.right) + len(units.wrong),
        situated_wrong=len(units.wrong),
        misread=len(misread),
        requested=len(day.requested),
        learned=_learned(day),
    )


def delay(summary: Summary, p: float) -> float | None:
    return metrics.percentile(summary.delays, p) if summary.delays else None


def span(day: Day) -> tuple[int, int]:
    """The day's active time: from the first context evaluated to the last evaluation."""
    if not day.evaluations:
        return 0, 0
    return day.evaluations[0].context_since, day.evaluations[-1].at


def stable(day: Day) -> list[tuple[Context, int, int, int]]:
    """The stretches of the contexts judged that day, as (context, since, stable, until): when
    each came to the foreground, when it was first judged, and when it left, where the log says
    (from version 0.2 on), else when the next one came; the last one, until the day's last
    evaluation or alert."""
    first: dict[tuple[int, Context], int] = {}
    for evaluation in day.evaluations:  # the oldest first
        first.setdefault((evaluation.context_since, evaluation.context), evaluation.at)
    left = {(stretch.since, stretch.context): stretch.until for stretch in day.left}
    marks = sorted(first, key=lambda mark: (mark[0], first[mark]))
    last = max(
        [evaluation.at for evaluation in day.evaluations]
        + [alert.created_at for alert in day.alerts]
    )
    found = []
    for index, mark in enumerate(marks):
        until = left.get(mark)
        if until is None:
            until = marks[index + 1][0] if index + 1 < len(marks) else last
        found.append((mark[1], mark[0], first[mark], until))
    return found


def _judged_shown(day: Day) -> list[Alert]:
    """The alerts shown of reminders the engine judged: those without a remainder are apart."""
    return [a for a in day.alerts if a.shown_at is not None and a.evaluation_id is not None]


def _situated_shown(day: Day) -> list[Alert]:
    """The alerts shown of reminders without a remainder on situations."""
    return [
        a
        for a in day.alerts
        if a.shown_at is not None and a.evaluation_id is None and a.revision.situations
    ]


def _may_ring(
    day: Day, labels: Mapping[str, bool], clock: Clock, truth: Truth
) -> Iterator[tuple[Candidate, Pair]]:
    """Every candidate judged while its reminder could ring, with its pair: within its time, as
    `core` reads it; within its situations, as they were; and where its thing had lasted as long
    as the condition wants, by the labels, before its context left: a judge that missed it there
    left no evaluation at that moment. The label is on the remainder, and the code checks the
    rest (ADR-0021, ADR-0028)."""
    reached: dict[int, list[tuple[int, int]]] = {}
    left = {(context, since): until for context, since, _, until in stable(day)}
    for evaluation in day.evaluations:
        for candidate in evaluation.candidates:
            revision = day.revisions[candidate.revision_id]
            at = evaluation.at
            timed = revision.schedule is not None and revision.written_at is not None
            if timed and instance_day(revision, clock, at) is None:
                continue
            if not truths.holds_at(revision, at, truth, clock):
                continue
            if _thing_minutes(revision) is not None:
                if revision.id not in reached:
                    reached[revision.id] = _thing_reached(day, labels, revision)
                until = left[(evaluation.context, evaluation.context_since)]
                if not any(start < until and at < end for start, end in reached[revision.id]):
                    continue
            yield candidate, Pair(evaluation.context, revision)


def _thing_minutes(revision: Revision) -> int | None:
    return next(
        (t.minutes for t in revision.situations if isinstance(t, Lasts) and t.situation is None),
        None,
    )


def _thing_reached(
    day: Day, labels: Mapping[str, bool], revision: Revision
) -> list[tuple[int, int]]:
    """When the thing the judge checks had lasted as long as the condition wants, by the labels:
    from the start of each occasion of contexts where the remainder is true, which a stretch
    away for less than the return pause does not break (ADR-0021, ADR-0028)."""
    minutes = _thing_minutes(revision) or 0
    occasions: list[tuple[int, int]] = []
    pause = RETURN_PAUSE_MS
    for context, since, _, until in stable(day):
        if labels.get(key(context, revision.remainder)) is not True:
            continue
        if occasions and since - occasions[-1][1] < pause:
            occasions[-1] = (occasions[-1][0], max(occasions[-1][1], until))
        else:
            occasions.append((since, until))
        pause = next(
            (
                e.return_pause
                for e in day.evaluations
                if e.context_since == since and e.return_pause
            ),
            RETURN_PAUSE_MS,
        )
    return [(start + minutes * MINUTE_MS, end) for start, end in occasions]


def _missed_units(day: Day, truth: Truth, clock: Clock) -> Iterator[Unit]:
    """The units of the stretches the owner added where a reminder without a remainder could
    ring and no right alert came: a call or an absence the capture missed or misread. It could
    ring where a stable context was in front, within its time, while it was active."""
    rang = [a for a in _situated_shown(day) if truths.supported(a.revision, a.due_at, truth)]
    unjudged = [r for r in day.revisions.values() if not r.remainder and r.situations]
    found: set[tuple[int, int]] = set()
    for added in truth.added:
        for revision in unjudged:
            for start, until in _units(revision, added, truth, day, clock):
                unit = Unit(revision, start)
                if unit.key in found or not _could_ring(day, revision, start, until, truth, clock):
                    continue
                low, high = start - truths.TOLERANCE_MS, until + truths.TOLERANCE_MS
                if not any(
                    a.reminder_id == revision.reminder_id and low <= a.due_at <= high for a in rang
                ):
                    found.add(unit.key)
                    yield unit


def _units(
    revision: Revision, added: SituationStretch, truth: Truth, day: Day, clock: Clock
) -> Iterator[tuple[int, int]]:
    """Where the stretch the owner added makes a unit of the revision begin, and until when it
    may ring, by its terms on that situation."""
    for term in revision.situations:
        if term.situation is not added.situation or not holds(
            term.situation, term.value, frozenset({added.value})
        ):
            continue
        spans = truths.intervals(truth.true, term.situation, term.value)
        since, until = next((s, u) for s, u in spans if s <= added.since < u)
        match term:
            case Holds():
                yield since, until
            case Lasts(minutes) if since + minutes * MINUTE_MS < until:
                yield since + minutes * MINUTE_MS, until
            case Ends() if until not in truth.unread:
                later = [s for s, _ in spans if s > until]
                yield until, min(later, default=bounds(day.day, clock)[1])


def _could_ring(
    day: Day, revision: Revision, start: int, until: int, truth: Truth, clock: Clock
) -> bool:
    """Whether a stable context was in front between `start` and `until` at a moment the
    revision was in force and its time and situations held."""
    for _, _, stable_at, left_at in stable(day):
        at = max(stable_at, start)
        if at >= min(left_at, until):
            continue
        timed = revision.schedule is not None and revision.written_at is not None
        if timed and instance_day(revision, clock, at) is None:
            continue
        if _in_force(day, revision, at) and truths.holds_at(revision, at, truth, clock):
            return True
    return False


def _in_force(day: Day, revision: Revision, at: int) -> bool:
    """Whether the revision was its reminder's at `at`, the reminder created and not completed."""
    reminder = next((r for r in day.reminders if r.id == revision.reminder_id), None)
    if reminder is None or at < reminder.created_at:
        return False
    if reminder.completed_at is not None and at >= reminder.completed_at:
        return False
    made = [
        r
        for r in day.revisions.values()
        if r.reminder_id == revision.reminder_id and (r.created_at or reminder.created_at) <= at
    ]
    return max(made, key=lambda r: r.number, default=None) == revision


def under(day: Day, alert: Alert) -> str | None:
    """Why an alert of the judge rang under the threshold: Remind here said in its place, or its
    reminder's threshold lowered by Remind here near the cut (ADR-0029); None over it."""
    evaluation = next((e for e in day.evaluations if e.id == alert.evaluation_id), None)
    if evaluation is None or alert.d is None or alert.d >= evaluation.threshold:
        return None
    said = [
        answer.here
        for answer in day.answers
        if answer.reminder_id == alert.reminder_id
        and answer.context == alert.context
        and answer.at <= alert.created_at
    ]
    return FOR_YES if said and said[-1] is Here.YES else LOWERED


def _learned(day: Day) -> dict[str, int]:
    found: dict[str, int] = {}
    for alert in _judged_shown(day):
        why = under(day, alert)
        if why is not None:
            found[why] = found.get(why, 0) + 1
    return found


def _reminders(evaluations: Iterable[Evaluation], revisions: Mapping[int, Revision]) -> int:
    return len({revisions[c.revision_id].reminder_id for e in evaluations for c in e.candidates})
