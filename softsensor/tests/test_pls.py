"""Tests of the PLS soft sensor: NIPALS vs OLS, invariances, CV gap, lags, validity, round trip."""

from __future__ import annotations

import json

import numpy as np
import pytest
from crosscut_softsensor.config import SoftSensorConfig, load_config
from crosscut_softsensor.features import FeatureError, build_lagged
from crosscut_softsensor.pls import PlsModel, PlsModelError, cv_split, fit_pls, nipals_pls1


def _config(
    tags: tuple[str, ...], lags: tuple[float, ...] = (0.0,), max_components: int = 8
) -> SoftSensorConfig:
    return SoftSensorConfig(
        id="t", target_tag="y", input_tags=tags, lags_s=lags, max_components=max_components
    )


def _latent(n: int = 600, seed: int = 1, p: int = 10, k: int = 3) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    t = rng.normal(size=(n, k))
    x = t @ rng.normal(size=(k, p)) + 0.3 * rng.normal(size=(n, p))
    y = t @ np.array([1.0, -0.7, 0.5][:k]) + 0.1 * rng.normal(size=n)
    return x * rng.uniform(1, 5, p) + rng.uniform(-3, 3, p), 10 + 4 * y


def _tags(p: int) -> tuple[str, ...]:
    return tuple(f"c{i}" for i in range(p))


def test_full_rank_equals_ols_and_first_weight_direction() -> None:
    x, y = _latent()
    model = fit_pls(x, y, _config(_tags(10), max_components=10), n_components=10)
    design = np.column_stack([x, np.ones(len(x))])
    ols = design @ np.linalg.lstsq(design, y, rcond=None)[0]
    assert np.max(np.abs(model.predict(x) - ols)) < 1e-6
    zx = (x - x.mean(0)) / x.std(0, ddof=1)
    zy = (y - y.mean()) / y.std(ddof=1)
    w1 = zx.T @ zy
    assert np.allclose(model.weights[:, 0], w1 / np.linalg.norm(w1), atol=1e-10)
    w, _, _ = nipals_pls1(zx, zy, 3)
    assert np.allclose(w[:, 0], model.weights[:, 0])


def test_shift_and_rescale_change_nothing() -> None:
    x, y = _latent(seed=2)
    base = fit_pls(x, y, _config(_tags(10), max_components=6))
    x2 = x.copy()
    x2[:, 3] = x2[:, 3] * 1000.0 + 5e4
    other = fit_pls(x2, y, _config(_tags(10), max_components=6))
    assert other.chosen_components == base.chosen_components
    assert np.allclose(other.predict(x2), base.predict(x), atol=1e-6)
    shifted = fit_pls(x + 100.0, y, _config(_tags(10), max_components=6))
    assert shifted.chosen_components == base.chosen_components
    assert np.allclose(shifted.predict(x + 100.0), base.predict(x), atol=1e-6)


def test_cv_gap_removes_rows_around_each_block() -> None:
    idx = np.arange(100)
    gap = 7
    splits = cv_split(idx, 5, gap)
    for train, val in splits:
        assert set(train).isdisjoint(val)
        before = range(val[0] - gap, val[0])
        after = range(val[-1] + 1, val[-1] + 1 + gap)
        removed = [i for i in [*before, *after] if 0 <= i < 100]
        assert not set(removed) & set(train)
        assert len(train) == 100 - len(val) - len(removed)
    assert cv_split(idx, 5, 0)[2][0].size == 80


def test_cv_gap_uses_original_indices_with_sparse_rows() -> None:
    idx = np.arange(0, 400, 40)  # sparse lab rows, 10 of them
    train, val = cv_split(idx, 5, 40)[2]
    assert list(idx[val]) == [160, 200]
    assert sorted(idx[train]) == [0, 40, 80, 280, 320, 360]


def test_lagged_features_use_only_the_past() -> None:
    rng = np.random.default_rng(3)
    cols = {"a": rng.normal(size=50), "b": rng.normal(size=50)}
    x, names = build_lagged(cols, ["a", "b"], [0, 120, 300], 60.0)
    assert names == ["a@0", "a@120", "a@300", "b@0", "b@120", "b@300"]
    for tag in cols:
        for lag in (0, 120, 300):
            k = lag // 60
            col = x[:, names.index(f"{tag}@{lag}")]
            assert np.isnan(col[:k]).all()
            assert np.array_equal(col[k:], cols[tag][: 50 - k])
            assert col[10] == cols[tag][10 - k]
    with pytest.raises(FeatureError):
        build_lagged(cols, ["a"], [-60], 60.0)
    with pytest.raises(FeatureError):
        build_lagged(cols, ["a"], [90], 60.0)


def test_validity_categories_and_precedence() -> None:
    x, y = _latent(seed=4)
    model = fit_pls(x, y, _config(_tags(10), max_components=4))
    assert model.validity(x[:5]) == ["ok"] * 5
    rows = x[:4].copy()
    rows[0, 2] = np.nan
    rows[1, 5] = x[:, 5].max() + 10 * (x[:, 5].max() - x[:, 5].min())
    rows[2] = x[:, :].mean(0) + 0.0
    rows[2, 0], rows[2, 1] = x[:, 0].min(), x[:, 1].max()  # inside range, off the correlation
    got = model.validity(rows)
    assert got[0] == "missing_input" and got[1] == "out_of_range" and got[3] == "ok"
    assert got[2] == "extrapolation"
    both = rows[1].copy()
    both[0] = np.nan
    assert model.validity(both) == ["missing_input"]
    assert np.isnan(model.predict(both)).all()


