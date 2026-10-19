"""Compare an advisory fuzzy output series against the operator's setpoint moves.

The operator only changes the setpoint in discrete jumps; a jump is treated as the
operator's "move". We ask whether the fuzzy advisor was already leaning in the same
direction just before that move (averaged over a lookback window), and summarise the
agreement with a small set of metrics. We also report how often the advice was silent.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Pearson correlation needs at least three points to be meaningful and to have a
# non-degenerate denominator.
MIN_MOVES_FOR_CORRELATION = 3


@dataclass(frozen=True)
class BacktestSettings:
    """Knobs of the advisory backtest, in engineering units of the setpoint and seconds."""

    dead_band: float = 2.0  # one-sample SP steps with |diff| <= dead_band are no move (SP units)
    lookback_s: float = 900.0  # fuzzy advice is averaged over this time before a move
    silent_band: float = 1.0  # |advice| <= silent_band counts as "fuzzy was silent"


@dataclass(frozen=True)
class BacktestMetrics:
    """Summary of advisory quality over a set of operator moves.

    A "usable" move is one whose advice is not NaN. Metrics over an empty set of
    usable moves are NaN rather than 0: 0 would claim a measured agreement.
    """

    n_moves: int  # moves with a usable (non-NaN) advice
    sign_agreement: float  # share of non-silent advices whose sign equals the move sign
    correlation: float  # Pearson correlation advice vs delta over usable moves
    majority_share: float  # max share of positive/negative deltas over usable moves
    silent_share: float  # share of usable moves where |advice| <= silent_band


def find_operator_moves(sp: np.ndarray, dead_band: float) -> tuple[np.ndarray, np.ndarray]:
    """Locate operator setpoint moves as runs of samples that jump beyond dead_band.

    A single operator move can span several samples (a ramp faster than dead_band per
    sample), so contiguous above-threshold differences are collapsed into ONE move; its delta
    is the plain sum of those differences, so a run mixing up and down steps can sum to ~0.
    The move index is the first sample AFTER the jump, i.e. the position in `sp` where
    the new setpoint is already in effect.

    Returns (indices, deltas): int array of move positions and float array of the
    summed setpoint change over each move. Both are empty when there is no move.
    """
    diffs = np.diff(np.asarray(sp, dtype=float))
    is_jump = np.abs(diffs) > dead_band
    start_position, length = _jump_run_starts(is_jump)
    if start_position.size == 0:
        return np.empty(0, dtype=int), np.empty(0, dtype=float)
    deltas = _sum_diffs_over_runs(diffs, start_position, length)
    indices = start_position + 1  # diff index + 1 is the first sample after the jump
    return indices.astype(int), deltas


def _jump_run_starts(is_jump: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (first index, run length) for each run of True in a boolean array.

    Runs are the maximal blocks of consecutive True values. The padding trick lets us
    detect a run start wherever the value rises from False to True.
    """
    padded = np.concatenate(([False], np.asarray(is_jump, dtype=bool), [False]))
    changes = np.diff(padded.astype(int))
    start_position = np.flatnonzero(changes == 1)
    length = np.flatnonzero(changes == -1) - start_position
    return start_position, length


def _sum_diffs_over_runs(
    diffs: np.ndarray, start_position: np.ndarray, length: np.ndarray
) -> np.ndarray:
    """Sum the per-sample differences inside each run to get the move delta."""
    prefix = np.concatenate(([0.0], np.cumsum(diffs)))
    end_position = start_position + length
    return np.asarray(prefix[end_position] - prefix[start_position], dtype=float)


def advice_before(fuzzy: np.ndarray, indices: np.ndarray, lookback_samples: int) -> np.ndarray:
    """Average the fuzzy advice over the `lookback_samples` just before each move.

    NaN entries are skipped (np.nanmean), so a partially missing history still yields
    an average. When the window is empty or entirely NaN the result is NaN; we guard
    explicitly instead of relying on nanmean's RuntimeWarning.
    """
    fuzzy = np.asarray(fuzzy, dtype=float)
    advice = np.empty(indices.size, dtype=float)
    for position, move_index in enumerate(indices):
        window = fuzzy[max(0, move_index - lookback_samples):move_index]
        advice[position] = _nanmean_or_nan(window)
    return advice


def _nanmean_or_nan(window: np.ndarray) -> float:
    """Mean of the finite values in `window`, or NaN if there is none."""
    if window.size == 0 or np.all(np.isnan(window)):
        return float("nan")
    return float(np.nanmean(window))


