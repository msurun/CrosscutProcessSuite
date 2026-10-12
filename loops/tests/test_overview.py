"""Tests for loop discovery, findings, status and health (part 1 of the overview module)."""

from typing import Any

import numpy as np
import pytest
from crosscut_loops.monitor import LoopReport, LoopSettings
from crosscut_loops.overview import (
    Finding,
    LoopTags,
    default_settings,
    discover_loops,
    findings_of,
    health_percent,
    status_level,
)

PV_ID = "sim.mc.hpgr_press"


def tag(tag_id: str, role: str, unit: str | None = None) -> dict[str, Any]:
    """Build one raw tag mapping as it arrives from the tag database."""
    return {"id": tag_id, "role": role, "unit": unit, "eng_min": 0.0, "eng_max": 6.0}


def make_tags(names: list[str]) -> list[dict[str, Any]]:
    """Build a complete tag set (PV, _sp, _out, _mode) for each loop name."""
    rows: list[dict[str, Any]] = []
    for name in names:
        rows.extend(
            [
                tag(name, "PV", unit="bar"),
                tag(f"{name}_sp", "SP"),
                tag(f"{name}_out", "OUT"),
                tag(f"{name}_mode", "MODE"),
            ]
        )
    return rows


def make_report(**overrides: Any) -> LoopReport:
    """Build a LoopReport with harmless defaults, overridden by keyword arguments."""
    values: dict[str, Any] = {
        "n_samples": 1000,
        "service_factor": 1.0,
        "saturation_fraction": 0.0,
        "flatline_fraction": 0.0,
        "mode_changes": 0,
        "mean_abs_error": 0.1,
        "error_std": 0.1,
        "harris_index": 1.0,
        "oscillation_period_s": 0.0,
        "classification": "ok",
        "findings": [],
        "stiction_verdict": "none",
    }
    values.update(overrides)
    return LoopReport(**values)  # type: ignore[arg-type]


def make_settings() -> LoopSettings:
    """Build the shared LoopSettings used by every test."""
    return LoopSettings(delay_s=30, ultimate_period_s=600, amplitude_limit=0.5)


def test_three_complete_loops_are_found_in_input_order():
    tags = make_tags(["a.press", "b.flow", "c.level"])

    loops = discover_loops(tags)

    assert [loop.name for loop in loops] == ["press", "flow", "level"]
    assert [loop.pv for loop in loops] == ["a.press", "b.flow", "c.level"]


def test_a_pv_without_its_mode_tag_is_skipped():
    tags = [row for row in make_tags(["a.press"]) if row["id"] != "a.press_mode"]

    assert discover_loops(tags) == []


def test_an_rsp_tag_is_ignored():
    tags = make_tags(["a.press"]) + [tag("a.press_rsp", "RSP")]

    loops = discover_loops(tags)

    assert len(loops) == 1
    assert loops[0].pv == "a.press"


def test_the_name_is_the_part_after_the_last_dot():
    tags = make_tags([PV_ID])

    assert discover_loops(tags)[0].name == "hpgr_press"


def test_an_empty_input_yields_no_loops():
    assert discover_loops([]) == []


def test_a_missing_unit_becomes_an_empty_string():
    tags = make_tags(["a.press"])
    for row in tags:
        row["unit"] = None

    assert discover_loops(tags)[0].unit == ""


def test_a_flatline_finding_reports_the_fraction_as_a_percentage():
    report = make_report(flatline_fraction=0.42)

    assert findings_of(report, make_settings()) == [Finding("flatline", {"percent": 42.0})]


def test_a_manual_loop_reports_the_manual_percentage():
    report = make_report(classification="manual", service_factor=0.25)

    assert findings_of(report, make_settings()) == [Finding("manual", {"percent": 75.0})]


def test_a_saturated_loop_reports_the_saturation_percentage():
    report = make_report(classification="saturated", saturation_fraction=0.8)

    assert findings_of(report, make_settings()) == [Finding("saturated", {"percent": 80.0})]


def test_an_oscillating_loop_reports_the_period_in_minutes():
    report = make_report(classification="oscillating", oscillation_period_s=90.0)

    assert findings_of(report, make_settings()) == [Finding("oscillating", {"minutes": 1.5})]


def test_a_poor_performance_loop_has_one_finding_without_parameters():
    report = make_report(classification="poor_performance")

    assert findings_of(report, make_settings()) == [Finding("poorPerformance", {})]


def test_an_ok_loop_has_no_classification_finding():
    assert findings_of(make_report(), make_settings()) == []


def test_stiction_adds_a_finding_after_the_others():
    report = make_report(classification="oscillating", stiction_verdict="stiction")

    codes = [finding.code for finding in findings_of(report, make_settings())]

    assert codes == ["oscillating", "stiction"]


@pytest.mark.parametrize(
    "classification",
    ["manual", "saturated", "oscillating", "poor_performance", "ok"],
)
def test_findings_are_ordered_flatline_first(classification):
    report = make_report(classification=classification, flatline_fraction=0.9)

    assert findings_of(report, make_settings())[0].code == "flatline"


