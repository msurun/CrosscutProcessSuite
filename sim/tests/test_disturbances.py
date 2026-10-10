"""Tests for the stochastic disturbance generators."""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_sim.disturbances import OrnsteinUhlenbeck


def run(ou: OrnsteinUhlenbeck, n: int) -> np.ndarray:
    return np.array([ou.update() for _ in range(n)])


def test_starts_at_mean_and_zero_sigma_is_constant() -> None:
    ou = OrnsteinUhlenbeck(
        mean=2.45, sigma=0.0, tau_s=600.0, dt_s=1.0, rng=np.random.default_rng(1)
    )
    assert ou.value == 2.45
    assert all(v == 2.45 for v in run(ou, 100))


def test_stationary_statistics() -> None:
    mean, sigma, tau = 2.45, 0.1, 60.0
    ou = OrnsteinUhlenbeck(
        mean=mean, sigma=sigma, tau_s=tau, dt_s=1.0, rng=np.random.default_rng(7)
    )
    x = run(ou, 300_000)[1000:]
    assert x.mean() == pytest.approx(mean, abs=0.01)
    assert x.std() == pytest.approx(sigma, rel=0.06)
    lag1 = np.corrcoef(x[:-1], x[1:])[0, 1]
    assert lag1 == pytest.approx(np.exp(-1.0 / tau), abs=0.01)


def test_determinism_and_seed_sensitivity() -> None:
    def make(seed: int) -> OrnsteinUhlenbeck:
        return OrnsteinUhlenbeck(
            mean=0.0, sigma=1.0, tau_s=100.0, dt_s=1.0, rng=np.random.default_rng(seed)
        )

    a, b, c = run(make(3), 500), run(make(3), 500), run(make(4), 500)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_invalid_parameters() -> None:
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        OrnsteinUhlenbeck(mean=0.0, sigma=-1.0, tau_s=10.0, dt_s=1.0, rng=rng)
    with pytest.raises(ValueError):
        OrnsteinUhlenbeck(mean=0.0, sigma=1.0, tau_s=0.0, dt_s=1.0, rng=rng)
    with pytest.raises(ValueError):
        OrnsteinUhlenbeck(mean=0.0, sigma=1.0, tau_s=10.0, dt_s=0.0, rng=rng)