def score_moves(advice: np.ndarray, deltas: np.ndarray, silent_band: float) -> BacktestMetrics:
    """Compute agreement metrics between averaged advice and operator move deltas.

    Moves with NaN advice carry no information and are dropped first, so every metric
    is computed on the same set of usable moves.
    """
    advice = np.asarray(advice, dtype=float)
    deltas = np.asarray(deltas, dtype=float)
    is_usable = ~np.isnan(advice)
    advice = advice[is_usable]
    deltas = deltas[is_usable]

    if advice.size == 0:
        return _no_usable_moves()

    is_silent = np.abs(advice) <= silent_band
    return BacktestMetrics(
        n_moves=int(advice.size),
        sign_agreement=_sign_agreement(advice, deltas, is_silent),
        correlation=_pearson(advice, deltas),
        majority_share=_majority_share(deltas),
        silent_share=float(np.mean(is_silent)),
    )


def _no_usable_moves() -> BacktestMetrics:
    """Metrics for an empty set of usable moves: NaN everywhere, 0 moves."""
    nan = float("nan")
    return BacktestMetrics(0, nan, nan, nan, nan)


def _sign_agreement(advice: np.ndarray, deltas: np.ndarray, is_silent: np.ndarray) -> float:
    """Share of non-silent advices pointing in the same direction as the move.

    A silent advice is not a wrong advice but an absence of advice, so silence is
    excluded from the denominator. NaN when every advice is silent.
    """
    is_meaningful = ~is_silent
    if not np.any(is_meaningful):
        return float("nan")
    same_sign = np.sign(advice[is_meaningful]) == np.sign(deltas[is_meaningful])
    return float(np.mean(same_sign))


def _pearson(advice: np.ndarray, deltas: np.ndarray) -> float:
    """Pearson correlation between advice and deltas; NaN when it is undefined.

    Undefined for fewer than MIN_MOVES_FOR_CORRELATION points or when either series
    has zero variance, which would make the correlation a division by zero.
    """
    if advice.size < MIN_MOVES_FOR_CORRELATION:
        return float("nan")
    if np.std(advice) == 0.0 or np.std(deltas) == 0.0:
        return float("nan")
    return float(np.corrcoef(advice, deltas)[0, 1])


def _majority_share(deltas: np.ndarray) -> float:
    """Share of the move direction that is most frequent (always >= 0.5).

    This is the baseline a sign_agreement must beat to be better than always guessing
    the dominant direction.
    """
    share_up = float(np.mean(deltas > 0.0))
    return max(share_up, 1.0 - share_up)


def split_halves(n_samples: int) -> tuple[slice, slice]:
    """Split a series of `n_samples` into a first and a second half.

    Used to check that advisory quality is stable over time (drift detection). The
    first half is the smaller one when `n_samples` is odd.
    """
    midpoint = n_samples // 2
    return slice(0, midpoint), slice(midpoint, n_samples)


# codecheck: allow too-many-parameters (public signature used by payload.py, exp09, tests)
def backtest(
    fuzzy: np.ndarray,
    sp: np.ndarray,
    dt_s: float,
    settings: BacktestSettings | None = None,
    part: slice | None = None,
) -> BacktestMetrics:
    """Score the fuzzy advice against operator moves, optionally on one slice of time.

    Moves are always detected on the whole setpoint series: a slice boundary must not
    create a fake jump or split a real one. Only moves whose index falls inside `part`
    are scored. `dt_s` is the sampling period in seconds and converts `lookback_s` into
    a number of samples.

    Raises ValueError when the two series have different lengths or dt_s <= 0.
    """
    settings = settings or BacktestSettings()
    fuzzy = np.asarray(fuzzy, dtype=float)
    sp = np.asarray(sp, dtype=float)
    _check_inputs(fuzzy, sp, dt_s)
    indices, deltas = find_operator_moves(sp, settings.dead_band)
    if part is not None:
        is_in_part = (indices >= part.start) & (indices < part.stop)
        indices = indices[is_in_part]
        deltas = deltas[is_in_part]

    lookback_samples = max(1, round(settings.lookback_s / dt_s))
    advice = advice_before(fuzzy, indices, lookback_samples)
    return score_moves(advice, deltas, settings.silent_band)


def _check_inputs(fuzzy: np.ndarray, sp: np.ndarray, dt_s: float) -> None:
    """Raise ValueError for series of different length or a non-positive sampling period."""
    if fuzzy.shape != sp.shape:
        raise ValueError(
            f"fuzzy and sp must have the same length, got {fuzzy.size} and {sp.size}"
        )
    if dt_s <= 0.0:
        raise ValueError(f"dt_s must be positive seconds, got {dt_s}")
