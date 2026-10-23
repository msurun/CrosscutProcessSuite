"""Robustness tests: non-finite values, per-tag quality, quality shapes, fit_from_config.

Infinite values are treated like NaN (invalid, never imputed, no RuntimeWarning).
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator

import numpy as np
import pytest
from crosscut_anomaly.config import AnomalyConfig
from crosscut_anomaly.detect import scan
from crosscut_anomaly.pca_model import PcaModel, PcaModelError, fit_from_config, fit_pca

TAGS = ("a", "b", "c", "d")
MIX = np.array([[1.0, 0.0], [0.8, 0.5], [0.0, 1.0], [0.4, -0.9]])
CFG = AnomalyConfig(
    schema_version="1.0.0", id="t", tags=TAGS, mode="advisory",
    alpha=0.999, min_consecutive=5, close_after=10,
)


def make_data(n: int, seed: int) -> np.ndarray:
    """Four tags from two latent factors plus small noise."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal((n, 2)) @ MIX.T + 0.1 * rng.standard_normal((n, 4))


@pytest.fixture(scope="module")
def model() -> PcaModel:
    return fit_pca(make_data(2000, 1), TAGS, alpha=0.999)


@pytest.fixture(autouse=True)
def no_warnings() -> Iterator[None]:
    """Turn every warning into an error inside these tests."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        yield


def test_fit_drops_inf_rows() -> None:
    x = make_data(500, 2)
    clean = fit_pca(x, TAGS)
    x[3, 1], x[9, 0], x[20, 2] = np.inf, -np.inf, np.nan
    dirty = fit_pca(x, TAGS)
    assert dirty.n_train == clean.n_train - 3
    assert np.isfinite(dirty.mean).all()


def test_fit_rejects_mostly_inf() -> None:
    x = make_data(100, 2)
    x[:60, 0] = np.inf
    with pytest.raises(PcaModelError):
        fit_pca(x, TAGS)


def test_statistics_nan_for_inf_rows(model: PcaModel) -> None:
    x = make_data(4, 3)
    x[1, 0], x[2, 3] = np.inf, -np.inf
    for stat in (model.t2(x), model.spe(x)):
        assert np.isnan(stat[[1, 2]]).all() and np.isfinite(stat[[0, 3]]).all()
    with pytest.raises(PcaModelError):
        model.contributions(x[1])


def test_scan_counts_inf_as_skipped(model: PcaModel) -> None:
    x = make_data(300, 4)
    x[10, 0], x[11, 2], x[12, 1] = np.inf, -np.inf, np.nan
    res = scan(model, np.arange(300) * 60.0, x, config=CFG)
    assert res.skipped_reasons == {"nan": 3, "quality": 0}
    assert res.n_valid == 297 and res.n_skipped == 3


def test_per_tag_quality_equals_row_quality(model: PcaModel) -> None:
    x = make_data(300, 5)
    t = np.arange(300) * 60.0
    per_tag = np.zeros((300, 4))
    per_tag[5, 2], per_tag[40, 0], per_tag[41, 3] = 1.0, 2.0, 1.0
    per_row = per_tag.any(axis=1).astype(float)
    a = scan(model, t, x, per_tag, CFG)
    b = scan(model, t, x, per_row, CFG)
    assert a == b and a.skipped_reasons["quality"] == 3


def test_per_tag_quality_with_square_shape(model: PcaModel) -> None:
    x = make_data(4, 6)
    res = scan(model, np.arange(4.0), x, np.zeros((4, 4)), CFG)
    assert res.n_valid == 4


@pytest.mark.parametrize("shape", [(299,), (301,), (300, 3), (299, 4), (300, 4, 1), (1, 300), ()])
def test_wrong_quality_shapes_raise(model: PcaModel, shape: tuple[int, ...]) -> None:
    x = make_data(300, 7)
    with pytest.raises(ValueError, match="quality"):
        scan(model, np.arange(300) * 60.0, x, np.zeros(shape), CFG)


def test_square_ambiguity_requires_n_p_exact(model: PcaModel) -> None:
    x = make_data(4, 8)
    with pytest.raises(ValueError, match="quality"):
        scan(model, np.arange(4.0), x, np.zeros((4, 3)), CFG)


def test_fit_from_config_matches_fit_pca() -> None:
    x = make_data(1000, 9)
    cfg = AnomalyConfig(
        schema_version="1.0.0", id="t", tags=TAGS, mode="advisory",
        variance_fraction=0.80, alpha=0.95,
    )
    assert fit_from_config(x, cfg).sha256() == fit_pca(x, TAGS, 0.80, 0.95).sha256()
