"""Detect tags holding a long exact linear ramp, the fingerprint of an archive gap that was
linearly interpolated. Such stretches carry no real measurement, so the tag is flagged as
unreliable and downstream analysis can exclude or down-weight it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

# A ramp must span at least this many samples by default: short linear stretches occur by chance.
DEFAULT_MIN_LEN = 120
# Relative tolerance for "this triple is on a straight line", scaled by the signal magnitude.
DEFAULT_REL_TOL = 1e-6
# A triple counts as linear when its second difference is below rel_tol * scale.
# The samples of a run of k consecutive linear triples span k + 2 samples.
SAMPLES_PER_TRIPLE = 2
# Axes an input array must have to be treated as a single 1-D series.
EXPECTED_NDIM = 1
# A span covering at least this share of a tag marks the tag as unreliable.
DEFAULT_MIN_FRACTION = 0.02


@dataclass(frozen=True)
class RampSpan:
    """A maximal run of samples lying on an exact straight line.

    Attributes:
        start: Index of the first sample of the run (inclusive).
        end: Index one past the last sample of the run (exclusive).
        slope: Change per sample along the ramp (value units per sample).
        length: Number of samples in the run, equal to ``end - start``.
    """

    start: int
    end: int
    slope: float
    length: int


def _validate_values(values: np.ndarray, min_len: int) -> None:
    """Raise ValueError if the series cannot be scanned as a 1-D array of at least min_len."""
    if min_len < 3:
        raise ValueError(f"min_len must be at least 3 samples, got {min_len}")
    if values.ndim != EXPECTED_NDIM:
        raise ValueError(f"values must be 1-D, got an array with shape {values.shape}")


def _linear_mask(values: np.ndarray, rel_tol: float) -> np.ndarray:
    """Return a boolean mask over the sample triples that lie on a straight line.

    Second difference d2[i] = v[i+2] - 2*v[i+1] + v[i] is zero for any linear triple. The
    tolerance is relative to the signal scale so huge and tiny signals behave the same. A
    triple touching a NaN gets d2 = NaN, which fails the comparison and so breaks runs.
    """
    scale = max(float(np.nanmax(np.abs(values))), 1.0)
    second_difference = np.diff(values, 2)
    with np.errstate(invalid="ignore"):
        return np.abs(second_difference) <= rel_tol * scale


def _run_bounds(linear: np.ndarray) -> list[tuple[int, int]]:
    """Split the linear-triple mask into maximal runs and return their half-open triple ranges."""
    padded = np.concatenate(([False], linear, [False]))
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(changes[0::2], changes[1::2], strict=True))


def _span_from_triples(values: np.ndarray, start: int, end: int) -> RampSpan | None:
    """Build the span of a run of triples, or None if it is too short or perfectly flat."""
    length = end - start + SAMPLES_PER_TRIPLE
    first_value, last_value = values[start], values[start + length - 1]
    slope = (last_value - first_value) / (length - 1)
    if slope == 0:
        return None
    return RampSpan(start=int(start), end=int(start + length), slope=float(slope), length=length)


def find_linear_ramps(
    values: np.ndarray, *, min_len: int = DEFAULT_MIN_LEN, rel_tol: float = DEFAULT_REL_TOL
) -> list[RampSpan]:
    """Return the maximal exact linear ramps in values that span at least min_len samples.

    A ramp needs a non-zero slope, so flat stretches (stuck sensors) are not reported. NaN
    samples split runs. Raises ValueError for non-1-D input or min_len below 3.
    """
    _validate_values(values, min_len)
    linear = _linear_mask(values, rel_tol)
    spans = [_span_from_triples(values, start, end) for start, end in _run_bounds(linear)]
    return [span for span in spans if span is not None and span.length >= min_len]


def ramp_fraction(values: np.ndarray, spans: list[RampSpan]) -> float:
    """Return the share of samples of values that fall inside the given spans, in [0, 1]."""
    if values.size == 0:
        return 0.0
    covered = sum(span.length for span in spans)
    return min(covered / values.size, 1.0)


def unreliable_tags(
    columns: Mapping[str, np.ndarray],
    *,
    min_len: int = DEFAULT_MIN_LEN,
    rel_tol: float = DEFAULT_REL_TOL,
    min_fraction: float = DEFAULT_MIN_FRACTION,
) -> dict[str, float]:
    """Return tag -> ramp fraction for every tag whose ramps cover at least min_fraction.

    Tags absent from the result are considered reliable.
    """
    flagged: dict[str, float] = {}
    for tag, values in columns.items():
        spans = find_linear_ramps(values, min_len=min_len, rel_tol=rel_tol)
        fraction = ramp_fraction(values, spans)
        if fraction >= min_fraction:
            flagged[tag] = fraction
    return flagged
