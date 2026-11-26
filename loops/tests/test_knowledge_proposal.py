"""Verify evidence-backed knowledge proposals on synthetic loop histories.

The analytical records keep gains, delays and slopes independently known.
"""

import numpy as np
import pytest
from crosscut_loops.knowledge_proposal import propose_knowledge


def _manual_record() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return a unit-sampled FOPDT response with gain 2, lag 30 s and delay 8 s."""
    time_s = np.arange(600.0)
    output = np.where(time_s >= 120, 60.0, 50.0)
    # A held step gives y = K du (1-exp(-(t-theta)/tau)) after its transport delay.
    elapsed_s = np.maximum(time_s - 128, 0)
    process_value = 20 + 20 * (1 - np.exp(-elapsed_s / 30))
    return time_s, process_value, output


def test_a_manual_step_proposes_the_known_dead_time() -> None:
    """A manual step proposes the known dead time."""
    time_s, process_value, output = _manual_record()
    result = propose_knowledge(time_s, process_value, process_value * 0, output,
                               np.zeros(time_s.size), {})
    assert result["delay_s"]["value"] == pytest.approx(8, abs=2)
    assert result["delay_s"]["evidence"]["kind"] == "manual_out_step"
    assert result["needs_step_test"] is False
    assert result["ultimate_period_s"]["value"] > 0


def test_an_integrating_step_proposes_an_integrating_process() -> None:
    """An integrating step proposes an integrating process."""
    time_s = np.arange(1000.0)
    output = np.where(time_s >= 250, 60.0, 50.0)
    process_value = 10 + 0.02 * np.maximum(time_s - 260, 0)
    result = propose_knowledge(time_s, process_value, np.zeros(1000), output,
                               np.zeros(1000), {})
    assert result["process_kind"]["value"] == "integrating"
    assert result["delay_s"]["value"] == pytest.approx(10, abs=2)


def test_a_flat_record_requests_a_step_test() -> None:
    """A flat record requests a step test."""
    time_s = np.arange(200.0)
    result = propose_knowledge(time_s, np.ones(200), np.ones(200), np.ones(200),
                               np.zeros(200), {})
    assert result["needs_step_test"] is True
    assert result["delay_s"]["value"] is None
    assert result["process_kind"]["confidence"] == "low"


def test_metadata_ranges_take_priority_over_observations() -> None:
    """Metadata ranges take priority over observations."""
    time_s, process_value, output = _manual_record()
    metadata = {"pv": {"eng_min": 0, "eng_max": 100},
                "out": {"eng_min": 0, "eng_max": 100}, "vendor": "abb"}
    result = propose_knowledge(time_s, process_value, process_value, output,
                               np.zeros(600), metadata)
    assert result["pv_eng_max"]["value"] == 100
    assert result["pv_eng_max"]["confidence"] == "high"
    assert result["amplitude_limit"]["value"] == 2
    assert "confirm" in result["amplitude_limit"]["evidence"]["detail"]


def test_a_constant_output_ramp_suggests_integration_without_inventing_a_delay() -> None:
    """A constant output ramp suggests integration without inventing a delay."""
    time_s = np.arange(200.0)
    result = propose_knowledge(time_s, 10 + time_s * 0.1, np.zeros(200), np.ones(200),
                               np.zeros(200), {})
    assert result["process_kind"]["value"] == "integrating"
    assert result["delay_s"]["value"] is None
    assert result["needs_step_test"] is True


def test_a_sustained_cycle_proposes_its_measured_period() -> None:
    """A sustained cycle proposes its measured period."""
    time_s = np.arange(2000.0)
    process_value = np.sin(2 * np.pi * time_s / 40)
    result = propose_knowledge(time_s, process_value, np.zeros(2000), np.ones(2000),
                               np.ones(2000), {})
    assert result["ultimate_period_s"]["value"] == pytest.approx(40, rel=0.05)
    assert result["ultimate_period_s"]["confidence"] == "low"


def test_mismatched_samples_raise_a_helpful_error() -> None:
    """Mismatched samples raise a helpful error."""
    with pytest.raises(ValueError, match="equal"):
        propose_knowledge(np.arange(100.0), np.ones(99), np.ones(100), np.ones(100),
                          np.zeros(100), {})
