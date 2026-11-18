"""Synthetic regression checks for measurement-aware monitoring.

Seeded signals exercise amplitude references and saturation policy without experiment data.
"""

import numpy as np
import pytest
from crosscut_loops.monitor import LoopReport, LoopSettings, analyze_loop
from crosscut_loops.oscillation_acf import acf_regularity, oscillation_reference

SAMPLE_COUNT = 3000  # equally spaced samples, one second apart
PERIOD_S = 60.0


def make_report(
    error: np.ndarray, saturated_share: float = 0.0, known_limits: bool = False,
) -> LoopReport:
    """Analyse an AUTO signal with a controlled share of output at its upper limit."""
    time_s = np.arange(SAMPLE_COUNT, dtype=float)
    output = np.full(SAMPLE_COUNT, 50.0)
    output[:round(SAMPLE_COUNT * saturated_share)] = 100.0
    known = frozenset({"out_range", "oscillation_limits"} if known_limits else {"out_range"})
    settings = LoopSettings(1.0, PERIOD_S, 0.01, known=known)
    return analyze_loop(time_s, error, np.zeros(SAMPLE_COUNT), output,
                        np.ones(SAMPLE_COUNT), settings=settings)


def test_a_low_amplitude_regular_cycle_is_rejected_against_noise() -> None:
    """A statistically regular component below three sensor-noise sigmas is withheld."""
    noise = np.random.default_rng(1).normal(size=SAMPLE_COUNT)
    error = 0.3 * np.sin(2.0 * np.pi * np.arange(SAMPLE_COUNT) / PERIOD_S) + noise

    report = make_report(error)

    assert report.oscillation_period_s is None
    assert report.oscillation_evidence["amplitude"] < 3 * report.oscillation_evidence["noise_sigma"]


def test_a_significant_cycle_reports_its_measurement_references() -> None:
    """A cycle well above sensor noise retains its period and numerical evidence."""
    noise = np.random.default_rng(2).normal(scale=0.05, size=SAMPLE_COUNT)
    error = np.sin(2.0 * np.pi * np.arange(SAMPLE_COUNT) / PERIOD_S) + noise

    report = make_report(error)

    assert report.classification == "oscillating"
    assert report.oscillation_period_s == pytest.approx(PERIOD_S, rel=0.05)
    assert report.oscillation_evidence["noise_sigma"] == pytest.approx(0.05, abs=0.01)
    evidence = report.oscillation_evidence
    assert evidence["amplitude"] > evidence["amplitude_threshold"]


@pytest.mark.parametrize("known_limits", [False, True])
def test_a_two_level_quantised_cycle_is_rejected_by_both_monitor_methods(
    known_limits: bool,
) -> None:
    """Resolution-sized cycling is insufficient even when its period is perfectly regular."""
    phase = np.random.default_rng(3).uniform(0.1, 0.2)
    error = 0.4 * (np.sin(2.0 * np.pi * np.arange(SAMPLE_COUNT) / PERIOD_S + phase) > 0)

    report = make_report(error, known_limits=known_limits)

    assert report.oscillation_period_s is None
    assert report.oscillation_evidence["quantisation_step"] == pytest.approx(0.4)


def test_acf_accepts_the_same_reference_used_by_the_monitor() -> None:
    """The ACF significance gate is enforced when a measurement reference is supplied."""
    error = 0.3 * np.sin(2.0 * np.pi * np.arange(SAMPLE_COUNT) / PERIOD_S)
    error += np.random.default_rng(1).normal(size=SAMPLE_COUNT)

    result = acf_regularity(error, 1.0, reference=oscillation_reference(error, error))

    assert result.regular is False
    assert result.reason == "amplitude below reference"


@pytest.mark.parametrize("share, level", [(0.09, "ok"), (0.1, "warning"),
                                         (0.17, "warning"), (0.21, "fault")])
def test_saturation_has_an_advisory_level_before_the_existing_fault(
    share: float, level: str,
) -> None:
    """Ten percent warns; the retained twenty-percent fault still takes priority."""
    error = np.random.default_rng(4).normal(scale=0.05, size=SAMPLE_COUNT)

    report = make_report(error, saturated_share=share)

    assert report.saturation_level == level
    assert (report.classification == "saturated") == (level == "fault")
    has_warning = "warning: output at its limit" in str(report.findings)
    assert has_warning == (level == "warning")
