"""Tests for crosscut_anomaly.distributions against textbook tables.

Normal quantiles: standard z table. F quantiles: standard F tables, each
cross-checked by trapezoid integration of the F density (independent method).
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pytest
from crosscut_anomaly.distributions import (
    DistributionError,
    f_cdf,
    f_ppf,
    normal_cdf,
    normal_ppf,
    regularized_incomplete_beta,
)


@pytest.mark.parametrize("p,z", [(0.975, 1.959964), (0.99, 2.326348), (0.995, 2.575829)])
def test_normal_ppf_table(p: float, z: float) -> None:
    """z table values (6 decimals)."""
    assert normal_ppf(p) == pytest.approx(z, abs=1e-6)
    assert normal_cdf(z) == pytest.approx(p, abs=1e-6)


def test_normal_round_trip_and_tails() -> None:
    """ppf/cdf agree to 1e-9 on a grid including extreme tails."""
    for p in [1e-12, 1e-8, 1e-3, 0.02, 0.3, 0.5, 0.9, 0.999, 1 - 1e-9]:
        assert normal_cdf(normal_ppf(p)) == pytest.approx(p, rel=1e-9)
    assert normal_ppf(0.5) == pytest.approx(0.0, abs=1e-12)
    assert normal_ppf(0.0) == -math.inf and normal_ppf(1.0) == math.inf


def _integrated_cdf(x: float, d1: float, d2: float, n: int = 400001) -> float:
    """Trapezoid integral of the F density on [0, x] (independent of f_cdf)."""
    t = np.linspace(0.0, x, n)
    ln_c = (math.lgamma((d1 + d2) / 2) - math.lgamma(d1 / 2) - math.lgamma(d2 / 2)
            + (d1 / 2) * math.log(d1 / d2))
    with np.errstate(divide="ignore"):
        ln_f = (ln_c + (d1 / 2 - 1) * np.log(t)
                - ((d1 + d2) / 2) * np.log1p(d1 * t / d2))
    dens = np.exp(ln_f)
    dens[0] = 0.0
    return float(np.sum((dens[1:] + dens[:-1]) / 2 * np.diff(t)))


@pytest.mark.parametrize("p,d1,d2,table", [
    (0.95, 1, 30, 4.1709),   # = t_{0.975,30}^2 = 2.0423^2
    (0.95, 5, 20, 2.7109),
    (0.99, 5, 100, 3.2059),
    (0.99, 3, 500, 3.8210),   # remembered 3.8223 disagrees with integration; 3.8210 is correct
])
def test_f_ppf_table(p: float, d1: int, d2: int, table: float) -> None:
    """Table values, with the integral of the density as cross-check."""
    assert f_ppf(p, d1, d2) == pytest.approx(table, abs=1e-3)
    if d1 > 1:  # d1 = 1 density is singular at 0; covered by the t identity
        assert _integrated_cdf(table, d1, d2) == pytest.approx(p, abs=2e-4)
    assert f_cdf(f_ppf(p, d1, d2), d1, d2) == pytest.approx(p, abs=1e-10)


def test_f_one_dof_matches_t_identity() -> None:
    """F_0.95(1, 30) = 2.0423^2 (t table value 2.0423)."""
    assert f_ppf(0.95, 1, 30) == pytest.approx(2.0423**2, abs=2e-4)


def test_beta_known_values() -> None:
    """I_x(1,1)=x, I_x(a,1)=x^a, symmetry I_x(a,b)=1-I_{1-x}(b,a)."""
    assert regularized_incomplete_beta(0.3, 1, 1) == pytest.approx(0.3, abs=1e-14)
    assert regularized_incomplete_beta(0.4, 3, 1) == pytest.approx(0.064, abs=1e-14)
    lhs = regularized_incomplete_beta(0.7, 2.5, 4.0)
    assert lhs == pytest.approx(1 - regularized_incomplete_beta(0.3, 4.0, 2.5), abs=1e-13)


GRID_P = [1e-9, 1e-4, 0.01, 0.1, 0.5, 0.9, 0.99, 0.9999, 1 - 1e-9]
GRID_D = [(1, 1), (1, 30), (2.5, 7.5), (5, 20), (10, 1000), (50, 3), (200, 400)]


@pytest.mark.parametrize("d1,d2", GRID_D)
def test_f_round_trips(d1: float, d2: float) -> None:
    """cdf(ppf(p)) = p and ppf(cdf(x)) = x within 1e-9."""
    for p in GRID_P:
        x = f_ppf(p, d1, d2)
        assert f_cdf(x, d1, d2) == pytest.approx(p, abs=1e-9)
    for x in [0.05, 0.5, 1.0, 3.0, 10.0]:
        p = f_cdf(x, d1, d2)
        if 1e-12 < p < 1 - 1e-12:
            assert f_ppf(p, d1, d2) == pytest.approx(x, rel=1e-6, abs=1e-9)


def test_monotonicity() -> None:
    """cdf and ppf are non-decreasing."""
    xs = np.linspace(0.0, 20.0, 200)
    cdfs = [f_cdf(float(x), 4, 9) for x in xs]
    assert all(b >= a for a, b in zip(cdfs, cdfs[1:], strict=False))
    ps = np.linspace(0.001, 0.999, 100)
    qs = [f_ppf(float(p), 4, 9) for p in ps]
    assert all(b > a for a, b in zip(qs, qs[1:], strict=False))
    nq = [normal_ppf(float(p)) for p in ps]
    assert all(b > a for a, b in zip(nq, nq[1:], strict=False))


def test_f_extremes() -> None:
    """p near 0 and 1, and the endpoints."""
    assert f_ppf(0.0, 3, 4) == 0.0 and f_ppf(1.0, 3, 4) == math.inf
    assert f_cdf(f_ppf(1e-12, 3, 4), 3, 4) == pytest.approx(1e-12, rel=1e-6)
    assert f_cdf(f_ppf(1 - 1e-12, 3, 4), 3, 4) == pytest.approx(1 - 1e-12, abs=1e-11)


@pytest.mark.parametrize("call", [
    lambda: normal_ppf(-0.1),
    lambda: normal_ppf(1.5),
    lambda: normal_cdf(float("nan")),
    lambda: regularized_incomplete_beta(1.1, 1, 1),
    lambda: regularized_incomplete_beta(0.5, 0, 1),
    lambda: regularized_incomplete_beta(0.5, 1, -2),
    lambda: f_cdf(1.0, 0, 5),
    lambda: f_cdf(1.0, 5, -1),
    lambda: f_ppf(0.5, 0, 5),
    lambda: f_ppf(1.2, 3, 5),
    lambda: f_ppf(-0.2, 3, 5),
])
def test_invalid_inputs(call: Callable[[], float]) -> None:
    """Out-of-domain input raises DistributionError (a ValueError)."""
    with pytest.raises(DistributionError):
        call()
    assert issubclass(DistributionError, ValueError)
