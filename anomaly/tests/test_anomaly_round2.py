"""Tests for the round 2 additions: dynamic PCA (lagged tags) and the stuck-sensor rule.

Covers round 1 invariance (defaults), augment_lags, model round trip, lag-aware validity,
the stuck rule (named tag, >= 3 moving others, invalid rows), config and schema keys, and an
honest synthetic comparison of static and dynamic PCA on an autocorrelated record.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import jsonschema
import numpy as np
import pytest
from crosscut_anomaly.config import AnomalyConfig, AnomalyConfigError, load_config
from crosscut_anomaly.detect import scan
from crosscut_anomaly.pca_model import PcaModel, augment_lags, fit_pca, lagged_tags

TAGS = ("a", "b", "c", "d")
MIX = np.array([[1.0, 0.0], [0.8, 0.5], [0.0, 1.0], [0.4, -0.9]])
CFG = AnomalyConfig(schema_version="1.0.0", id="t", tags=TAGS, mode="advisory", alpha=0.999)
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "schemas" / "anomaly.schema.json").read_text("utf-8")
)
GOOD: dict[str, Any] = {
    "schema_version": "1.0.0", "id": "x", "tags": ["a", "b", "c"], "mode": "off",
}


def make_data(n: int, seed: int) -> np.ndarray:
    """Four tags from two latent factors plus small noise."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal((n, 2)) @ MIX.T + 0.1 * rng.standard_normal((n, 4))


def times(n: int) -> np.ndarray:
    return np.arange(n) * 60.0


@pytest.fixture(scope="module")
def model() -> PcaModel:
    return fit_pca(make_data(5000, 1), TAGS, alpha=0.999)


def test_round1_behaviour_unchanged_against_stored_result(model: PcaModel) -> None:
    x = make_data(600, 11)
    x[200:300, 0] += 6 * model.scale[0]
    x[400:405, 2] = np.nan
    quality = np.zeros(600)
    quality[450:460] = 1
    res = scan(model, times(600), x, quality, CFG)
    assert (res.n_valid, res.n_skipped) == (585, 15)
    assert res.skipped_reasons == {"nan": 5, "quality": 10}
    assert len(res.events) == 1
    ev = res.events[0]
    assert (ev.start_index, ev.end_index, ev.closed, ev.peak_index, ev.n_samples) == (
        200, 299, True, 245, 100)
    assert ev.peak_t2 == pytest.approx(13.147798255, rel=1e-6)
    assert ev.peak_spe == pytest.approx(20.530599685, rel=1e-6)
    assert (ev.top_spe_tags, ev.top_t2_tags, ev.exceeded) == (
        ("a", "b", "d"), ("a", "d", "c"), "both")
    assert (ev.kind, ev.stuck_tag) == ("pca", None) and res.n_stuck_events == 0
    assert res.n_pca_events == 1


def test_augment_lags_hand_example() -> None:
    x = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0], [4.0, 40.0]])
    out = augment_lags(x, 2)
    assert out.shape == (4, 6)
    assert np.isnan(out[:2]).all()
    np.testing.assert_array_equal(out[2], [3.0, 30.0, 2.0, 20.0, 1.0, 10.0])
    np.testing.assert_array_equal(out[3], [4.0, 40.0, 3.0, 30.0, 2.0, 20.0])
    np.testing.assert_array_equal(augment_lags(x, 0), x)
    assert lagged_tags(("a", "b"), 1) == ("a@0", "b@0", "a@1", "b@1")


def test_nan_source_row_invalidates_all_rows_using_it() -> None:
    x = np.arange(20.0).reshape(10, 2)
    x[4, 1] = np.nan
    bad = np.flatnonzero(np.isnan(augment_lags(x, 2)).any(axis=1))
    assert bad.tolist() == [0, 1, 4, 5, 6]


