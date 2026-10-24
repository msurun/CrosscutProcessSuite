"""Tests for crosscut_anomaly.ramp_detect.

Synthetic series only; neutral tag names. Each test pins one behaviour of ramp
detection so failures name the rule that broke.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_anomaly.ramp_detect import (
    RampSpan,
    find_linear_ramps,
    ramp_fraction,
    unreliable_tags,
)

NOISE_AMPLITUDE = 0.1
RAMP_SLOPE = 0.5
RAMP_START = 100
RAMP_LENGTH = 300
SERIES_LENGTH = 600
LARGE_OFFSET = 1e6


def _series_with_ramp() -> np.ndarray:
    """Return a noisy series with an exact linear ramp stitched into the middle."""
    generator = np.random.default_rng(0)
    values = generator.normal(0.0, NOISE_AMPLITUDE, SERIES_LENGTH)
    ramp = RAMP_SLOPE * np.arange(RAMP_LENGTH)
    values[RAMP_START : RAMP_START + RAMP_LENGTH] = ramp
    return values


def test_ramp_detect_exact_ramp_is_found_with_bounds_and_slope() -> None:
    spans = find_linear_ramps(_series_with_ramp())

    assert len(spans) == 1
    assert spans[0].start == RAMP_START
    assert spans[0].end == RAMP_START + RAMP_LENGTH
    assert spans[0].slope == pytest.approx(RAMP_SLOPE)


def test_ramp_detect_noisy_series_has_no_ramps() -> None:
    generator = np.random.default_rng(0)
    values = generator.normal(0.0, NOISE_AMPLITUDE, SERIES_LENGTH)

    assert find_linear_ramps(values) == []


def test_ramp_detect_flat_constant_run_is_not_a_ramp() -> None:
    values = np.full(SERIES_LENGTH, 3.0)

    assert find_linear_ramps(values) == []


def test_ramp_detect_ramp_shorter_than_min_len_is_ignored() -> None:
    values = _series_with_ramp()

    spans = find_linear_ramps(values, min_len=RAMP_LENGTH + 1)

    assert spans == []


def test_ramp_detect_nan_splits_ramp_into_two_spans() -> None:
    values = _series_with_ramp()
    values[RAMP_START + RAMP_LENGTH // 2] = np.nan

    spans = find_linear_ramps(values, min_len=20)

    assert len(spans) == 2


def test_ramp_detect_nan_split_ramp_vanishes_below_min_len() -> None:
    values = _series_with_ramp()
    values[RAMP_START + RAMP_LENGTH // 2] = np.nan

    spans = find_linear_ramps(values, min_len=RAMP_LENGTH)

    assert spans == []


def test_ramp_detect_ramp_fraction_is_share_of_samples_covered() -> None:
    values = _series_with_ramp()

    spans = find_linear_ramps(values)

    assert ramp_fraction(values, spans) == pytest.approx(RAMP_LENGTH / SERIES_LENGTH)


def test_ramp_detect_ramp_fraction_of_empty_series_is_zero() -> None:
    empty = np.array([])

    assert ramp_fraction(empty, []) == 0.0


def test_ramp_detect_unreliable_tags_flags_only_interpolated_tag() -> None:
    generator = np.random.default_rng(0)
    columns = {
        "tag_a": _series_with_ramp(),
        "tag_b": generator.normal(0.0, NOISE_AMPLITUDE, SERIES_LENGTH),
    }

    flagged = unreliable_tags(columns)

    assert set(flagged) == {"tag_a"}
    assert flagged["tag_a"] == pytest.approx(RAMP_LENGTH / SERIES_LENGTH)


def test_ramp_detect_min_len_below_three_raises_value_error() -> None:
    with pytest.raises(ValueError):
        find_linear_ramps(np.arange(10.0), min_len=2)


def test_ramp_detect_two_dimensional_array_raises_value_error() -> None:
    with pytest.raises(ValueError):
        find_linear_ramps(np.zeros((4, 4)))


def test_ramp_detect_large_magnitude_ramp_is_found() -> None:
    values = LARGE_OFFSET + RAMP_SLOPE * np.arange(RAMP_LENGTH)

    spans = find_linear_ramps(values)

    assert len(spans) == 1
    assert spans[0].slope == pytest.approx(RAMP_SLOPE)


def test_ramp_detect_descending_ramp_has_negative_slope() -> None:
    values = -RAMP_SLOPE * np.arange(RAMP_LENGTH)

    spans = find_linear_ramps(values)

    assert len(spans) == 1
    assert spans[0].slope == pytest.approx(-RAMP_SLOPE)


def test_ramp_detect_span_reports_length_equal_to_bounds_difference() -> None:
    span = RampSpan(start=10, end=20, slope=1.5, length=10)

    assert span.length == span.end - span.start
