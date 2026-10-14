"""Tests for the PID (derivative action) parts of the tuning report.

They cover the AMIGO PID advice section and the vendor blocks that carry a derivative time.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import numpy as np

# The helpers live next to this package's tests, so we make that directory importable first.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crosscut_loops.tuning_pid import PidSettings, amigo_pid
from crosscut_loops.tuning_report import TuningReport, build_tuning_report, render_markdown
from crosscut_loops.tuning_rules import PiSettings
from crosscut_loops.vendor_forms import abb_pidcc_pid, siemens_pid_compact_pid, vendor_summaries
from test_identification import SimulationSettings, simulate_fopdt

GAIN = 2.0
TIME_CONSTANT_S = 30.0
DELAY_S = 8.0
SAMPLE_TIME_S = 1.0
PV_SPAN = 200.0
OUT_SPAN = 100.0
FLAT_SAMPLE_COUNT = 50
KC = 2.0
TI_S = 30.0
TD_S = 5.0
FILTER_RATIO_N = 10.0


def build_report_for_open_loop(
    pv_span: float | None = None,
    out_span: float = OUT_SPAN,
) -> TuningReport:
    """Build a report from the standard simulated process, with optional overrides."""
    u, y = simulate_fopdt(GAIN, TIME_CONSTANT_S, DELAY_S, SimulationSettings(seed=1))
    return build_tuning_report("FIC101", u, y, SAMPLE_TIME_S, pv_span=pv_span, out_span=out_span)


def build_report_for_flat_data() -> TuningReport:
    """Return a report for constant signals, which no model can explain."""
    u = np.zeros(FLAT_SAMPLE_COUNT)
    y = np.zeros(FLAT_SAMPLE_COUNT)
    return build_tuning_report("FIC101", u, y, SAMPLE_TIME_S)


def build_report_with_pid_advice() -> TuningReport:
    """Return the healthy report with a PID setting and advice attached by hand."""
    report = build_report_for_open_loop()
    pid = PidSettings(KC, TI_S, TD_S)
    return dataclasses.replace(report, pid=pid, pid_advice=(True, "derivative action pays off"))


def test_a_healthy_report_carries_a_pid_setting_and_an_advice_pair() -> None:
    report = build_report_for_open_loop()

    assert report.pid is not None
    assert isinstance(report.pid_advice[0], bool)
    assert isinstance(report.pid_advice[1], str)


def test_the_pid_setting_equals_the_amigo_pid_of_the_identified_model() -> None:
    report = build_report_for_open_loop()

    assert report.pid == amigo_pid(report.model)


def test_the_markdown_has_a_derivative_section_with_the_high_frequency_gain() -> None:
    markdown = render_markdown(build_report_with_pid_advice())

    assert "## PID (derivative action)" in markdown
    assert "Kc(1+N)" in markdown


def test_the_siemens_pid_tags_carry_the_derivative_time_and_its_filter() -> None:
    tags = siemens_pid_compact_pid(PidSettings(KC, TI_S, TD_S, FILTER_RATIO_N))

    assert tags["Retain.CtrlParams.Td"] == TD_S
    assert tags["Retain.CtrlParams.TdFiltRatio"] == 0.1
    assert tags["Retain.CtrlParams.DWeighting"] == 0.0
    assert tags["Retain.CtrlParams.Gain"] == KC


def test_the_abb_pid_tags_normalise_the_gain_and_filter_the_derivative() -> None:
    tags = abb_pidcc_pid(PidSettings(KC, TI_S, TD_S, FILTER_RATIO_N), pv_span=PV_SPAN)

    assert tags["Gain"] == KC * PV_SPAN / OUT_SPAN
    assert tags["TD"] == TD_S
    assert tags["TF"] == TD_S / FILTER_RATIO_N


def test_vendor_summaries_with_a_pid_setting_report_a_derivative_time() -> None:
    summaries = vendor_summaries(
        PiSettings(KC, TI_S), PV_SPAN, pid=PidSettings(KC, TI_S, TD_S)
    )

    assert summaries["siemens_pid_compact"]["tags"]["Retain.CtrlParams.Td"] == TD_S


def test_a_failed_identification_has_no_pid_and_no_derivative_section() -> None:
    report = build_report_for_flat_data()

    assert report.pid is None
    assert "## PID (derivative action)" not in render_markdown(report)
