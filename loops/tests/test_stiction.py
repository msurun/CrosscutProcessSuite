"""Tests for the stiction detection algorithm."""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.stiction import detect_stiction
from numpy.typing import NDArray

DT = 1.0
N = 6000
RNG = np.random.default_rng(3)


def simulate_loop(
    seed: int, stiction: bool, disturbance_amp: float = 0.0, n: int = N
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    rng = np.random.default_rng(seed)
    pv = np.zeros(n)
    out = np.zeros(n)
    integral = 0.0
    x_old = 0.0
    a = np.exp(-1 / 20)
    kc = 0.5
    ti = 20
    S = 0.5
    J = 0.25
    load = 1.0  # constant load disturbance: without it the valve never leaves its rest position

    for k in range(1, n):
        e = -pv[k - 1]
        integral += e * DT
        u = kc * (e + integral / ti)

        if stiction:
            if abs(u - x_old) > S:
                x = u - np.sign(u - x_old) * (S - J)
                x_old = x
            else:
                x = x_old
        else:
            x = u

        disturbance = disturbance_amp * np.sin(2 * np.pi * k / 150)
        noise = rng.normal(scale=0.005)
        pv[k] = a * pv[k - 1] + (1 - a) * (x + load + disturbance) + noise
        out[k] = u

    return pv[1000:], out[1000:]


def test_stiction_loop_is_detected() -> None:
    pv, out = simulate_loop(seed=1, stiction=True)
    result = detect_stiction(pv, out, DT)
    assert result.verdict == "stiction"


def test_healthy_oscillating_loop_is_not_detected() -> None:
    pv, out = simulate_loop(seed=1, stiction=False, disturbance_amp=0.3)
    result = detect_stiction(pv, out, DT)
    assert result.verdict == "no_stiction"


def test_white_noise_is_inconclusive() -> None:
    pv = RNG.normal(size=4000)
    out = RNG.normal(size=4000)
    result = detect_stiction(pv, out, DT)
    assert result.verdict == "inconclusive"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_stiction_verdict_is_consistent(seed: int) -> None:
    pv, out = simulate_loop(seed=seed, stiction=True)
    result = detect_stiction(pv, out, DT)
    assert result.verdict == "stiction"


def test_stiction_loop_has_period_and_cycles() -> None:
    pv, out = simulate_loop(seed=1, stiction=True)
    result = detect_stiction(pv, out, DT)
    assert result.period_s is not None
    assert result.n_cycles >= 5


def test_healthy_oscillating_loop_has_correct_period() -> None:
    pv, out = simulate_loop(seed=1, stiction=False, disturbance_amp=0.3)
    result = detect_stiction(pv, out, DT)
    assert result.period_s == pytest.approx(150.0, rel=0.15)


def test_invalid_input_raises_value_error() -> None:
    pv = np.zeros(1000)
    out = np.zeros(1001)
    with pytest.raises(ValueError):
        detect_stiction(pv, out, DT)

    pv = np.zeros(1000)
    out = np.zeros(1000)
    out[500] = np.nan
    with pytest.raises(ValueError):
        detect_stiction(pv, out, DT)

    pv = np.zeros(1000)
    out = np.zeros(1000)
    with pytest.raises(ValueError):
        detect_stiction(pv, out, -1.0)
