"""Tests for the valve KPI fields that analyze_loop adds to LoopReport.

Covers valve travel, reversals, OUT quantisation and sizing hints: the normal
case, coarse quantisation, oversized and undersized valves, and records with
too few samples in AUTO (or no sample at all).
"""

import numpy as np
from crosscut_loops.monitor import LoopSettings, analyze_loop
from crosscut_sim.core import AUTO, MAN

SAMPLE_COUNT = 3000
SAMPLE_INTERVAL_S = 1.0
SETPOINT = 50.0
PV_NOISE_SD = 0.2
OUT_WALK_NOISE_SD = 0.05
OUT_WAVE_AMPLITUDE = 0.5
OUT_WAVE_PERIOD_S = 400.0
QUANTISATION_STEP = 5.0
QUANTISED_OUT_NOISE_SD = 1.5
AUTO_SAMPLE_COUNT = 30


def _settings() -> LoopSettings:
    """Return the loop settings shared by every test in this module."""
    return LoopSettings(delay_s=5.0, ultimate_period_s=100.0, amplitude_limit=1.0)


def _time_axis() -> np.ndarray:
    """Return sample times in seconds, one sample per second."""
    return np.arange(SAMPLE_COUNT) * SAMPLE_INTERVAL_S


def _noise(standard_deviation: float) -> np.ndarray:
    """Return Gaussian noise with the given standard deviation, seeded for determinism."""
    rng = np.random.default_rng(0)
    return rng.normal(0.0, standard_deviation, SAMPLE_COUNT)


def _modes(mode_value: float) -> np.ndarray:
    """Return a mode array with the same value in every sample."""
    return np.full(SAMPLE_COUNT, mode_value)


def _smooth_out(t_s: np.ndarray) -> np.ndarray:
    """Return a slow sine wave around 50 percent with a little noise."""
    wave = OUT_WAVE_AMPLITUDE * np.sin(2.0 * np.pi * t_s / OUT_WAVE_PERIOD_S)
    return SETPOINT + wave + _noise(OUT_WALK_NOISE_SD)


def _normal_out(t_s: np.ndarray) -> np.ndarray:
    """Return OUT for the normal record: a slow wave with fine-grained noise."""
    return _smooth_out(t_s)


def _normal_pv() -> np.ndarray:
    """Return PV sitting on the setpoint with mild measurement noise."""
    return SETPOINT + _noise(PV_NOISE_SD)


def _run(out: np.ndarray, mode: np.ndarray) -> object:
    """Analyze a record with fixed SP/PV and the given OUT and mode arrays."""
    t_s = _time_axis()
    return analyze_loop(
        t_s, _normal_pv(), np.full(SAMPLE_COUNT, SETPOINT), out, mode, settings=_settings()
    )


def _findings_starting_with(findings: list[str], prefix: str) -> list[str]:
    """Return the findings that begin with the given prefix."""
    return [finding for finding in findings if finding.startswith(prefix)]


def test_normal_record_reports_sensible_valve_kpis():
    """A smooth OUT drives the valve, so travel is positive and reversals are counted."""
    report = _run(_normal_out(_time_axis()), _modes(AUTO))

    assert np.isfinite(report.valve_travel_per_h)
    assert report.valve_travel_per_h > 0.0
    assert report.valve_reversals_per_h >= 0.0


def test_normal_record_has_no_sizing_or_quantisation_findings():
    """A valve moving over a mid-range of OUT is neither oversized nor coarse."""
    report = _run(_normal_out(_time_axis()), _modes(AUTO))

    assert report.valve_sizing_hint is None
    assert _findings_starting_with(report.findings, "quantisation") == []
    assert _findings_starting_with(report.findings, "valve ") == []


def test_quantised_out_flags_a_quantisation_finding():
    """When OUT moves in steps of 5 units, the ratio reaches 1 and a finding appears."""
    walk = SETPOINT + np.cumsum(_noise(QUANTISED_OUT_NOISE_SD))
    out = np.round(walk / QUANTISATION_STEP) * QUANTISATION_STEP

    report = _run(out, _modes(AUTO))

    assert report.out_quantisation_ratio >= 1.0
    assert _findings_starting_with(report.findings, "quantisation:") != []


def test_low_median_out_flags_an_oversized_valve():
    """A valve that sits near 8 percent is too big for the load it serves."""
    out = np.full(SAMPLE_COUNT, 8.0) + _noise(OUT_WALK_NOISE_SD)

    report = _run(out, _modes(AUTO))

    assert report.valve_sizing_hint == "oversized"
    assert _findings_starting_with(report.findings, "valve oversized:") != []


def test_high_median_out_flags_an_undersized_valve():
    """A valve that sits near 92 percent is too small for the load it serves."""
    out = np.full(SAMPLE_COUNT, 92.0) + _noise(OUT_WALK_NOISE_SD)

    report = _run(out, _modes(AUTO))

    assert report.valve_sizing_hint == "undersized"
    assert _findings_starting_with(report.findings, "valve undersized:") != []


def test_too_few_auto_samples_returns_no_valve_kpis():
    """With only 30 samples in AUTO the KPIs cannot be trusted, so they are None."""
    mode = _modes(MAN)
    mode[:AUTO_SAMPLE_COUNT] = AUTO

    report = _run(_normal_out(_time_axis()), mode)

    assert report.valve_travel_per_h is None
    assert report.valve_reversals_per_h is None
    assert report.out_quantisation_ratio is None
    assert report.valve_sizing_hint is None


def test_all_manual_record_returns_no_valve_kpis_without_raising():
    """A loop left in MAN has no AUTO samples and is reported rather than rejected."""
    report = _run(_normal_out(_time_axis()), _modes(MAN))

    assert report.valve_travel_per_h is None
    assert report.valve_reversals_per_h is None
    assert report.out_quantisation_ratio is None
    assert report.valve_sizing_hint is None