def test_dynamic_model_roundtrip_and_old_dict_compat(model: PcaModel) -> None:
    dyn = fit_pca(make_data(3000, 2), TAGS, 0.9, 0.99, dynamic_lags=2)
    assert dyn.dynamic_lags == 2 and dyn.base_tags == TAGS
    assert dyn.tags == lagged_tags(TAGS, 2) and len(dyn.mean) == 12
    back = PcaModel.from_dict(json.loads(json.dumps(dyn.to_dict())))
    assert back.dynamic_lags == 2 and back.base_tags == TAGS and back.tags == dyn.tags
    assert back.sha256() == dyn.sha256()
    old = model.to_dict()
    assert "dynamic_lags" not in old and "base_tags" not in old
    loaded = PcaModel.from_dict(old)
    assert loaded.dynamic_lags == 0 and loaded.monitored_tags == TAGS


def test_dynamic_contributions_are_per_base_tag() -> None:
    dyn = fit_pca(make_data(3000, 2), TAGS, 0.9, 0.99, dynamic_lags=2)
    x = make_data(50, 3)
    x[10:, 0] += 6 * dyn.scale[0]
    row = augment_lags(x, 2)[30:31]
    contrib = dyn.contributions(row)
    assert list(contrib["spe"]) == list(TAGS) and list(contrib["t2"]) == list(TAGS)
    assert sum(contrib["spe"].values()) == pytest.approx(1.0)
    assert max(contrib["t2"], key=contrib["t2"].get) in ("a", "b", "d")  # type: ignore[arg-type]


def test_quality_and_nan_propagate_through_lags() -> None:
    dyn = fit_pca(make_data(3000, 2), TAGS, 0.9, 0.99, dynamic_lags=2)
    cfg = replace(CFG, dynamic_lags=2)
    x = make_data(300, 5)
    x[200, 1] = np.nan
    quality = np.zeros(300)
    quality[100] = 1
    res = scan(dyn, times(300), x, quality, cfg)
    assert res.skipped_reasons == {"nan": 1, "quality": 1, "lag": 2 + 2 + 2}
    assert res.n_valid == 300 - 2 - 3 - 3 and res.n_skipped == 300 - res.n_valid


def frozen_record(start: int, stop: int, tags: tuple[int, ...] = (1,)) -> np.ndarray:
    """Quiet record with the given tag columns frozen at their value at ``start``."""
    x = make_data(600, 21)
    for j in tags:
        x[start:stop, j] = x[start, j]
    return x


def test_frozen_tag_found_by_stuck_rule_not_by_static_pca(model: PcaModel) -> None:
    x = frozen_record(300, 340)
    plain = scan(model, times(600), x, None, replace(CFG, min_consecutive=45))
    assert plain.events == ()
    res = scan(model, times(600), x, None, replace(CFG, min_consecutive=45, stuck_samples=15))
    assert res.n_stuck_events == 1 and res.n_pca_events == 0
    ev = res.events[0]
    assert ev.kind == "stuck" and ev.stuck_tag == "b" and ev.top_spe_tags == ("b",)
    assert (ev.start_index, ev.end_index, ev.n_samples, ev.closed) == (300, 339, 40, True)
    assert ev.start_s == 300 * 60.0


def test_short_run_open_run_and_off_switch(model: PcaModel) -> None:
    cfg = replace(CFG, stuck_samples=15, min_consecutive=45)
    assert scan(model, times(600), frozen_record(300, 314), None, cfg).events == ()
    assert scan(model, times(600), frozen_record(300, 600), None, CFG).n_stuck_events == 0
    res = scan(model, times(600), frozen_record(560, 600), None, cfg)
    stuck = [e for e in res.events if e.kind == "stuck"]
    assert len(stuck) == 1 and stuck[0].closed is False and stuck[0].end_index == 599


def test_constant_tag_needs_three_moving_others(model: PcaModel) -> None:
    cfg = replace(CFG, stuck_samples=15, min_consecutive=45)
    two_frozen = frozen_record(300, 340, tags=(1, 2))
    assert [e for e in scan(model, times(600), two_frozen, None, cfg).events
            if e.kind == "stuck"] == []
    one_frozen = scan(model, times(600), frozen_record(300, 340), None, cfg)
    assert one_frozen.n_stuck_events == 1


