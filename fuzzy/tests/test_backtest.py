"""Tests for crosscut_fuzzy.backtest.

The module under test turns a raw price series and a fuzzy advice series into a small quality
report: it finds the operator moves in the price, looks at the advice just before each move and
scores how well that advice agrees with the direction of the move.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_fuzzy.backtest import (
    BacktestSettings,
    advice_before,
    backtest,
    find_operator_moves,
    score_moves,
    split_halves,
)


def _constant_series(value: float, length: int) -> np.ndarray:
    """Return an array of `length` samples all equal to `value`."""
    return np.full(length, value, dtype=float)


def _price_with_steps(base: float, steps: dict[int, float], length: int) -> np.ndarray:
    """Build a price series of `length` samples that jumps by `steps[index]` at each given index."""
    prices = np.empty(length, dtype=float)
    level = base
    for i in range(length):
        if i in steps:
            level += steps[i]
        prices[i] = level
    return prices


def test_a_step_up_is_found_at_the_index_after_the_jump() -> None:
    """A +5 jump between samples 3 and 4 is reported at index 4 with delta 5."""
    prices = np.array([0.0, 0.0, 0.0, 0.0, 5.0, 5.0])

    indices, deltas = find_operator_moves(prices, dead_band=2.0)

    assert indices.tolist() == [4]
    assert deltas.tolist() == pytest.approx([5.0])


def test_a_jump_smaller_than_the_dead_band_is_ignored() -> None:
    """A 1.5 change with dead_band 2.0 does not count as an operator move."""
    prices = np.array([0.0, 0.0, 1.5, 1.5])

    indices, deltas = find_operator_moves(prices, dead_band=2.0)

    assert indices.size == 0
    assert deltas.size == 0


def test_two_adjacent_jumps_form_one_single_move() -> None:
    """Consecutive +3 and +3 jumps are one run, reported once with the summed delta 6."""
    prices = np.array([0.0, 0.0, 3.0, 6.0])

    indices, deltas = find_operator_moves(prices, dead_band=2.0)

    assert indices.tolist() == [2]
    assert deltas.tolist() == pytest.approx([6.0])


def test_adjacent_jumps_of_opposite_sign_are_two_moves() -> None:
    """A +5 jump directly followed by a -5 jump is two moves, not one move of delta 0."""
    prices = np.array([0.0, 0.0, 5.0, 0.0, 0.0])

    indices, deltas = find_operator_moves(prices, dead_band=2.0)

    assert indices.tolist() == [2, 3]
    assert deltas.tolist() == pytest.approx([5.0, -5.0])

def test_a_downward_move_is_found_with_a_negative_delta() -> None:
    """A -4 drop is reported with a negative delta."""
    prices = np.array([0.0, 0.0, 0.0, -4.0])

    indices, deltas = find_operator_moves(prices, dead_band=2.0)

    assert indices.tolist() == [3]
    assert deltas.tolist() == pytest.approx([-4.0])


def test_advice_before_averages_the_window_and_excludes_the_move_sample() -> None:
    """The mean is taken over the samples strictly before the move sample."""
    fuzzy = np.array([2.0, 4.0, 100.0, 100.0])

    advice = advice_before(fuzzy, indices=np.array([2]), lookback_samples=2)

    assert advice.tolist() == pytest.approx([3.0])


def test_advice_before_a_move_at_the_first_sample_is_nan() -> None:
    """A move at index 0 has an empty window, so the advice is undefined."""
    fuzzy = np.array([1.0, 2.0, 3.0])

    advice = advice_before(fuzzy, indices=np.array([0]), lookback_samples=3)

    assert np.isnan(advice[0])


def test_perfect_agreement_gives_full_sign_agreement_and_high_correlation() -> None:
    """Advice with the same sign as the delta scores 1.0 agreement and near-1 correlation."""
    advice = np.array([1.0, 2.0, 3.0, 4.0])
    deltas = np.array([5.0, 10.0, 15.0, 20.0])

    metrics = score_moves(advice, deltas, silent_band=0.1)

    assert metrics.sign_agreement == pytest.approx(1.0)
    assert metrics.correlation == pytest.approx(1.0)


def test_opposite_advice_gives_zero_sign_agreement() -> None:
    """Advice whose sign is always opposite to the delta scores 0.0 agreement."""
    advice = np.array([-1.0, -2.0, -3.0, -4.0])
    deltas = np.array([5.0, 10.0, 15.0, 20.0])

    metrics = score_moves(advice, deltas, silent_band=0.1)

    assert metrics.sign_agreement == pytest.approx(0.0)


def test_silent_advice_is_ignored_for_agreement_but_counted_as_silent() -> None:
    """Advice inside the silent band does not vote but appears in silent_share."""
    advice = np.array([0.05, 2.0, 3.0, 4.0])
    deltas = np.array([5.0, 10.0, 15.0, 20.0])

    metrics = score_moves(advice, deltas, silent_band=0.5)

    assert metrics.sign_agreement == pytest.approx(1.0)
    assert metrics.silent_share == pytest.approx(0.25)


def test_nan_advice_is_dropped_from_the_move_count() -> None:
    """Moves with NaN advice are removed before anything is counted."""
    advice = np.array([np.nan, 2.0, 3.0])
    deltas = np.array([5.0, 10.0, 15.0])

    metrics = score_moves(advice, deltas, silent_band=0.5)

    assert metrics.n_moves == 2


def test_majority_share_reports_the_winning_delta_side() -> None:
    """With deltas +5, +5, -5 the majority side holds two of three moves."""
    advice = np.array([1.0, 1.0, -1.0])
    deltas = np.array([5.0, 5.0, -5.0])

    metrics = score_moves(advice, deltas, silent_band=0.1)

    assert metrics.majority_share == pytest.approx(2.0 / 3.0)


def test_split_halves_splits_even_length_in_two() -> None:
    """Ten samples are cut into 0:5 and 5:10."""
    first_half, second_half = split_halves(10)

    assert first_half == slice(0, 5)
    assert second_half == slice(5, 10)


def test_backtest_end_to_end_scores_the_advice_on_both_moves() -> None:
    """Steps of +5 at sample 100 and -5 at sample 300 match advice that flips in the middle."""
    prices = _price_with_steps(base=0.0, steps={100: 5.0, 300: -5.0}, length=400)
    fuzzy = np.concatenate([_constant_series(5.0, 200), _constant_series(-5.0, 200)])

    metrics = backtest(fuzzy, prices, dt_s=1.0, settings=BacktestSettings(lookback_s=50.0))

    assert metrics.n_moves == 2
    assert metrics.sign_agreement == pytest.approx(1.0)


def test_backtest_with_a_part_only_counts_moves_inside_it() -> None:
    """Restricting the run to samples 200:400 keeps the second move only."""
    prices = _price_with_steps(base=0.0, steps={100: 5.0, 300: -5.0}, length=400)
    fuzzy = np.concatenate([_constant_series(5.0, 200), _constant_series(-5.0, 200)])

    settings = BacktestSettings(lookback_s=50.0)
    metrics = backtest(fuzzy, prices, dt_s=1.0, settings=settings, part=slice(200, 400))

    assert metrics.n_moves == 1


def test_backtest_rejects_series_of_different_lengths() -> None:
    """A price series of a different length than the advice is a programming error."""
    fuzzy = _constant_series(1.0, 10)
    prices = _constant_series(0.0, 9)

    with pytest.raises(ValueError, match="length"):
        backtest(fuzzy, prices, dt_s=1.0)


def test_backtest_rejects_a_non_positive_sample_interval() -> None:
    """A zero sampling interval cannot be turned into a sample count."""
    fuzzy = _constant_series(1.0, 10)
    prices = _constant_series(0.0, 10)

    with pytest.raises(ValueError):
        backtest(fuzzy, prices, dt_s=0.0)


def test_default_settings_are_the_documented_ones() -> None:
    """The default BacktestSettings carry the documented thresholds."""
    settings = BacktestSettings()

    assert settings.dead_band == pytest.approx(2.0)
    assert settings.lookback_s == pytest.approx(900.0)
    assert settings.silent_band == pytest.approx(1.0)
