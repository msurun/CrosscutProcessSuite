"""Tests of the "noise driven valve" check: detection, finding, status and worklist advice.

The check flags a valve that travels and reverses a lot while the loop shows no regular cycle:
measurement noise is then moving the valve, not a disturbance. The tests pin the thresholds, the
finding parameters (rounded whole numbers) and the place of its advice in the worklist order.
"""

from __future__ import annotations

from dataclasses import replace

from crosscut_loops.monitor import LoopReport, LoopSettings
from crosscut_loops.overview import (
    NOISE_DRIVEN_CODE,
    WARNING_LEVEL,
    Finding,
    findings_of,
    is_noise_driven,
    status_level,
)
from crosscut_loops.worklist import (
    ASK_WHY_MANUAL,
    CHECK_MEASUREMENT,
    REVIEW_NOISE_RESPONSE,
    VALVE_TEST,
    next_action,
)

NOISE_TRAVEL_PER_H = 190.0  # a level loop on real data: far above the noise travel limit
NOISE_REVERSALS_PER_H = 70.0  # and far above the reversal limit
FLOW_TRAVEL_PER_H = 20.0  # a flow loop's ordinary travel: below the limit
LOW_REVERSALS_PER_H = 5.0  # a slowly wandering valve: below the reversal limit

SETTINGS = LoopSettings(delay_s=30.0, ultimate_period_s=600.0, amplitude_limit=1.0)


def _base_report(**overrides: object) -> LoopReport:
    """A healthy, fully assessed report; tests change only the field they are about."""
    base = LoopReport(
        n_samples=1000,
        service_factor=1.0,
        saturation_fraction=0.0,
        flatline_fraction=0.0,
        mode_changes=0,
        mean_abs_error=0.5,
        error_std=0.6,
        harris_index=0.9,
        oscillation_period_s=None,
        classification="ok",
        findings=[],
        valve_travel_per_h=NOISE_TRAVEL_PER_H,
        valve_reversals_per_h=NOISE_REVERSALS_PER_H,
    )
    return replace(base, **overrides)


# --- is_noise_driven: the four thresholds ------------------------------------


def test_high_travel_and_high_reversals_is_noise_driven():
    report = _base_report()
    assert is_noise_driven(report) is True


def test_low_travel_is_not_noise_driven():
    report = _base_report(valve_travel_per_h=FLOW_TRAVEL_PER_H)
    assert is_noise_driven(report) is False


def test_low_reversals_is_not_noise_driven():
    report = _base_report(valve_reversals_per_h=LOW_REVERSALS_PER_H)
    assert is_noise_driven(report) is False


def test_unknown_travel_is_not_noise_driven():
    report = _base_report(valve_travel_per_h=None)
    assert is_noise_driven(report) is False


def test_an_oscillating_loop_is_not_noise_driven():
    report = _base_report(classification="oscillating")
    assert is_noise_driven(report) is False


def test_a_manual_loop_is_not_noise_driven():
    report = _base_report(classification="manual")
    assert is_noise_driven(report) is False


# --- findings_of: one finding with rounded parameters ------------------------


def _rounds_to_whole_numbers(value: float) -> bool:
    """True when the value is a whole number, so a JSON consumer can print it as-is."""
    return float(value).is_integer()


def test_findings_of_reports_noise_driven_with_whole_numbers():
    report = _base_report(valve_travel_per_h=190.4, valve_reversals_per_h=70.6)

    findings = findings_of(report, SETTINGS)

    noise = [finding for finding in findings if finding.code == NOISE_DRIVEN_CODE]
    assert len(noise) == 1
    assert noise[0] == Finding(NOISE_DRIVEN_CODE, {"travel": 190, "reversals": 71})
    assert _rounds_to_whole_numbers(noise[0].params["travel"])


def test_a_clean_loop_has_no_noise_driven_finding():
    report = _base_report(valve_travel_per_h=FLOW_TRAVEL_PER_H)

    findings = findings_of(report, SETTINGS)

    assert all(finding.code != NOISE_DRIVEN_CODE for finding in findings)


# --- status_level: warning, even when conclusions were withheld --------------


def test_noise_driven_loop_is_a_warning():
    report = _base_report(not_assessed=("saturation", "valve_kpis"))
    assert status_level(report, SETTINGS) == WARNING_LEVEL


def test_a_healthy_assessed_loop_is_ok():
    report = _base_report(valve_travel_per_h=FLOW_TRAVEL_PER_H)
    assert status_level(report, SETTINGS) == "ok"


# --- worklist: the noise advice and its place in the rule order --------------


def _row_with_noise_finding(**overrides: object) -> dict[str, object]:
    """A worklist row whose findings list carries the noise-driven finding."""
    row: dict[str, object] = {
        "classification": "ok",
        "status": "warning",
        "findings": [{"code": NOISE_DRIVEN_CODE, "params": {"travel": 190, "reversals": 70}}],
        "valve_travel_per_h": 190.4,
        "valve_reversals_per_h": 70.6,
        "stiction_advice": "not_checked",
        "same_period_as": [],
        "not_assessed": [],
        "out_quantisation_ratio": None,
        "valve_sizing_hint": None,
    }
    row.update(overrides)
    return row


def test_a_noise_driven_row_asks_to_review_the_noise_response():
    action = next_action(_row_with_noise_finding())
    assert action == {
        "code": REVIEW_NOISE_RESPONSE,
        "params": {"travel": 190, "reversals": 71},
    }


def test_a_manual_row_still_asks_why_manual_first():
    row = _row_with_noise_finding(classification="manual")
    assert next_action(row)["code"] == ASK_WHY_MANUAL


def test_a_flatlined_row_still_checks_the_measurement_first():
    row = _row_with_noise_finding(findings=[{"code": "flatline", "params": {}}])
    assert next_action(row)["code"] == CHECK_MEASUREMENT


def test_an_oscillating_row_with_stiction_still_tests_the_valve_first():
    row = _row_with_noise_finding(
        classification="oscillating",
        stiction_advice="test_valve",
        same_period_as=[],
    )
    assert next_action(row)["code"] == VALVE_TEST


def test_a_poor_performance_row_with_noise_finding_checks_the_noise_before_retuning():
    row = _row_with_noise_finding(classification="poor_performance")
    assert next_action(row)["code"] == REVIEW_NOISE_RESPONSE