def test_invalid_rows_neither_extend_nor_break_a_stuck_run(model: PcaModel) -> None:
    x = frozen_record(300, 340)
    x[310:313, 0] = np.nan
    x[320:323, 1] = 999.0
    quality = np.zeros(600)
    quality[320:323] = 1
    quality[345:350] = 1
    x[345:350, 1] = -5.0
    cfg = replace(CFG, stuck_samples=15, min_consecutive=45)
    stuck = [e for e in scan(model, times(600), x, quality, cfg).events if e.kind == "stuck"]
    assert len(stuck) == 1
    assert (stuck[0].start_index, stuck[0].end_index) == (300, 339)
    assert stuck[0].n_samples == 40 - 3 - 3
    x2 = frozen_record(300, 340)
    x2[320, 1] += 0.5
    broken = [e for e in scan(model, times(600), x2, None, cfg).events if e.kind == "stuck"]
    assert [(e.start_index, e.end_index) for e in broken] == [(300, 319), (321, 339)]


def test_events_of_both_kinds_sorted_and_counted() -> None:
    dyn = fit_pca(make_data(5000, 1), TAGS, 0.9, 0.999, dynamic_lags=2)
    cfg = replace(CFG, dynamic_lags=2, stuck_samples=15)
    x = frozen_record(200, 240)
    x[400:500, 0] += 6 * dyn.scale[0]
    res = scan(dyn, times(600), x, None, cfg)
    starts = [e.start_index for e in res.events]
    assert starts == sorted(starts)
    assert res.n_stuck_events == 1 and res.n_pca_events >= 1
    assert any(e.kind == "pca" and 400 <= e.start_index <= 410 for e in res.events)


def ar_record(n: int, seed: int, transient: tuple[int, int] | None = None) -> np.ndarray:
    """8 tags, 3 latent AR(1) factors (phi 0.95) with per-tag delays 0..2 plus noise."""
    rng = np.random.default_rng(seed)
    e = rng.standard_normal((n, 3)) * np.sqrt(1 - 0.95**2)
    z = np.zeros((n, 3))
    for i in range(1, n):
        z[i] = 0.95 * z[i - 1] + e[i]
    if transient:
        start, length = transient
        ramp = np.exp(-np.arange(length) / 6.0) * np.minimum(np.arange(length) / 2.0, 1) * 4
        z[start : start + length, 0] += ramp
        z[start : start + length, 1] -= ramp
    mix = np.random.default_rng(99)
    w, delay = mix.standard_normal((3, 8)), mix.integers(0, 3, (3, 8))
    x = sum(w[i] * np.roll(z[:, [i]], delay[i], axis=0) for i in range(3))
    return np.asarray(x + 0.05 * rng.standard_normal((n, 8)))


def test_dynamic_vs_static_pca_on_autocorrelated_transient() -> None:
    """Honest comparison: the DPCA false-alarm reduction could NOT be shown here.

    On this synthetic set (delays 0..2 samples between tags, a ramp-and-decay transient in
    two latent factors) the transient mostly moves inside the PCA subspace, so both models
    flag it; dynamic PCA with 2 lags gave slightly MORE event samples in exploration
    (142 vs 119 over 12 records). The test only guards that dynamic PCA runs end to end,
    has few event samples on quiet data and still sees the transient.
    """
    tags = tuple(f"t{i}" for i in range(8))
    samples = {}
    for lags in (0, 2):
        mdl = fit_pca(ar_record(6000, 1), tags, 0.9, 0.99, dynamic_lags=lags)
        cfg = AnomalyConfig(schema_version="1.0.0", id="t", tags=tags, mode="advisory",
                            dynamic_lags=lags)
        quiet = scan(mdl, times(3000), ar_record(3000, 2), None, cfg)
        assert sum(e.n_samples for e in quiet.events) <= 60  # of 3000 quiet samples
        hit = scan(mdl, times(600), ar_record(600, 3, (300, 60)), None, cfg)
        samples[lags] = sum(e.n_samples for e in hit.events)
    assert samples[0] > 0 and samples[2] > 0


