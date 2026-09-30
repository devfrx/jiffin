"""The measures, in pure Python (ADR-0017): the data are hundreds of pairs, not millions.

A day or a sample is a table: one row per evaluated context, one column per reminder, and in
each cell the model's d and whether the reminder is relevant there. The pipeline has one stage
(ADR-0007): a reminder alerts wherever d reaches the threshold, so recall and false alarms are
read off one threshold on all the cells.
"""

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

type Table[T] = Sequence[Sequence[T]]
"""Rows are evaluated contexts, columns are reminders."""


@dataclass(frozen=True, slots=True)
class Operating:
    """What one threshold on d gives."""

    threshold: float
    """Infinite when nothing alerts."""
    recall: float
    """The share of relevant cells that alert."""
    false_alarms: float
    """Alerts on cells that are not relevant, per evaluated context."""


def auroc(scores: Sequence[float], relevant: Sequence[bool]) -> float:
    """How often a relevant cell scores above one that is not: ties count one half.

    The same number as scikit-learn's `roc_auc_score`; NaN when either kind is missing.
    """
    positives = sum(relevant)
    negatives = len(relevant) - positives
    if positives == 0 or negatives == 0:
        return math.nan
    ranks = _ranks(scores)
    rank_sum = sum(rank for rank, is_relevant in zip(ranks, relevant, strict=True) if is_relevant)
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def percentile(values: Sequence[float], p: float) -> float:
    """The p-th percentile, from 0 to 100, linear between the closest ranks, as numpy's default."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * p / 100
    below = math.floor(position)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (ordered[above] - ordered[below]) * (position - below)


def at_threshold(d: Table[float], relevant: Table[bool], threshold: float) -> Operating:
    alerts = hits = 0
    for d_row, relevant_row in zip(d, relevant, strict=True):
        for score, is_relevant in zip(d_row, relevant_row, strict=True):
            if score >= threshold:
                alerts += 1
                hits += is_relevant
    return Operating(threshold, _share(hits, _count(relevant)), (alerts - hits) / len(d))


def best_within(d: Table[float], relevant: Table[bool], budget: float) -> Operating:
    """The highest recall with at most `budget` false alarms per evaluated context.

    Of the thresholds that give it, the lowest, as the prototype chose them (devfrx/sibyl#20).
    """
    cells = sorted(
        (
            (score, is_relevant)
            for d_row, relevant_row in zip(d, relevant, strict=True)
            for score, is_relevant in zip(d_row, relevant_row, strict=True)
        ),
        reverse=True,
    )
    total = sum(is_relevant for _, is_relevant in cells)
    best = Operating(math.inf, 0.0, 0.0)
    hits = alerts = 0
    index = 0
    # Lowering the threshold only adds alerts: the last one within the budget is the best.
    while index < len(cells):
        threshold = cells[index][0]
        while index < len(cells) and cells[index][0] == threshold:
            alerts += 1
            hits += cells[index][1]
            index += 1
        false_alarms = (alerts - hits) / len(d)
        if false_alarms > budget:
            break
        best = Operating(threshold, _share(hits, total), false_alarms)
    return best


def bootstrap(
    rows: int, statistic: Callable[[Sequence[int]], float], rounds: int = 1000, seed: int = 0
) -> tuple[float, float]:
    """The 95% interval of a statistic of the rows, drawn again with replacement.

    `statistic` gets the indices of the drawn rows. Resampling whole rows keeps the cells of a
    context together, and passing the same draws to two statistics pairs them.
    """
    generator = random.Random(seed)
    values = []
    for _ in range(rounds):
        value = statistic([generator.randrange(rows) for _ in range(rows)])
        if not math.isnan(value):
            values.append(value)
    return percentile(values, 2.5), percentile(values, 97.5)


def pick[T](table: Table[T], rows: Sequence[int]) -> list[Sequence[T]]:
    return [table[row] for row in rows]


def column[T](table: Table[T], columns: Sequence[int]) -> list[list[T]]:
    """The cells of some columns, row by row."""
    return [[row[index] for index in columns] for row in table]


def flat[T](table: Table[T]) -> list[T]:
    return [cell for row in table for cell in row]


def _count(relevant: Table[bool]) -> int:
    return sum(sum(row) for row in relevant)


def _share(part: int, whole: int) -> float:
    return part / whole if whole else math.nan


def _ranks(values: Sequence[float]) -> list[float]:
    """Ranks from 1, ties sharing the mean of theirs."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            ranks[order[position]] = (start + end) / 2 + 1
        start = end + 1
    return ranks