def test_round_trip_and_stable_hash() -> None:
    x, y = _latent(seed=5)
    model = fit_pls(x, y, _config(_tags(10), max_components=5))
    doc = json.loads(json.dumps(model.to_dict()))
    again = PlsModel.from_dict(doc)
    assert np.array_equal(again.predict(x), model.predict(x))
    refit = fit_pls(x, y, _config(_tags(10), max_components=5))
    assert again.sha256() == model.sha256() == refit.sha256()
    assert again.validity(x[:20]) == model.validity(x[:20])
    with pytest.raises(PlsModelError):
        PlsModel.from_dict({"kind": "pca"})


def test_low_rank_selects_fewer_components() -> None:
    rng = np.random.default_rng(6)
    n = 800
    x = rng.normal(size=(n, 8))
    low = x[:, :1] @ np.ones((1, 1)) * 2 + 0.2 * rng.normal(size=(n, 1))
    y_low = low[:, 0]
    y_full = x @ np.arange(1, 9) + 0.2 * rng.normal(size=n)
    cfg = _config(_tags(8), max_components=8)
    assert fit_pls(x, y_low, cfg).chosen_components < fit_pls(x, y_full, cfg).chosen_components
    assert fit_pls(x, y_low, cfg).chosen_components <= 2


def test_errors_for_constant_column_and_too_few_rows() -> None:
    x, y = _latent(seed=7)
    xc = x.copy()
    xc[:, 4] = 3.0
    with pytest.raises(PlsModelError, match="c4"):
        fit_pls(xc, y, _config(_tags(10)))
    with pytest.raises(PlsModelError, match="too few"):
        fit_pls(x[:12], y[:12], _config(_tags(10)))
    ynan = y.copy()
    ynan[5:] = np.nan
    with pytest.raises(PlsModelError, match="too few"):
        fit_pls(x, ynan, _config(_tags(10)))


def test_nan_rows_dropped_and_lagged_fit_runs() -> None:
    rng = np.random.default_rng(8)
    n = 500
    cols = {"u": np.cumsum(rng.normal(size=n)), "v": rng.normal(size=n)}
    cfg = _config(("u", "v"), (0.0, 300.0, 900.0), max_components=4)
    x, _ = build_lagged(cols, cfg.input_tags, cfg.lags_s, 60.0)
    y = cols["u"] * 0.5 + cols["v"] + 0.1 * rng.normal(size=n)
    y[::4] = np.nan
    model = fit_pls(x, y, cfg)
    assert model.n_train < n and len(model.feature_names) == 6


def test_config_schema_agreement() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    from pathlib import Path

    path = Path(__file__).parents[2] / "schemas" / "softsensor.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    good = {
        "schema_version": "1.0.0", "id": "ss-1", "target_tag": "y",
        "input_tags": ["a", "b"], "mode": "advisory",
    }
    validator = jsonschema.Draft202012Validator(schema)
    cases = [
        (good, True),
        ({**good, "mode": "closed_loop"}, False),
        ({**good, "id": "bad id"}, False),
        ({**good, "schema_version": "1.0"}, False),
        ({**good, "lags_s": [0, -5]}, False),
        ({**good, "cv_blocks": 1}, False),
        ({**good, "input_tags": []}, False),
        ({**good, "extra": 1}, False),
        ({**good, "lags_s": [0, 300], "max_components": 4, "mode": "off"}, True),
    ]
    for doc, ok in cases:
        assert validator.is_valid(doc) is ok, doc
        try:
            load_config(doc)
            loaded = True
        except ValueError:
            loaded = False
        assert loaded is ok, doc
    assert load_config(good).lags_s == (0.0, 300.0, 900.0, 1800.0)


def test_x_domain_widens_validity_domain_from_sparse_labels() -> None:
    x, y = _latent(n=5000, seed=9)
    rng = np.random.default_rng(10)
    cfg = _config(_tags(10), max_components=4)
    sparse = np.full(len(y), np.nan)
    sparse[::83] = y[::83]
    assert np.isfinite(sparse).sum() == 61
    plain = fit_pls(x, sparse, cfg)
    wide = fit_pls(x, sparse, cfg, x_domain=x)
    assert wide.domain_rows == 5000 and "domain_rows" not in plain.to_dict()
    new = x[rng.integers(0, 5000, 2000)]
    ok_plain = np.mean([v == "ok" for v in plain.validity(new)])
    ok_wide = np.mean([v == "ok" for v in wide.validity(new)])
    assert ok_wide >= 0.95 and ok_plain < ok_wide
    far = x[:3].copy()
    far[:, 1] += 50 * (x[:, 1].max() - x[:, 1].min())
    assert wide.validity(far) == ["out_of_range"] * 3
    again = PlsModel.from_dict(json.loads(json.dumps(wide.to_dict())))
    assert again.domain_rows == 5000 and again.sha256() == wide.sha256()
