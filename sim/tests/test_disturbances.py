"""Tests for the stochastic disturbance generators."""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_sim.disturbances import OrnsteinUhlenbeck, OuShape


def run(ornstein_uhlenbeck: OrnsteinUhlenbeck, sample_count: int) -> np.ndarray:
    """Return the next sample_count values produced by the Ornstein-Uhlenbeck process."""
    return np.array([ornstein_uhlenbeck.update() for _ in range(sample_count)])


def test_starts_at_mean_and_zero_sigma_is_constant() -> None:
    temperature = OrnsteinUhlenbeck(
        OuShape(mean=2.45, sigma=0.0, tau_s=600.0), dt_s=1.0, rng=np.random.default_rng(1)
    )
    assert temperature.value == 2.45
    assert all(value == 2.45 for value in run(temperature, 100))


def test_stationary_statistics() -> None:
    mean, sigma, tau = 2.45, 0.1, 60.0
    ou = OrnsteinUhlenbeck(
        OuShape(mean=mean, sigma=sigma, tau_s=tau), dt_s=1.0, rng=np.random.default_rng(7)
    )
    x = run(ou, 300_000)[1000:]
    assert x.mean() == pytest.approx(mean, abs=0.01)
    assert x.std() == pytest.approx(sigma, rel=0.06)
    lag1 = np.corrcoef(x[:-1], x[1:])[0, 1]
    assert lag1 == pytest.approx(np.exp(-1.0 / tau), abs=0.01)


def test_determinism_and_seed_sensitivity() -> None:
    def make(seed: int) -> OrnsteinUhlenbeck:
        """Build an Ornstein-Uhlenbeck process with fixed parameters and a seeded RNG."""
        return OrnsteinUhlenbeck(
            OuShape(mean=0.0, sigma=1.0, tau_s=100.0), dt_s=1.0, rng=np.random.default_rng(seed)
        )

    path_from_seed_three, repeat_from_seed_three, path_from_seed_four = (
        run(make(3), 500),
        run(make(3), 500),
        run(make(4), 500),
    )
    assert np.array_equal(path_from_seed_three, repeat_from_seed_three)
    assert not np.array_equal(path_from_seed_three, path_from_seed_four)


def test_invalid_parameters() -> None:
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        OrnsteinUhlenbeck(OuShape(0.0, -1.0, 10.0), dt_s=1.0, rng=rng)
    with pytest.raises(ValueError):
        OrnsteinUhlenbeck(OuShape(0.0, 1.0, 0.0), dt_s=1.0, rng=rng)
    with pytest.raises(ValueError):
        OrnsteinUhlenbeck(OuShape(0.0, 1.0, 10.0), dt_s=0.0, rng=rng)
