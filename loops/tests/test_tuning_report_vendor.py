"""Tests for the vendor parameter section of the tuning report.

The vendor section restates the identified PI settings in the tags of a real DCS block.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# The helper simulate_fopdt lives next to this package's tests, so we make that
# directory importable before importing it.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crosscut_loops.tuning_report import TuningReport, build_tuning_report, render_markdown
from test_identification import SimulationSettings, simulate_fopdt

GAIN = 2.0
TIME_CONSTANT_S = 30.0
DELAY_S = 8.0
SAMPLE_TIME_S = 1.0
PV_SPAN = 200.0
OUT_SPAN = 100.0
FLAT_SAMPLE_COUNT = 50
IDENTIFICATION_FAILURE_PREFIX = "model identification failed"


def build_report_for_open_loop(
    pv_span: float | None = None,
    out_span: float = OUT_SPAN,
    stiction_verdict: str | None = None,
) -> TuningReport:
    """Build a report from the standard simulated process, with optional overrides."""
    u, y = simulate_fopdt(GAIN, TIME_CONSTANT_S, DELAY_S, SimulationSettings(seed=1))
    return build_tuning_report(
        "FIC101",
        u,
        y,
        SAMPLE_TIME_S,
        stiction_verdict=stiction_verdict,
        pv_span=pv_span,
        out_span=out_span,
    )


def build_report_for_flat_data() -> TuningReport:
    """Return a report for constant signals, which no model can explain."""
    u = np.zeros(FLAT_SAMPLE_COUNT)
    y = np.zeros(FLAT_SAMPLE_COUNT)
    return build_tuning_report("FIC101", u, y, SAMPLE_TIME_S)


def test_a_healthy_loop_carries_the_two_vendor_blocks() -> None:
    report = build_report_for_open_loop()

    assert set(report.vendor_forms.keys()) == {"siemens_pid_compact", "abb_pidcc"}


def test_the_siemens_gain_and_integral_time_match_the_simc_settings() -> None:
    report = build_report_for_open_loop()

    assert report.simc is not None
    tags = report.vendor_forms["siemens_pid_compact"]["tags"]
    assert tags["Retain.CtrlParams.Gain"] == report.simc.kc
    assert tags["Retain.CtrlParams.Ti"] == report.simc.ti_s


def test_without_a_pv_span_the_abb_tags_are_empty_and_a_caveat_explains_why() -> None:
    report = build_report_for_open_loop(pv_span=None)

    abb = report.vendor_forms["abb_pidcc"]
    assert abb["tags"] == {}
    assert "PV range not given" in abb["caveats"][0]


def test_a_pv_span_of_200_units_doubles_the_abb_gain() -> None:
    report = build_report_for_open_loop(pv_span=PV_SPAN)

    assert report.simc is not None
    abb_gain = report.vendor_forms["abb_pidcc"]["tags"]["Gain"]
    assert abb_gain == pytest.approx(report.simc.kc * 2.0)


def test_markdown_shows_both_blocks_with_their_evidence_and_the_check_lines() -> None:
    markdown = render_markdown(build_report_for_open_loop(pv_span=PV_SPAN))

    assert "## Vendor blocks" in markdown
    assert "evidence: verified" in markdown
    assert "evidence: partly_verified" in markdown
    assert "CHECK:" in markdown


def test_a_failed_identification_has_no_vendor_section_in_the_markdown() -> None:
    report = build_report_for_flat_data()

    assert report.vendor_forms == {}
    assert "## Vendor blocks" not in render_markdown(report)


def test_a_stiction_blocked_loop_still_carries_its_vendor_forms() -> None:
    report = build_report_for_open_loop(stiction_verdict="stiction")

    assert report.blocked_reason is not None
    assert report.vendor_forms != {}
