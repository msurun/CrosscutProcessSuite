"""Tests for the readiness check of a historian export.

Each test describes one behaviour a customer-facing report must have: what makes an export
unusable, what is only a warning, and what the message tells the user to fix.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.overview import LoopTags
from crosscut_loops.readiness import FAIL, WARN, ReadinessReport, check_readiness

# A clean export has 30 h of data with a 10 s sample period: the smallest record that passes.
CLEAN_DURATION_S = 30 * 3600.0
CLEAN_PERIOD_S = 10.0
NOISE_SCALE = 0.05  # small noise so no tag looks stuck


def _clean_export() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Timestamps and four noisy PV/SP/OUT/MODE series, all sharing the same time base."""
    t_s = np.arange(0.0, CLEAN_DURATION_S, CLEAN_PERIOD_S)
    rng = np.random.default_rng(0)
    columns = {
        name: 50.0 + rng.normal(scale=NOISE_SCALE, size=t_s.size)
        for name in ("pv", "sp", "out", "mode")
    }
    return t_s, columns


def _loop() -> LoopTags:
    """The loop under test: all four roles named, engineering range 0..100 %."""
    return LoopTags("L1", "pv", "sp", "out", "mode", "%", 0.0, 100.0)


def _find(report: ReadinessReport, name: str):
    """The single check with the given name; fails the test when it is missing."""
    matches = [check for check in report.checks if check.name == name]
    assert matches, f"No check named {name!r} in {[check.name for check in report.checks]}"
    return matches[0]


def test_a_clean_30_hour_10_second_export_is_ready_with_no_warnings():
    """The happy path: the export the customer should send passes without complaint."""
    t_s, columns = _clean_export()

    report = check_readiness(t_s, columns, [_loop()])

    assert report.ready
    assert report.warnings() == []


def test_a_3_hour_record_fails_on_duration():
    """Three hours are too few oscillation cycles, so the report must fail."""
    t_s, columns = _clean_export()
    short_t_s = t_s[t_s <= 3 * 3600.0]

    report = check_readiness(short_t_s, columns, [_loop()])

    assert _find(report, "duration").status == FAIL
    assert not report.ready


def test_a_12_hour_record_warns_on_duration_but_is_ready():
    """Twelve hours are usable but not ideal: a warning that does not block the analysis."""
    t_s, columns = _clean_export()
    half_day_t_s = t_s[t_s <= 12 * 3600.0]

    report = check_readiness(half_day_t_s, columns, [_loop()])

    assert _find(report, "duration").status == WARN
    assert report.ready


def test_30_second_sampling_warns_about_hiding_stiction():
    """A 30 s period still works, but the message must say why it is risky."""
    t_s, columns = _clean_export()
    coarse_t_s = t_s[::3]
    coarse_columns = {name: values[::3] for name, values in columns.items()}

    report = check_readiness(coarse_t_s, coarse_columns, [_loop()])

    period_check = _find(report, "sample_period")
    assert period_check.status == WARN
    assert "stiction" in period_check.message


def test_120_second_sampling_fails_on_sample_period():
    """Two minutes between samples are too coarse for loop analysis."""
    t_s, columns = _clean_export()
    coarse_t_s = t_s[::12]
    coarse_columns = {name: values[::12] for name, values in columns.items()}

    report = check_readiness(coarse_t_s, coarse_columns, [_loop()])

    assert _find(report, "sample_period").status == FAIL


def test_timestamps_that_are_not_strictly_increasing_fail_on_time_order():
    """A repeated or backwards timestamp breaks every later calculation."""
    t_s, columns = _clean_export()
    t_s[10] = t_s[9]

    report = check_readiness(t_s, columns, [_loop()])

    assert _find(report, "time_order").status == FAIL


def test_a_tag_missing_from_the_columns_fails_with_the_loop_tag_name():
    """The customer named a PV tag that the export does not contain."""
    t_s, columns = _clean_export()
    del columns["pv"]

    report = check_readiness(t_s, columns, [_loop()])

    missing_check = _find(report, "tags:L1")
    assert missing_check.status == FAIL
    assert "pv" in missing_check.message


def test_20_percent_missing_values_in_pv_warns():
    """One fifth of the PV samples gone is worth a warning but is still workable."""
    t_s, columns = _clean_export()
    columns["pv"][: columns["pv"].size // 5] = np.nan

    report = check_readiness(t_s, columns, [_loop()])

    assert _find(report, "missing:pv").status == WARN


def test_50_percent_missing_values_in_pv_fails():
    """Half of the PV samples gone leaves nothing to analyse."""
    t_s, columns = _clean_export()
    columns["pv"][: columns["pv"].size // 2] = np.nan

    report = check_readiness(t_s, columns, [_loop()])

    assert _find(report, "missing:pv").status == FAIL


def test_a_pv_that_is_constant_for_the_whole_record_fails_as_flat():
    """A frozen PV never moves, so no oscillation can be detected."""
    t_s, columns = _clean_export()
    columns["pv"] = np.full(t_s.size, 42.0)

    report = check_readiness(t_s, columns, [_loop()])

    assert _find(report, "flat:pv").status == FAIL


def test_a_loop_without_out_and_mode_warns_but_stays_ready():
    """Stiction and manual findings need OUT and MODE, but the loop can still be analysed."""
    t_s, columns = _clean_export()
    loop_without_outputs = LoopTags("L1", "pv", "sp", "", "", "%", 0.0, 100.0)

    report = check_readiness(t_s, columns, [loop_without_outputs])

    assert _find(report, "tags:L1").status == WARN
    assert report.ready


def test_a_loop_without_an_sp_fails():
    """Without a setpoint there is nothing to compare the PV against."""
    t_s, columns = _clean_export()
    loop_without_sp = LoopTags("L1", "pv", "", "out", "mode", "%", 0.0, 100.0)

    report = check_readiness(t_s, columns, [loop_without_sp])

    assert _find(report, "tags:L1").status == FAIL


@pytest.mark.parametrize("export", ["clean", "broken"])
def test_ready_is_false_exactly_when_failures_are_non_empty(export):
    """`ready` is only a shortcut for "no failures"; the two must never disagree."""
    t_s, columns = _clean_export()
    if export == "broken":
        del columns["pv"]

    report = check_readiness(t_s, columns, [_loop()])

    assert report.ready == (report.failures() == [])


def test_fewer_than_two_samples_gives_a_failing_report_and_no_exception():
    """A one-row export is a user mistake, so it must come back as a readable failure."""
    columns = {"pv": np.array([1.0]), "sp": np.array([1.0])}

    report = check_readiness(np.array([0.0]), columns, [_loop()])

    assert _find(report, "duration").status == FAIL
    assert not report.ready
