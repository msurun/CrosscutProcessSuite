"""Tests for the per-loop report and its classification, incl. a simulator run with a fault."""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.monitor import LoopSettings, analyze_loop
from crosscut_sim.core import AUTO, MAN, Scenario
from crosscut_sim.faults import Fault, FaultyPlant
from crosscut_sim.plants.wood_berry import REFLUX, TOP, TOP_MODE, TOP_SP, WoodBerryPlant

DT = 10.0
SAMPLE_COUNT = 2160  # 6 h
RNG = np.random.default_rng(3)
SETTINGS = LoopSettings(delay_s=DT, ultimate_period_s=600.0, amplitude_limit=0.2)


def signals(
    error: np.ndarray, out: float | np.ndarray = 50.0, mode: int = AUTO
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build the time, setpoint, measurement, output and mode signals of a simulation run."""
    time_signal = np.arange(SAMPLE_COUNT) * DT
    setpoint_signal = np.full(SAMPLE_COUNT, 10.0)
    return (
        time_signal,
        setpoint_signal + error,
        setpoint_signal,
        np.broadcast_to(out, SAMPLE_COUNT).copy(),
        np.full(SAMPLE_COUNT, mode),
    )


def test_healthy_loop_is_classified_ok() -> None:
    report = analyze_loop(*signals(RNG.normal(scale=0.05, size=SAMPLE_COUNT)), settings=SETTINGS)
    assert report.classification == "ok"
    assert report.service_factor == pytest.approx(1.0)
    assert report.harris_index == pytest.approx(1.0, abs=0.15)


def test_loop_in_manual_is_classified_manual() -> None:
    report = analyze_loop(
        *signals(RNG.normal(scale=0.05, size=SAMPLE_COUNT), mode=MAN), settings=SETTINGS
    )
    assert report.classification == "manual" and report.service_factor == 0.0


def test_loop_with_output_at_the_limit_is_classified_saturated() -> None:
    out = np.where(np.arange(SAMPLE_COUNT) < SAMPLE_COUNT // 2, 100.0, 50.0)
    report = analyze_loop(
        *signals(RNG.normal(scale=0.05, size=SAMPLE_COUNT), out=out), settings=SETTINGS
    )
    assert report.classification == "saturated"
    assert report.saturation_fraction == pytest.approx(0.5)


def test_oscillating_loop_is_classified_oscillating_with_its_period() -> None:
    time_s = np.arange(SAMPLE_COUNT) * DT
    error = np.sin(2 * np.pi * time_s / 600.0) + RNG.normal(scale=0.05, size=SAMPLE_COUNT)
    report = analyze_loop(*signals(error), settings=SETTINGS)
    assert report.classification == "oscillating"
    assert report.oscillation_period_s == pytest.approx(600.0, rel=0.05)


def test_sluggish_loop_is_classified_poor_performance() -> None:
    error = np.zeros(SAMPLE_COUNT)
    for k in range(1, SAMPLE_COUNT):
        error[k] = 0.98 * error[k - 1] + RNG.normal(scale=0.05)
    report = analyze_loop(*signals(error), settings=SETTINGS)
    assert report.classification == "poor_performance"
    assert report.harris_index < 0.3


def test_mode_changes_and_mean_error_are_reported() -> None:
    time_s, process_variable, setpoint, controller_output, mode = signals(
        np.full(SAMPLE_COUNT, 0.5)
    )
    mode[1000:1100] = MAN
    report = analyze_loop(
        time_s, process_variable, setpoint, controller_output, mode, settings=SETTINGS
    )
    assert report.mode_changes == 2
    assert report.mean_abs_error == pytest.approx(0.5)


def _simulate_frozen_top_sensor() -> tuple[np.ndarray, ...]:
    """Run the Wood-Berry plant for 3 h with its top sensor frozen during the second hour."""
    plant = FaultyPlant(WoodBerryPlant(), [Fault("freeze", TOP, start_s=3600.0, end_s=7200.0)])
    plant.reset(11, Scenario(duration_s=3 * 3600.0))
    rows = []
    for _ in range(3 * 3600):
        rows.append(
            [plant.time_s] + [plant.read(tag)[0] for tag in (TOP, TOP_SP, REFLUX, TOP_MODE)]
        )
        plant.step()
    return tuple(np.array(rows).T)


def test_simulated_loop_with_a_frozen_sensor_reports_the_flatline() -> None:
    signals_of_run = _simulate_frozen_top_sensor()
    report = analyze_loop(
        *signals_of_run,
        settings=LoopSettings(
            delay_s=60.0,
            ultimate_period_s=600.0,
            amplitude_limit=0.5,
            out_low=-100.0,
            out_high=100.0,
        ),
    )
    assert report.flatline_fraction == pytest.approx(1 / 3, abs=0.02)
    assert any(
        "frozen" in finding.lower() or "flatline" in finding.lower() for finding in report.findings
    )
