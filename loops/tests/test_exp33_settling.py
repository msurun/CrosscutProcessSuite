"""Synthetic sensor-resolution regressions for settling bands.

Seeded signals exercise quantisation without using public experiment recordings.
"""

import numpy as np
import pytest
from crosscut_loops.history_windows import WindowSettings, find_excitation_windows
from crosscut_loops.metrics import detected_quantisation_step, settling_band


def _quantised_response() -> tuple[np.ndarray, np.ndarray]:
    """Return a setpoint step and first-order PV samples on a 0.4-unit sensor lattice."""
    generator = np.random.default_rng(102)
    time_s = np.arange(1000, dtype=float)
    setpoint = np.where(time_s >= 100.0, 10.1, 0.0)
    response = 10.1 * (1.0 - np.exp(-np.maximum(time_s - 100.0, 0.0) / 25.0))
    noise = generator.normal(0.0, 0.15, time_s.size)
    return setpoint, np.round((response + noise) / 0.4) * 0.4


def test_a_repeated_sensor_lattice_has_a_detected_step() -> None:
    """Small repeated differences recover the sensor resolution in PV units."""
    _, process_value = _quantised_response()

    assert detected_quantisation_step(process_value) == pytest.approx(0.4)


def test_a_quantised_response_widens_the_default_settling_band() -> None:
    """The result records that resolution, rather than configured percent, set the band."""
    setpoint, process_value = _quantised_response()

    windows = find_excitation_windows(setpoint, process_value, 1.0)

    assert len(windows) == 1
    assert windows[0].band_widened is True
    assert windows[0].settling_band == pytest.approx(1.2)
    assert windows[0].settled is True


def test_the_sensor_step_multiplier_can_be_configured() -> None:
    """A caller can select a larger number of codes for the half-band."""
    setpoint, process_value = _quantised_response()

    window = find_excitation_windows(
        setpoint, process_value, 1.0, WindowSettings(quantisation_multiplier=4.0)
    )[0]

    assert window.settling_band == pytest.approx(1.6)


def test_a_wide_configured_band_is_preserved() -> None:
    """Existing engineering tolerances remain the lower bound."""
    _, process_value = _quantised_response()

    assert settling_band(process_value, 2.0) == (2.0, False)


def test_continuous_noise_does_not_invent_a_sensor_lattice() -> None:
    """An arbitrary small percentile of continuous differences is not quantisation."""
    process_value = np.random.default_rng(33).normal(size=1000)

    assert detected_quantisation_step(process_value) == 0.0


def test_double_steps_do_not_hide_a_supported_single_step() -> None:
    """Fast motion may make two codes more common than one code."""
    generator = np.random.default_rng(34)
    increments = generator.permutation(np.concatenate((np.full(80, 0.8), np.full(20, 0.4))))
    process_value = np.concatenate(([0.0], np.cumsum(increments)))

    assert detected_quantisation_step(process_value) == pytest.approx(0.4)


def test_missing_samples_do_not_create_differences_across_gaps() -> None:
    """An unsupported short trace leaves the configured tolerance unchanged."""
    process_value = np.array([0.0, np.nan, 10.0, 10.0])

    assert settling_band(process_value, 0.1) == (0.1, False)


def test_a_negative_multiplier_is_rejected() -> None:
    """Invalid configuration gives an actionable exception."""
    with pytest.raises(ValueError, match="quantisation_multiplier"):
        settling_band(np.zeros(30), 0.1, -1.0)
