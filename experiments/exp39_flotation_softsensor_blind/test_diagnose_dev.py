"""Test the development-only analyses on synthetic hourly frames (no data file needed).

The checks cover the sealed-span guard, ACF identity, lag correlation, baselines and grouping.
"""

import numpy as np
import pytest

pytest.importorskip("numpy")
import diagnose_dev as dd  # noqa: E402


def ar1(n=600, phi=0.8, seed=1):
    """Synthetic AR(1) target."""
    rng = np.random.default_rng(seed)
    y = np.zeros(n)
    for i in range(1, n):
        y[i] = phi * y[i - 1] + rng.normal()
    return y


def test_sealed_span_is_refused():
    """Arrays reaching the first sealed hour are rejected; development-length ones pass."""
    dd.assert_development_only(10, 10)
    with pytest.raises(ValueError, match="sealed span"):
        dd.assert_development_only(11, 10)


def test_acf_matches_persistence_identity():
    """For a stationary AR(1) the measured persistence MSE equals 2 s2 (1 - rho)."""
    rows = dd.acf_table(ar1(), 5)
    assert rows[0]["rho"] == pytest.approx(0.8, abs=0.08)
    assert all(abs(r["ratio"] - 1) < 0.05 for r in rows)


def test_acf_skips_missing_pairs():
    """NaN hours reduce the pair count instead of breaking the statistic."""
    y = ar1(100)
    y[10] = np.nan
    assert dd.acf_table(y, 1)[0]["n"] == 97


def test_lag_xcorr_peaks_at_the_true_delay():
    """A tag that leads the target by 3 h correlates best at lag 3."""
    x = np.random.default_rng(2).normal(size=500)
    y = np.r_[np.zeros(3), x[:-3]]
    corr = dd.lag_xcorr(x, y)
    assert int(np.argmax(corr)) == 3
    assert dd.lag_xcorr(x, y, difference=True)[3] == pytest.approx(1.0)


def test_known_lab_applies_delay_and_carries_forward():
    """Lab of hour h-2 is the newest known at h; gaps carry the last value."""
    y = np.array([1.0, np.nan, 3.0, np.nan, np.nan, 6.0])
    out = dd.known_lab(y, 2)
    assert np.isnan(out[0]) and np.isnan(out[1])
    assert out[2] == 1.0 and out[4] == 3.0 and out[5] == 3.0


def test_common_rows_and_rmse():
    """Masks keep only rows finite in every array; RMSE is over that mask."""
    a, b = np.array([1.0, np.nan, 3.0]), np.array([1.0, 2.0, 5.0])
    mask = dd.common_rows(a, b)
    assert mask.tolist() == [True, False, True]
    assert dd.rmse_on(a, b, mask) == pytest.approx(np.sqrt(2.0))


def test_monthly_bias_groups_by_calendar_month():
    """Residual mean, RMSE and count are reported per month label."""
    months = dd.month_keys(np.datetime64("2017-03-31T23:00:00"), 3)
    assert months.tolist() == ["2017-03", "2017-04", "2017-04"]
    rows = dd.monthly_bias(np.array([1.0, 2.0, np.nan]), months)
    assert rows == [("2017-03", 1.0, 1.0, 1), ("2017-04", 2.0, 2.0, 1)]


def test_groups_partition_the_19_inputs():
    """Ablation groups cover every input tag exactly once."""
    pytest.importorskip("pyarrow")
    import exp39

    tags = [t for g in dd.GROUPS.values() for t in g]
    assert sorted(tags) == sorted(exp39.INPUTS)


def test_ablation_reports_drop_and_only_per_group():
    """A synthetic frame yields all/drop/only scores on the identical row mask."""
    pytest.importorskip("pyarrow")
    import exp39

    rng = np.random.default_rng(3)
    n = 300
    x = {t: rng.normal(size=n) for t in exp39.INPUTS}
    y = 2 * x["Starch Flow"] + 0.1 * rng.normal(size=n)
    split = 240
    mask = np.arange(n) >= split
    out = dd.ablation(x, y, split, mask)
    assert len(out) == 9
    assert out["drop reagents"][0] > 3 * out["all"][0]
    assert out["only reagents"][1] == 2