def test_a_manual_loop_has_no_health_value():
    assert health_percent(make_report(classification="manual")) is None


def test_a_perfect_loop_is_at_one_hundred_percent():
    assert health_percent(make_report()) == 100


def test_a_zero_harris_index_costs_sixty_percent_of_the_score():
    assert health_percent(make_report(harris_index=0.0)) == 40


def test_a_nan_harris_index_counts_as_one_half():
    assert health_percent(make_report(harris_index=np.nan)) == 70


def test_an_oscillating_loop_is_penalised_by_thirty_percent():
    report = make_report(classification="oscillating")

    assert health_percent(report) == 70


def test_a_stiction_verdict_costs_forty_percent_of_the_score():
    report = make_report(stiction_verdict="stiction")

    assert health_percent(report) == 60


@pytest.mark.parametrize(
    "harris_index, service_factor, saturation_fraction, flatline_fraction",
    [
        (7.0, 1.0, 0.0, 0.0),
        (-1.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0, 1.0),
        (np.nan, 0.5, 0.9, 0.9),
    ],
)
def test_health_stays_between_zero_and_one_hundred(
    harris_index, service_factor, saturation_fraction, flatline_fraction
):
    report = make_report(
        harris_index=harris_index,
        service_factor=service_factor,
        saturation_fraction=saturation_fraction,
        flatline_fraction=flatline_fraction,
    )

    assert 0 <= health_percent(report) <= 100


@pytest.mark.parametrize(
    "classification, stiction_verdict, flatline_fraction, expected",
    [
        ("manual", "none", 0.0, "unused"),
        ("ok", "stiction", 0.0, "problem"),
        ("ok", "none", 0.9, "problem"),
        ("saturated", "none", 0.0, "warning"),
        ("oscillating", "none", 0.0, "warning"),
        ("poor_performance", "none", 0.0, "warning"),
        ("ok", "none", 0.0, "ok"),
    ],
)
def test_status_level_follows_the_priority_order(
    classification, stiction_verdict, flatline_fraction, expected
):
    report = make_report(
        classification=classification,
        stiction_verdict=stiction_verdict,
        flatline_fraction=flatline_fraction,
    )

    assert status_level(report, make_settings()) == expected


def test_default_amplitude_is_two_percent_of_the_engineering_range():
    loop = LoopTags(
        name="press",
        pv=PV_ID,
        sp=f"{PV_ID}_sp",
        out=f"{PV_ID}_out",
        mode=f"{PV_ID}_mode",
        unit="bar",
        eng_min=0.0,
        eng_max=6.0,
    )

    assert default_settings(loop).amplitude_limit == pytest.approx(0.12)


def test_default_amplitude_is_one_when_the_range_is_unknown():
    loop = LoopTags(
        name="press",
        pv=PV_ID,
        sp=f"{PV_ID}_sp",
        out=f"{PV_ID}_out",
        mode=f"{PV_ID}_mode",
        unit="bar",
        eng_min=None,
        eng_max=None,
    )

    assert default_settings(loop).amplitude_limit == 1.0


def test_default_settings_keep_the_standard_timing_values():
    loop = LoopTags(
        name="press",
        pv=PV_ID,
        sp=f"{PV_ID}_sp",
        out=f"{PV_ID}_out",
        mode=f"{PV_ID}_mode",
        unit="bar",
        eng_min=0.0,
        eng_max=6.0,
    )

    settings = default_settings(loop)

    assert settings.delay_s == 30.0
    assert settings.ultimate_period_s == 600.0


def test_stiction_without_a_sustained_oscillation_raises_no_alarm():
    report = make_report(stiction_verdict="stiction", oscillation_period_s=None)
    assert "stiction" not in [finding.code for finding in findings_of(report, make_settings())]
    assert status_level(report, make_settings()) == "ok"
    assert health_percent(report) == 100


def test_stiction_with_a_sustained_oscillation_makes_the_loop_a_problem():
    """A stiction verdict with a sustained oscillation is flagged as a problem finding."""
    report = make_report(stiction_verdict="stiction", oscillation_period_s=600.0)
    finding_codes = [finding.code for finding in findings_of(report, make_settings())]
    assert "stiction" in finding_codes
    assert status_level(report, make_settings()) == "problem"


def test_finding_percentages_are_whole_numbers():
    report = make_report(classification="saturated", saturation_fraction=0.3611)
    saturation_findings = [
        finding for finding in findings_of(report, make_settings()) if finding.code == "saturated"
    ]
    assert saturation_findings[0].params == {"percent": 36.0}


def test_stiction_is_not_reported_when_saturation_explains_the_cycle():
    """A cycle caused by valve saturation must not raise a stiction finding."""
    report = make_report(
        stiction_verdict="stiction",
        oscillation_period_s=600.0,
        classification="saturated",
        saturation_fraction=0.4,
    )
    finding_codes = [finding.code for finding in findings_of(report, make_settings())]
    assert "stiction" not in finding_codes