@pytest.mark.parametrize(("key", "value"), [
    ("dynamic_lags", 11), ("dynamic_lags", -1), ("dynamic_lags", 2.5), ("dynamic_lags", True),
    ("stuck_samples", 1), ("stuck_samples", 2), ("stuck_samples", -3), ("stuck_samples", 3.5),
])
def test_bad_new_keys_rejected_by_loader_and_schema(key: str, value: Any) -> None:
    doc = {**GOOD, key: value}
    with pytest.raises(AnomalyConfigError, match=key):
        load_config(doc)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)


@pytest.mark.parametrize(("lags", "stuck"), [(0, 0), (2, 15), (10, 3)])
def test_good_new_keys_accepted(lags: int, stuck: int) -> None:
    doc = {**GOOD, "dynamic_lags": lags, "stuck_samples": stuck}
    jsonschema.validate(doc, SCHEMA)
    cfg = load_config(doc)
    assert (cfg.dynamic_lags, cfg.stuck_samples) == (lags, stuck)
    assert (load_config(GOOD).dynamic_lags, load_config(GOOD).stuck_samples) == (0, 0)


def test_static_limits_and_sha_are_bit_identical_to_before() -> None:
    cases = {
        0.99: (9.22252065837847, 0.09358820827743504,
               "76b0d8d4cbedbe034730861b7e9898d39cadc51d1a373170b36d3c90dadcb140"),
        0.999: (13.840158144677385, 0.14350959439108266,
                "f484b58276c58036bd7b3563cef0575c78c05985c631cadf32105534f3532d81"),
    }
    for alpha, (t2, spe, sha) in cases.items():
        mdl = fit_pca(make_data(5000, 1), TAGS, 0.9, alpha)
        assert mdl.spe_limit_method == "jackson_mudholkar"
        assert (mdl.t2_limit, mdl.spe_limit, mdl.sha256()) == (t2, spe, sha)


def ar_filtered(n: int, seed: int) -> np.ndarray:
    """8 tags from 3 AR(1) latents, each tag a first-order lag (tau 1..6) of its mix."""
    rng = np.random.default_rng(seed)
    e = rng.standard_normal((n, 3)) * np.sqrt(1 - 0.95**2)
    z = np.zeros((n, 3))
    for i in range(1, n):
        z[i] = 0.95 * z[i - 1] + e[i]
    w = np.random.default_rng(99).standard_normal((3, 8))
    tau = np.array([1, 1, 1, 1.5, 3, 3, 6, 6])
    u, y = z @ w, np.zeros((n, 8))
    for i in range(1, n):
        y[i] = y[i - 1] + (u[i] - y[i - 1]) / tau
    return np.asarray(y + 0.1 * rng.standard_normal((n, 8)))


def test_degenerate_jm_falls_back_to_empirical_limit() -> None:
    tags = tuple(f"t{i}" for i in range(8))
    mdl = fit_pca(ar_filtered(6000, 1), tags, 0.9, 0.99, dynamic_lags=2)
    assert mdl.spe_limit_method == "empirical"
    fresh = augment_lags(ar_filtered(6000, 2), 2)[2:]
    rate = float(np.mean(mdl.spe(fresh) > mdl.spe_limit))
    assert 0.005 <= rate <= 0.02
    cfg = AnomalyConfig(schema_version="1.0.0", id="t", tags=tags, mode="advisory",
                        dynamic_lags=2)
    res = scan(mdl, times(3000), ar_filtered(3000, 2), None, cfg)
    assert res.limit_methods == {"t2": "hotelling_f", "spe": "empirical"}
    assert sum(e.n_samples for e in res.events) < 300


