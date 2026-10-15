"""Tests for the noise-checked derivative-advice function."""
from __future__ import annotations

import numpy as np
from crosscut_loops.identification_quality import pv_noise_sd
from crosscut_loops.tuning_pid import PidSettings, noise_checked_advice
from numpy import random


def test_pv_noise_sd_of_white_noise_is_estimated_correctly() -> None:
    """The pv_noise_sd of white noise N(0, 0.3) is within 10% of 0.3."""
    rng = random.default_rng(1)
    y = rng.normal(0.0, 0.3, 5000)
    assert abs(pv_noise_sd(y) - 0.3) <= 0.03


def test_pv_noise_sd_of_white_noise_plus_ramp_is_estimated_correctly() -> None:
    """The pv_noise_sd of white noise N(0, 0.3) plus a ramp stays within 15% of 0.3."""
    rng = random.default_rng(1)
    y = rng.normal(0.0, 0.3, 5000) + np.linspace(0.0, 50.0, 5000)
    assert abs(pv_noise_sd(y) - 0.3) <= 0.045


def test_pv_noise_sd_of_fewer_than_two_samples_is_zero() -> None:
    """The pv_noise_sd of fewer than two samples is 0.0."""
    assert pv_noise_sd([]) == 0.0
    assert pv_noise_sd([1.0]) == 0.0


def test_noise_checked_advice_returns_input_when_advice_is_false() -> None:
    """The noise_checked_advice returns the input unchanged when advice is (False, 'x')."""
    advice = (False, "x")
    settings = PidSettings(kc=2.0, ti_s=30.0, td_s=5.0)
    assert noise_checked_advice(advice, settings, 0.001, 100.0) == advice


def test_noise_checked_advice_returns_input_when_noise_is_small() -> None:
    """The noise_checked_advice returns the input unchanged when the noise is small."""
    advice = (True, "r")
    settings = PidSettings(kc=2.0, ti_s=30.0, td_s=5.0)
    assert noise_checked_advice(advice, settings, 0.001, 100.0) == advice


def test_noise_checked_advice_returns_false_when_noise_is_large() -> None:
    """The noise_checked_advice returns False when the noise is large."""
    advice = (True, "r")
    settings = PidSettings(kc=2.0, ti_s=30.0, td_s=5.0)
    result = noise_checked_advice(advice, settings, 5.0, 100.0)
    assert result[0] is False
    assert "PV noise too high" in result[1]


def test_noise_checked_advice_returns_input_when_out_span_is_zero() -> None:
    """The noise_checked_advice returns the input unchanged when out_span is 0."""
    advice = (True, "r")
    settings = PidSettings(kc=2.0, ti_s=30.0, td_s=5.0)
    assert noise_checked_advice(advice, settings, 5.0, 0.0) == advice
