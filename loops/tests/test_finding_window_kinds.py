"""Behaviour tests for the window_kind field of findings from analyze_dataset.

Every finding that points at a stretch of the record (window_s) must say what that
stretch means: "cause" when the stretch is the evidence, "example" when it is only
one representative occurrence of a record-wide problem.
"""

import numpy as np
import pytest
from crosscut_loops.overview import LoopTags, analyze_dataset

# --- Constants describing the synthetic loops used across the tests ----------

SAMPLE_INTERVAL_S = 1.0
LONG_SAMPLE_COUNT = 4000
OSCILLATING_SAMPLE_COUNT = 6000
RANDOM_SEED = 0
NOISE_SCALE = 0.1

PV_BASE = 50.0
SP_BASE = 50.0
OUT_BASE = 40.0

MODE_AUTO = 1

# Upper bound of the controller output range; OUT stuck here means saturated.
OUT_FULL_SCALE = 100.0

SATURATION_FINDING_CODE = "saturated"
OSCILLATING_FINDING_CODE = "oscillating"
VALID_WINDOW_KINDS = {"cause", "example"}


# --- Arrangement helpers ----------------------------------------------------


def _make_time_vector(sample_count: int) -> np.ndarray:
    """Return a time vector of sample_count seconds with one sample per second."""
    return np.arange(sample_count, dtype=float) * SAMPLE_INTERVAL_S


def _make_loop_tags(name: str) -> LoopTags:
    """Return tags mapping the synthetic columns PV, SP, OUT and MODE."""
    return LoopTags(
        name=name,
        pv="PV",
        sp="SP",
        out="OUT",
        mode="MODE",
        unit="degC",
        eng_min=0.0,
        eng_max=100.0,
        # Configured per-loop knowledge (the former placeholders), so every check is assessed.
        delay_s=30.0,
        ultimate_period_s=600.0,
        out_low=0.0,
        out_high=100.0,
    )


def _make_mode_column(sample_count: int) -> np.ndarray:
    """Return a constant AUTO mode column."""
    return np.full(sample_count, MODE_AUTO)


def _make_saturated_columns(time_vector: np.ndarray) -> dict[str, np.ndarray]:
    """Return a stuck loop: OUT clamped at full scale while PV drifts below SP."""
    sample_count = time_vector.size
    return {
        "PV": np.linspace(SP_BASE - 10.0, SP_BASE - 5.0, sample_count),
        "SP": np.full(sample_count, SP_BASE),
        "OUT": np.full(sample_count, OUT_FULL_SCALE),
        "MODE": _make_mode_column(sample_count),
    }


def _make_oscillating_columns(
    time_vector: np.ndarray, amplitude: float, period_s: float
) -> dict[str, np.ndarray]:
    """Return a cycling loop: PV swings around SP with OUT following in phase."""
    noise = np.random.default_rng(RANDOM_SEED)
    sample_count = time_vector.size
    phase = 2.0 * np.pi * time_vector / period_s
    return {
        "PV": PV_BASE + amplitude * np.sin(phase) + NOISE_SCALE * noise.standard_normal(
            sample_count
        ),
        "SP": np.full(sample_count, SP_BASE),
        "OUT": OUT_BASE + amplitude * np.sin(phase) + NOISE_SCALE * noise.standard_normal(
            sample_count
        ),
        "MODE": _make_mode_column(sample_count),
    }


def _make_healthy_columns(time_vector: np.ndarray) -> dict[str, np.ndarray]:
    """Return a healthy loop: PV and OUT jitter around fixed values, SP constant."""
    noise = np.random.default_rng(RANDOM_SEED)
    sample_count = time_vector.size
    return {
        "PV": PV_BASE + NOISE_SCALE * noise.standard_normal(sample_count),
        "SP": np.full(sample_count, SP_BASE),
        "OUT": OUT_BASE + NOISE_SCALE * noise.standard_normal(sample_count),
        "MODE": _make_mode_column(sample_count),
    }


def _findings_with_code(findings: list[dict], code: str) -> list[dict]:
    """Return the findings whose code matches, in report order."""
    return [finding for finding in findings if finding["code"] == code]


# --- Tests ------------------------------------------------------------------


def test_a_saturated_stretch_is_flagged_with_a_cause_window():
    """The saturated stretch is the evidence itself, so its kind is 'cause'."""
    time_vector = _make_time_vector(LONG_SAMPLE_COUNT)
    columns = _make_saturated_columns(time_vector)
    tags = _make_loop_tags(name="stuck loop")

    [result] = analyze_dataset(time_vector, columns, [tags])

    [saturated] = _findings_with_code(result["findings"], SATURATION_FINDING_CODE)
    assert saturated["window_kind"] == "cause"


def test_an_oscillating_loop_reports_an_example_window():
    """A record-wide oscillation is illustrated by one stretch: kind 'example'."""
    time_vector = _make_time_vector(OSCILLATING_SAMPLE_COUNT)
    columns = _make_oscillating_columns(time_vector, amplitude=10.0, period_s=300.0)
    tags = _make_loop_tags(name="cycling loop")

    [result] = analyze_dataset(time_vector, columns, [tags])

    [oscillating] = _findings_with_code(result["findings"], OSCILLATING_FINDING_CODE)
    assert oscillating["window_kind"] == "example"


def test_the_example_window_is_an_ordered_interval_inside_the_record():
    """The example window must be a real time span: start < end, both within the record."""
    time_vector = _make_time_vector(OSCILLATING_SAMPLE_COUNT)
    columns = _make_oscillating_columns(time_vector, amplitude=10.0, period_s=300.0)
    tags = _make_loop_tags(name="cycling loop")

    [result] = analyze_dataset(time_vector, columns, [tags])

    [oscillating] = _findings_with_code(result["findings"], OSCILLATING_FINDING_CODE)
    start_s, end_s = oscillating["window_s"]
    assert start_s < end_s
    assert 0.0 <= start_s
    assert end_s <= time_vector[-1]


@pytest.mark.parametrize(
    "column_factory",
    [
        _make_saturated_columns,
        lambda t: _make_oscillating_columns(t, amplitude=10.0, period_s=300.0),
    ],
)
def test_every_windowed_finding_declares_a_known_window_kind(column_factory):
    """A stretch is meaningless without a kind, so each window_s carries a known one."""
    time_vector = _make_time_vector(LONG_SAMPLE_COUNT)
    columns = column_factory(time_vector)
    tags = _make_loop_tags(name="loop 1")

    [result] = analyze_dataset(time_vector, columns, [tags])

    windowed_findings = [f for f in result["findings"] if "window_s" in f]
    assert windowed_findings
    assert all(f["window_kind"] in VALID_WINDOW_KINDS for f in windowed_findings)


def test_a_healthy_loop_reports_no_windowed_finding():
    """Nothing is wrong with a healthy loop, so no finding points at a stretch."""
    time_vector = _make_time_vector(LONG_SAMPLE_COUNT)
    columns = _make_healthy_columns(time_vector)
    tags = _make_loop_tags(name="healthy loop")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert all("window_kind" not in finding for finding in result["findings"])
