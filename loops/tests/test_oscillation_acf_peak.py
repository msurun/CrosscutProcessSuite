"""Tests for the ACF detector options added in exp20/exp21: noise-band variants and the peak gate.

They pin the shipped defaults, the Bartlett band shapes and the behaviour of the optional
peak-strength gate on a clear sine and on AR(1) noise.
"""

import numpy as np
import pytest
from crosscut_loops.oscillation_acf import (
    BAND_BARTLETT,
    BAND_BARTLETT_LAG,
    BAND_WHITE,
    AcfConfig,
    _noise_sigma,
    _peak_is_strong,
    acf_regularity,
)

SINE_PERIOD_SAMPLES = 60
SINE_LENGTH = 300
NOISE_STD = 0.3
PERIOD_TOLERANCE = 0.10  # accept the estimated period within 10 % of the true one
AR_LENGTH = 3000
AR_SEEDS = range(20)
AR_MAX_DETECTIONS = 1
AR_PHI = 0.5  # AR(1) coefficient of the noise process

# Gate variant with a wide lag band and a strong peak requirement.
GATED = AcfConfig(band=BAND_BARTLETT_LAG, min_crossings=5, max_lag_fraction=0.75,
                  unbiased=True, peak_z=3.0)


def _sine_with_noise(seed: int) -> np.ndarray:
    """Sine of one period every 60 samples plus white noise, unit amplitude."""
    rng = np.random.default_rng(seed)
    time = np.arange(SINE_LENGTH)
    sine = np.sin(2.0 * np.pi * time / SINE_PERIOD_SAMPLES)
    return sine + NOISE_STD * rng.standard_normal(SINE_LENGTH)


def _ar1_noise(seed: int, length: int, phi: float) -> np.ndarray:
    """AR(1) process x[k] = phi * x[k-1] + e[k] with standard normal innovations e."""
    rng = np.random.default_rng(seed)
    innovations = rng.standard_normal(length)
    samples = np.empty(length)
    samples[0] = innovations[0]
    for k in range(1, length):
        samples[k] = phi * samples[k - 1] + innovations[k]
    return samples


def test_default_config_unchanged():
    """The shipped config equals the explicit defaults in field order."""
    assert AcfConfig() == AcfConfig(BAND_BARTLETT, 7, 0.5, False, 0.0)


def test_lag_band_widens_with_lag():
    """The lag band grows strictly with lag and starts at the plain Bartlett value."""
    acf = np.array([1.0, 0.5, -0.1, 0.05, 0.0])
    n_samples = 10
    sigma_lag = _noise_sigma(acf, n_samples, AcfConfig(band=BAND_BARTLETT_LAG))
    sigma_plain = _noise_sigma(acf, n_samples, AcfConfig(band=BAND_BARTLETT))

    assert np.all(np.diff(sigma_lag) > 0.0)
    assert sigma_lag[0] == pytest.approx(np.sqrt((1.0 + 2.0 * 0.25) / n_samples))
    assert np.allclose(sigma_plain, sigma_plain[0])
    assert sigma_plain[0] == pytest.approx(sigma_lag[0])


def test_white_band_value():
    """The white band is 1 / sqrt(n) at every lag, whatever the ACF."""
    acf = np.array([1.0, 0.5, -0.1, 0.05, 0.0])
    n_samples = 10
    sigma = _noise_sigma(acf, n_samples, AcfConfig(band=BAND_WHITE))

    assert np.allclose(sigma, 1.0 / np.sqrt(n_samples))


def test_peak_gate_keeps_clear_sine():
    """A clear sine passes the gate and its period is recovered within 10 %."""
    result = acf_regularity(_sine_with_noise(seed=1), dt_s=1.0, config=GATED)

    assert result.regular is True
    assert result.period_s == pytest.approx(SINE_PERIOD_SAMPLES, rel=PERIOD_TOLERANCE)


def test_peak_gate_rejects_ar05_noise():
    """AR(1) noise with phi=0.5 is detected as regular in at most 1 of 20 runs."""
    detections = sum(
        acf_regularity(_ar1_noise(seed, AR_LENGTH, AR_PHI), dt_s=1.0, config=GATED).regular
        for seed in AR_SEEDS
    )

    assert detections <= AR_MAX_DETECTIONS


def test_weak_peak_reason():
    """The gate accepts a lobe at 0.3 over sigma 0.1 for peak_z 2.5 and rejects it for 3.5."""
    acf = np.array([1.0, 0.2, -0.2, -0.2, 0.2, 0.3, 0.2, -0.2, -0.2, 0.2])
    sigma = np.full(10, 0.1)
    crossings = np.array([1.5, 3.5, 6.5])

    assert _peak_is_strong(acf, sigma, crossings, peak_z=2.5) is True
    assert _peak_is_strong(acf, sigma, crossings, peak_z=3.5) is False