def test_limit_method_round_trip_and_old_dicts() -> None:
    tags = tuple(f"t{i}" for i in range(8))
    mdl = fit_pca(ar_filtered(6000, 1), tags, 0.9, 0.99, dynamic_lags=2)
    back = PcaModel.from_dict(json.loads(json.dumps(mdl.to_dict())))
    assert back.spe_limit_method == "empirical" and back.spe_limit == mdl.spe_limit
    old = mdl.to_dict()
    del old["spe_limit_method"]
    assert PcaModel.from_dict(old).spe_limit_method == "jackson_mudholkar"


def held_data(n: int, seed: int) -> np.ndarray:
    """Quiet data where tag c is a signal updated only every 30 samples (legitimately held)."""
    x = make_data(n, seed)
    x[:, 2] = np.repeat(x[::30, 2], 30)[:n]
    return x


def test_held_tag_is_not_stuck_but_a_long_freeze_is() -> None:
    mdl = fit_pca(held_data(5000, 1), TAGS, 0.9, 0.999, stuck_samples=15)
    assert mdl.stuck_runs[2] == 30 and max(mdl.stuck_runs[0], mdl.stuck_runs[1]) < 5
    cfg = replace(CFG, stuck_samples=15, min_consecutive=1000)
    quiet = scan(mdl, times(3000), held_data(3000, 2), None, cfg)
    assert quiet.n_stuck_events == 0
    x = held_data(600, 3)
    x[320:380, 1] = x[320, 1]
    x[100:160, 2] = x[100, 2]
    res = scan(mdl, times(600), x, None, cfg)
    assert sorted((e.stuck_tag, e.start_index) for e in res.events) == [("b", 320), ("c", 90)]
    plain = fit_pca(held_data(5000, 1), TAGS, 0.9, 0.999)
    assert plain.stuck_runs == ()
    assert scan(plain, times(3000), held_data(3000, 2), None, cfg).n_stuck_events > 0


def test_stuck_runs_round_trip_and_old_model_fallback() -> None:
    mdl = fit_pca(held_data(5000, 1), TAGS, 0.9, 0.999, stuck_samples=15)
    back = PcaModel.from_dict(json.loads(json.dumps(mdl.to_dict())))
    assert back.stuck_runs == mdl.stuck_runs
    old = mdl.to_dict()
    del old["stuck_runs"]
    assert PcaModel.from_dict(old).stuck_runs == ()
    assert "stuck_runs" not in fit_pca(held_data(5000, 1), TAGS).to_dict()


def test_lag_history_breaks_at_a_time_gap_and_matches_masking() -> None:
    dyn = fit_pca(make_data(5000, 1), TAGS, 0.9, 0.999, dynamic_lags=2)
    cfg = replace(CFG, dynamic_lags=2, min_consecutive=1)
    x = np.vstack([make_data(300, 5), make_data(300, 6) + 4.0])
    t = times(600)
    keep = np.ones(600, dtype=bool)
    keep[300 - 60 : 300] = False
    mask = np.where(keep[:, None], x, np.nan)
    full = scan(dyn, t, mask, None, cfg)
    red = scan(dyn, t[keep], x[keep], None, cfg)
    assert red.skipped_reasons["lag"] == 2 + 2
    assert full.skipped_reasons["lag"] == 2 + 2
    key = lambda r: [(e.start_s, e.end_s, e.n_samples, e.closed, e.peak_t2) for e in r.events]  # noqa: E731
    assert key(full) == key(red)
    gap_s, after_s = t[239], t[300]
    assert not any(e.start_s <= gap_s < e.end_s and e.end_s >= after_s for e in red.events)
    assert not any(e.start_s in (after_s, t[301]) for e in red.events)
    shifted_t = t[keep].copy()
    shifted_t[240:] += 3600.0
    assert scan(dyn, shifted_t, x[keep], None, cfg).skipped_reasons["lag"] == 2 + 2
