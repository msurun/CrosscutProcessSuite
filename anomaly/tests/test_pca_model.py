"""Tests for the PCA monitoring model: fit, limits, contributions, I/O.

Limits are checked against independent hand formulas, a hard-coded example
and the empirical exceedance rate on fresh Gaussian samples.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from crosscut_anomaly.distributions import f_ppf, normal_ppf
from crosscut_anomaly.pca_model import (
    PcaModel,
    PcaModelError,
    fit_pca,
    spe_limit,
    t2_limit,
)

TAGS = ("a", "b", "c", "d")
MIX = np.array([[1.0, 0.0], [0.8, 0.5], [0.0, 1.0], [0.4, -0.9]])


def make_data(n: int, seed: int) -> np.ndarray:
    """Four tags from two latent factors plus small noise."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal((n, 2)) @ MIX.T + 0.1 * rng.standard_normal((n, 4))


@pytest.fixture(scope="module")
def model() -> PcaModel:
    return fit_pca(make_data(5000, 1), TAGS)


def test_rank_subspace_and_monotone_variance(model: PcaModel) -> None:
    assert model.k == 2
    ev = model.eigenvalues
    assert np.all(np.diff(ev) <= 0)
    x = make_data(200000, 7)
    true_basis, _ = np.linalg.qr(MIX / x.std(axis=0)[:, None])
    q, _ = np.linalg.qr(model.loadings)
    cosines = np.linalg.svd(true_basis.T @ q, compute_uv=False)
    assert np.arccos(np.clip(cosines, -1, 1)).max() < 0.05


def test_limits_match_hand_formulas(model: PcaModel) -> None:
    ev = [float(v) for v in model.eigenvalues]
    k, n, alpha = model.k, model.n_train, model.alpha
    th = [sum(v**i for v in ev[k:]) for i in (1, 2, 3)]
    h0 = 1 - 2 * th[0] * th[2] / (3 * th[1] ** 2)
    c = normal_ppf(alpha)
    q = th[0] * (c * math.sqrt(2 * th[1] * h0**2) / th[0] + 1
                 + th[1] * h0 * (h0 - 1) / th[0] ** 2) ** (1 / h0)
    assert model.spe_limit == pytest.approx(q, rel=1e-12)
    t2 = k * (n * n - 1) / (n * (n - k)) * f_ppf(alpha, k, n - k)
    assert model.t2_limit == pytest.approx(t2, rel=1e-12)
    assert t2_limit(n, k, alpha) == model.t2_limit


def test_spe_limit_hard_coded_example() -> None:
    ev = [3.0, 1.2, 0.5, 0.2, 0.1]
    # theta1 = 0.8, theta2 = 0.30, theta3 = 0.134 (residual after k = 2)
    h0 = 1 - 2 * 0.8 * 0.134 / (3 * 0.09)
    assert h0 == pytest.approx(0.20592, abs=1e-4)
    c = 2.3263478740408408  # normal quantile at 0.99
    expected = 0.8 * (c * math.sqrt(2 * 0.30 * h0**2) / 0.8 + 1
                      + 0.30 * h0 * (h0 - 1) / 0.64) ** (1 / h0)
    assert spe_limit(ev, 2, 0.99) == pytest.approx(expected, rel=1e-9)
    assert 0.8 < expected < 5.0


def test_empirical_exceedance_within_factor_two(model: PcaModel) -> None:
    # The SPE limit is an approximation (Jackson-Mudholkar), hence the band.
    fresh = make_data(20000, 99)
    for stat, lim in ((model.t2(fresh), model.t2_limit),
                      (model.spe(fresh), model.spe_limit)):
        share = float(np.mean(stat > lim))
        assert 0.5 * (1 - model.alpha) <= share <= 2 * (1 - model.alpha)


def test_contributions_identify_off_subspace_tag(model: PcaModel) -> None:
    row = np.zeros((1, 4))
    row[0, 3] = 5 * float(model.scale[3])
    # tag d is anti-correlated with b in the model, so shifting it alone
    # breaks the correlation structure
    shifted = model.mean + row[0]
    contrib = model.contributions(shifted)
    assert sum(contrib["spe"].values()) == pytest.approx(1.0)
    assert sum(contrib["t2"].values()) == pytest.approx(1.0)
    assert max(contrib["spe"], key=contrib["spe"].__getitem__) == "d"
    assert list(contrib["spe"]) == list(TAGS)


def test_nan_rows_give_nan(model: PcaModel) -> None:
    x = make_data(3, 5)
    x[1, 2] = np.nan
    assert np.isnan(model.t2(x)[1]) and np.isnan(model.spe(x)[1])
    assert not np.isnan(model.t2(x)[[0, 2]]).any()
    with pytest.raises(PcaModelError):
        model.contributions(x[1])


def test_fit_drops_nan_rows() -> None:
    x = make_data(400, 3)
    x[::10, 0] = np.nan
    assert fit_pca(x, TAGS).n_train == 360


def test_too_few_rows_and_zero_variance() -> None:
    with pytest.raises(PcaModelError):
        fit_pca(make_data(39, 1), TAGS)
    x = make_data(500, 1)
    x[:, 1] = 3.0
    with pytest.raises(PcaModelError):
        fit_pca(x, TAGS)


def test_round_trip_and_stable_hash(model: PcaModel) -> None:
    again = PcaModel.from_dict(model.to_dict())
    assert again.to_dict() == model.to_dict()
    assert again.sha256() == model.sha256()
    assert model.to_dict()["kind"] == "pca"
    assert model.to_dict()["schema_version"] == "1.0.0"
    other = fit_pca(make_data(5000, 2), TAGS)
    assert other.sha256() != model.sha256()
    assert fit_pca(make_data(5000, 1), TAGS).sha256() == model.sha256()


def test_sign_convention(model: PcaModel) -> None:
    flipped = fit_pca(-make_data(5000, 1), TAGS)
    for m in (model, flipped):
        for i in range(m.k):
            col = m.loadings[:, i]
            assert col[np.argmax(np.abs(col))] > 0
