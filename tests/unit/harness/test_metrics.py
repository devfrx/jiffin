import math
from collections.abc import Sequence

import pytest

from jiffin.harness.metrics import (
    Operating,
    at_threshold,
    auroc,
    best_within,
    bootstrap,
    column,
    flat,
    percentile,
    pick,
)

# Two contexts, two reminders: sorted by d, the cells are 0.9 relevant, 0.8 not, 0.7 relevant,
# 0.5 not.
D = [[0.9, 0.5], [0.8, 0.7]]
RELEVANT = [[True, False], [False, True]]


def test_auroc_is_scikit_learns() -> None:
    # The example of roc_auc_score's documentation.
    assert auroc([0.1, 0.4, 0.35, 0.8], [False, False, True, True]) == 0.75


def test_auroc_counts_a_tie_one_half() -> None:
    assert auroc([0.5, 0.5, 0.2], [True, False, False]) == 0.75


def test_auroc_needs_both_kinds_of_cells() -> None:
    assert math.isnan(auroc([0.1, 0.9], [True, True]))


def test_percentile_interpolates_as_numpy() -> None:
    assert percentile([4, 1, 3, 2], 50) == 2.5
    assert percentile([1, 2, 3, 4], 95) == pytest.approx(3.85)
    assert percentile([1, 2, 3, 4], 0) == 1
    assert percentile([1, 2, 3, 4], 100) == 4
    assert percentile([7], 95) == 7


def test_a_percentile_of_nothing_is_an_error() -> None:
    with pytest.raises(ValueError):
        percentile([], 50)


def test_at_a_threshold_recall_is_over_relevant_cells_and_false_alarms_over_contexts() -> None:
    assert at_threshold(D, RELEVANT, 0.75) == Operating(0.75, 0.5, 0.5)
    assert at_threshold(D, RELEVANT, 0.95) == Operating(0.95, 0.0, 0.0)


def test_best_within_a_budget_takes_the_lowest_threshold_of_the_highest_recall() -> None:
    assert best_within(D, RELEVANT, 0.0) == Operating(0.9, 0.5, 0.0)
    assert best_within(D, RELEVANT, 0.5) == Operating(0.7, 1.0, 0.5)
    assert best_within(D, RELEVANT, 1.0) == Operating(0.5, 1.0, 1.0)


def test_best_within_a_budget_may_be_to_alert_on_nothing() -> None:
    assert best_within([[0.9, 0.5]], [[False, True]], 0.5) == Operating(math.inf, 0.0, 0.0)


def test_best_within_a_budget_takes_ties_together() -> None:
    # At 0.8 both cells alert: one hit and one false alarm, never only the hit.
    assert best_within([[0.8, 0.8]], [[True, False]], 0.5) == Operating(math.inf, 0.0, 0.0)
    assert best_within([[0.8, 0.8]], [[True, False]], 1.0) == Operating(0.8, 1.0, 1.0)


def test_bootstrap_draws_rows_with_replacement_and_is_repeatable() -> None:
    values = [1.0, 2.0, 3.0, 4.0]

    def mean(rows: Sequence[int]) -> float:
        return sum(values[row] for row in rows) / len(rows)

    low, high = bootstrap(len(values), mean, rounds=500)
    assert 1.0 <= low < 2.5 < high <= 4.0
    assert bootstrap(len(values), mean, rounds=500) == (low, high)


def test_bootstrap_leaves_out_draws_where_the_statistic_is_undefined() -> None:
    assert bootstrap(3, lambda rows: math.nan if rows[0] == 0 else 1.0, rounds=50) == (1.0, 1.0)


def test_tables_are_cut_by_rows_and_by_columns() -> None:
    assert pick(D, [1, 1]) == [[0.8, 0.7], [0.8, 0.7]]
    assert column(D, [1]) == [[0.5], [0.7]]
    assert flat(D) == [0.9, 0.5, 0.8, 0.7]
