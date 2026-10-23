"""Tests for the anomaly event scan on synthetic data (two latent factors, four tags).

Covers quiet data, a step shift with contribution check, short spikes, separated bursts,
open events, and the invariance of events under invalid (NaN / bad quality) rows.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_anomaly.config import AnomalyConfig, AnomalyConfigError
from crosscut_anomaly.detect import AnomalyEvent, scan
from crosscut_anomaly.pca_model import PcaModel, fit_pca

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
    return fit_pca(make_data(5000, 1), TAGS, alpha=0.999)


def times(n: int) -> np.ndarray:
    return np.arange(n) * 60.0


def shifted(model: PcaModel, n: int, onset: int, length: int, tag: int, sigma: float = 6.0):
    """Quiet record with a step shift of ``sigma`` standard deviations on one tag."""
    x = make_data(n, 11)
    x[onset : onset + length, tag] += sigma * model.scale[tag]
    return x


def spike_record(model: PcaModel, n: int, at: list[int]) -> np.ndarray:
    """Quiet record with single-sample 6 sigma spikes on tag d at the given rows."""
    x = make_data(n, 12)
    x[at, 3] += 6 * model.scale[3]
    return x


def test_quiet_data_has_few_events(model: PcaModel) -> None:
    res = scan(model, times(3000), make_data(3000, 5), None, CFG)
    assert len(res.events) <= 1
    assert res.n_valid == 3000 and res.n_skipped == 0
    assert res.skipped_reasons == {"nan": 0, "quality": 0}


def test_step_shift_gives_one_event_with_right_tag(model: PcaModel) -> None:
    x = shifted(model, 600, 200, 100, 0)
    res = scan(model, times(600), x, None, CFG)
    assert len(res.events) == 1
    ev = res.events[0]
    assert 200 <= ev.start_index <= 200 + CFG.min_consecutive
    assert ev.closed and ev.end_index <= 299
    assert ev.start_s == ev.start_index * 60.0
    assert "a" in (ev.top_spe_tags[0], ev.top_t2_tags[0])
    assert len(ev.top_spe_tags) == 3 and ev.exceeded in ("t2", "spe", "both")
    assert 200 <= ev.peak_index <= 299 and ev.n_samples >= CFG.min_consecutive


def test_short_spike_gives_no_event(model: PcaModel) -> None:
    res = scan(model, times(500), spike_record(model, 500, [100, 101, 102]), None, CFG)
    assert res.events == ()


def test_two_bursts_give_two_events(model: PcaModel) -> None:
    x = make_data(800, 13)
    for onset in (100, 400):
        x[onset : onset + 30, 3] += 6 * model.scale[3]
    res = scan(model, times(800), x, None, CFG)
    assert len(res.events) == 2
    assert res.events[0].closed and res.events[1].closed
    assert res.events[0].end_index < res.events[1].start_index


def test_gap_shorter_than_close_after_keeps_one_event(model: PcaModel) -> None:
    x = make_data(600, 14)
    x[100:130, 3] += 6 * model.scale[3]
    x[135:165, 3] += 6 * model.scale[3]
    res = scan(model, times(600), x, None, CFG)
    assert len(res.events) == 1
    assert res.events[0].end_index >= 160


def test_open_event_at_the_end(model: PcaModel) -> None:
    x = shifted(model, 300, 250, 50, 3)
    res = scan(model, times(300), x, None, CFG)
    assert len(res.events) == 1 and res.events[0].closed is False
    assert res.events[0].end_index == 299


def test_invalid_rows_inside_burst_do_not_split_or_extend(model: PcaModel) -> None:
    x = shifted(model, 600, 200, 100, 0)
    q = np.zeros(600)
    x[210, :] = np.nan
    x[220:240, 1] = np.nan
    q[250:262] = 4
    q[300:320] = 4  # after the burst: must not extend it
    res = scan(model, times(600), x, q, CFG)
    assert len(res.events) == 1
    assert res.events[0].end_index <= 299
    assert res.n_skipped == 1 + 20 + 12 + 20
    assert res.skipped_reasons == {"nan": 21, "quality": 32}


def test_events_equal_those_of_record_without_invalid_rows(model: PcaModel) -> None:
    x = make_data(900, 21)
    x[150:190, 3] += 6 * model.scale[3]
    x[500:520, 0] += 6 * model.scale[0]
    q = np.zeros(900)
    bad = np.r_[160:170, 505:510, 700:710]
    q[bad[:15]] = 1
    x[bad[15:], :] = np.nan
    res = scan(model, times(900), x, q, CFG)
    keep = np.ones(900, dtype=bool)
    keep[bad] = False
    ref = scan(model, times(900)[keep], x[keep], None, CFG)
    assert [fields(e) for e in res.events] == [fields(e) for e in ref.events]
    mapped = np.flatnonzero(keep)
    for e, r in zip(res.events, ref.events, strict=True):
        assert (e.start_index, e.end_index, e.peak_index) == tuple(
            int(mapped[i]) for i in (r.start_index, r.end_index, r.peak_index)
        )
        assert (e.start_s, e.end_s) == (mapped[r.start_index] * 60.0, mapped[r.end_index] * 60.0)


def fields(e: AnomalyEvent) -> tuple:
    """Event fields that must not depend on invalid rows (not the indices)."""
    return (e.closed, e.peak_t2, e.peak_spe, e.top_spe_tags, e.top_t2_tags, e.exceeded,
            e.n_samples)


def test_nan_and_quality_counted_once(model: PcaModel) -> None:
    x = make_data(100, 3)
    q = np.zeros(100)
    x[5, 0] = np.nan
    q[5] = 1  # both: counted as NaN only
    q[6] = 2
    res = scan(model, times(100), x, q, CFG)
    assert res.skipped_reasons == {"nan": 1, "quality": 1}
    assert res.n_skipped == 2 and res.n_valid == 98


def test_all_rows_invalid_gives_no_events(model: PcaModel) -> None:
    res = scan(model, times(10), make_data(10, 3), np.ones(10), CFG)
    assert res.events == () and res.n_valid == 0 and res.n_skipped == 10


def test_config_is_required(model: PcaModel) -> None:
    with pytest.raises(AnomalyConfigError, match="^config"):
        scan(model, times(10), make_data(10, 3))
