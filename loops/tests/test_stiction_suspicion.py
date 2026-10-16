"""Tests for the ranked stiction suspicion of one loop.

Synthetic loops from test_stiction.simulate_loop (fixed seeds). Sticking seeds 1, 5, 7 limit-cycle
(seeds 3, 6, 8 do not and give not_ranked); healthy seeds 1 and 2 carry a sinusoidal disturbance.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.stiction_suspicion import (
    TEST_VALVE_MIN,
    SuspicionResult,
    stiction_suspicion,
)
from numpy.typing import NDArray
from test_stiction import LONG_RECORD, simulate_loop

DT = 1.0
STICKING_SEEDS = (1, 5, 7)


def run(pv: NDArray[np.float64], out: NDArray[np.float64], kind: str = "F") -> SuspicionResult:
    """Run stiction_suspicion with a zero setpoint and dt of one second."""
    return stiction_suspicion(np.zeros(len(pv)), pv, out, DT, kind)


def sticking(seed: int = 1) -> SuspicionResult:
    """Suspicion of a sticking synthetic loop."""
    pv, out = simulate_loop(seed=seed, stiction=True, sample_count=LONG_RECORD)
    return run(pv, out)


def healthy(seed: int = 1) -> SuspicionResult:
    """Suspicion of a healthy loop with a sinusoidal disturbance."""
    pv, out = simulate_loop(seed=seed, stiction=False, disturbance_amp=0.3)
    return run(pv, out)


@pytest.mark.parametrize("seed", STICKING_SEEDS)
def test_sticking_loop_advises_valve_test(seed: int) -> None:
    """Sticking loops (seeds 1, 5, 7) score at least 0.5 with a positive period."""
    result = sticking(seed)
    assert result.advice == "test_valve"
    assert result.score is not None
    assert result.score >= 0.5
    assert result.period_s is not None
    assert result.period_s > 0


@pytest.mark.parametrize("seed", [1, 2])
def test_healthy_loop_with_disturbance_is_not_advised_a_test(seed: int) -> None:
    """Healthy seeds 1 and 2 are ranked and come out 'unlikely' (score about 0.35)."""
    result = healthy(seed)
    assert result.advice != "test_valve"
    assert result.advice == "unlikely"
    assert result.score is not None
    assert result.score < TEST_VALVE_MIN


def test_white_noise_with_constant_out_is_not_ranked() -> None:
    """White noise PV (seed 5) with constant OUT has no oscillation window."""
    pv = np.random.default_rng(5).normal(scale=0.1, size=4000)
    result = run(pv, np.full(4000, 50.0))
    assert result.advice == "not_ranked"
    assert result.score is None


def test_nan_in_arrays_is_not_ranked_without_exception() -> None:
    """NaN in PV gives not_ranked instead of an exception."""
    pv, out = simulate_loop(seed=1, stiction=True, sample_count=LONG_RECORD)
    pv[100] = np.nan
    result = run(pv, out)
    assert result.advice == "not_ranked"
    assert result.score is None


def test_unequal_lengths_raise_value_error() -> None:
    """Arrays of different length raise ValueError."""
    with pytest.raises(ValueError, match="same length"):
        stiction_suspicion(np.zeros(100), np.zeros(100), np.zeros(99), DT)


def test_non_positive_dt_raises_value_error() -> None:
    """dt_s of zero or below raises ValueError."""
    for dt_s in (0.0, -1.0):
        with pytest.raises(ValueError, match="dt_s"):
            stiction_suspicion(np.zeros(100), np.zeros(100), np.zeros(100), dt_s)


def test_unknown_kind_raises_value_error() -> None:
    """Kind 'X' raises ValueError."""
    with pytest.raises(ValueError, match="kind"):
        stiction_suspicion(np.zeros(100), np.zeros(100), np.zeros(100), DT, "X")


def test_kind_l_has_no_horch() -> None:
    """Kind 'L' never computes Horch, whatever the rest of the result (seed 1)."""
    pv, out = simulate_loop(seed=1, stiction=True, sample_count=LONG_RECORD)
    assert run(pv, out, "L").horch is None


def test_kind_f_on_sticking_loop_has_horch() -> None:
    """Kind 'F' on a sticking loop (seed 1) returns a Horch value."""
    assert sticking(1).horch is not None


@pytest.mark.parametrize(
    "result",
    [sticking(1), sticking(5), sticking(7), healthy(1), healthy(2), sticking(3)],
    ids=["stick1", "stick5", "stick7", "healthy1", "healthy2", "stick3-no-cycle"],
)
def test_advice_follows_score_threshold(result: SuspicionResult) -> None:
    """Advice is test_valve iff score >= TEST_VALVE_MIN, unlikely below, not_ranked for None."""
    if result.score is None:
        assert result.advice == "not_ranked"
    elif result.score >= TEST_VALVE_MIN:
        assert result.advice == "test_valve"
    else:
        assert result.advice == "unlikely"


def test_very_short_record_is_not_ranked() -> None:
    """A record of 50 samples is not ranked."""
    pv, out = simulate_loop(seed=1, stiction=True, sample_count=LONG_RECORD)
    result = run(pv[:50], out[:50])
    assert result.advice == "not_ranked"
    assert result.score is None
