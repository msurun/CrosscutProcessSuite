"""Tests for the experiment helpers (correctness of the estimator, not of the scientific result)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from exp00 import DRIVERS, VARIANTS, fir_gains, highpass, main, true_gains


def test_fir_gains_recover_a_known_two_input_system() -> None:
    rng = np.random.default_rng(0)
    sample_count = 4000
    x1 = rng.normal(size=sample_count)
    x2 = rng.normal(size=sample_count)
    h1 = 0.5 * 0.8 ** np.arange(30)  # gain 0.5 / (1 - 0.8) = 2.5 (truncated)
    h2 = -0.3 * 0.7 ** np.arange(30)
    y = (
        np.convolve(x1, h1)[:sample_count]
        + np.convolve(x2, h2)[:sample_count]
        + 1.0
        + 0.01 * rng.normal(size=sample_count)
    )
    gains = fir_gains(y, [x1, x2], n_lags=40)
    assert gains[0] == pytest.approx(h1.sum(), abs=0.03)
    assert gains[1] == pytest.approx(h2.sum(), abs=0.03)


def test_highpass_removes_slow_components_and_keeps_fast_ones() -> None:
    sample_indices = np.arange(2000)
    slow_component = np.sin(2 * np.pi * sample_indices / 2000)
    fast_component = np.sin(2 * np.pi * sample_indices / 6)
    filtered = highpass(slow_component + fast_component, 20)
    middle = slice(100, -100)
    assert np.abs(filtered[middle] - fast_component[middle]).max() < 0.5
    assert np.abs(highpass(slow_component, 20)[middle]).max() < 0.01


def test_true_gains_use_the_plant_ground_truth() -> None:
    gains = true_gains()
    assert gains["hpgr_press"] == pytest.approx(-20.0)
    assert gains["mill_feed"] == pytest.approx(0.45)
    assert gains["cyc_water"] == pytest.approx(-0.6)


def test_experiment_runs_end_to_end_on_a_short_configuration(tmp_path: Path) -> None:
    assert main(["--seeds", "1", "--hours", "6", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "results.csv").is_file()
    text = (tmp_path / "results.md").read_text(encoding="utf-8")
    for variant in VARIANTS:
        assert variant in text
    for driver in DRIVERS:
        assert driver in text
