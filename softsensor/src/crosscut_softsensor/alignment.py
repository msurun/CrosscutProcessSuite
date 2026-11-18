"""Align catalogue targets and estimate relative delays from user measurements.

Times and delays use seconds; report availability is kept separate from physical alignment.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from crosscut_softsensor.long_format import TagSeries
from crosscut_softsensor.runner import LabResults

MINIMUM_PAIRS = 8  # Paired observations needed to fit a meaningful delay profile.
MAXIMUM_CANDIDATES = 1001  # Bound scan work for interactive API requests.
DEFAULT_BOOTSTRAP_SAMPLES = 200  # Paired resamples for a 95 percent percentile interval.
MAXIMUM_BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 38  # Reproducible uncertainty estimates for the same data.
INTERVAL_PERCENTILES = (2.5, 97.5)


class AlignmentError(ValueError):
    """Invalid metadata or insufficient measurements to estimate alignment."""


def _mapping(value: Any, field: str) -> dict:
    """Reject malformed metadata before reading its fields."""
    if not isinstance(value, dict):
        raise AlignmentError(f"{field}: supply a metadata object.")
    return value


def _missing_codes(metadata: dict) -> list:
    """Validate the catalogue's numeric sentinel values."""
    values = metadata.get("missing_codes", [])
    if not isinstance(values, list | tuple) or any(
        isinstance(value, bool) or not isinstance(value, int | float) for value in values
    ):
        raise AlignmentError("missing_codes: supply an array of numbers.")
    return list(values)


def _number(metadata: dict, key: str, default: float = 0.0) -> float:
    """Read a finite nonnegative duration in seconds."""
    value = metadata.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or not np.isfinite(value):
        raise AlignmentError(f"{key}: supply a finite number of seconds.")
    if value < 0:
        raise AlignmentError(f"{key}: supply a nonnegative duration in seconds.")
    return float(value)


def _sample_offset(metadata: dict, window_s: float) -> float:
    """Resolve a stamp to the composite midpoint, honoring an explicit offset."""
    stamp = _mapping(metadata.get("stamp", {}), "stamp")
    meaning = stamp.get("meaning", "middle")
    offsets = {"start": window_s / 2, "end": -window_s / 2, "middle": 0.0, "mid": 0.0}
    if meaning not in offsets:
        raise AlignmentError("stamp.meaning: choose start, end or middle.")
    offset = stamp.get("offset_s", offsets[meaning])
    if isinstance(offset, bool) or not isinstance(offset, int | float) or not np.isfinite(offset):
        raise AlignmentError("stamp.offset_s: supply a finite number of seconds.")
    return float(offset)


def _clean_series(series: TagSeries, metadata: dict) -> TagSeries:
    """Remove configured missing values and validate chronological sample arrays."""
    times, values = np.asarray(series.t_s, float), np.asarray(series.values, float)
    if times.ndim != 1 or values.shape != times.shape or not np.isfinite(times).all():
        raise AlignmentError("Provide matching one-dimensional times and values with finite times.")
    if len(times) < 1 or np.any(np.diff(times) <= 0):
        raise AlignmentError("Provide at least one sample with strictly increasing timestamps.")
    valid = np.isfinite(values) & ~np.isin(values, _missing_codes(metadata))
    bounds = _mapping(metadata.get("valid_range", {}), "valid_range")
    valid &= (values >= bounds.get("min", -np.inf)) & (values <= bounds.get("max", np.inf))
    return TagSeries(series.tag, times[valid], values[valid])


def align_target(series: TagSeries, metadata: dict) -> LabResults:
    """Resolve sample midpoint and independent report availability from catalogue metadata.

    A physical analyser delay moves the represented process time backwards. Report delay
    only postpones availability after the composite ends; latency_s is its legacy alias.
    """
    metadata = _mapping(metadata, "metadata")
    clean = _clean_series(series, metadata)
    window_s = _number(metadata, "composite_window_s")
    analyser_delay_s = _number(metadata, "analyser_delay_s")
    report_delay_s = _number(metadata, "report_delay_s", metadata.get("latency_s", 0.0))
    midpoint_s = clean.t_s + _sample_offset(metadata, window_s)
    return LabResults(midpoint_s - analyser_delay_s, clean.values,
                      midpoint_s + window_s / 2 + report_delay_s)


def _candidate_delays(options: dict) -> np.ndarray:
    """Build a bounded inclusive delay grid in seconds."""
    try:
        low, high, step = (float(options[key]) for key in
                           ("min_delay_s", "max_delay_s", "step_s"))
    except (KeyError, ValueError, TypeError) as error:
        raise AlignmentError("Supply min_delay_s, max_delay_s and step_s in seconds.") from error
    if not np.isfinite([low, high, step]).all() or step <= 0 or high < low:
        raise AlignmentError("Use finite delay bounds with max >= min and step > 0.")
    count = int(np.floor((high - low) / step)) + 1
    if count < 2 or count > MAXIMUM_CANDIDATES:
        raise AlignmentError(f"Choose between 2 and {MAXIMUM_CANDIDATES} delay candidates.")
    return low + np.arange(count) * step


def _window_values(reference: LabResults, centres: np.ndarray, window_s: float) -> np.ndarray:
    """Average reference readings in each composite, or interpolate a point sample."""
    if len(reference.t_s) < 2:
        raise AlignmentError("Reference needs at least two valid measurements.")
    if window_s == 0:
        return np.interp(centres, reference.t_s, reference.values, left=np.nan, right=np.nan)
    starts, ends = centres - window_s / 2, centres + window_s / 2
    left = np.searchsorted(reference.t_s, starts, side="left")
    right = np.searchsorted(reference.t_s, ends, side="right")
    sums = np.concatenate(([0.0], np.cumsum(reference.values)))
    counts = right - left
    covered = (starts >= reference.t_s[0]) & (ends <= reference.t_s[-1]) & (counts > 0)
    return np.where(covered, (sums[right] - sums[left]) / np.maximum(counts, 1), np.nan)


def _paired_measurements(lab: LabResults, reference: LabResults,
                         delays: np.ndarray, window_s: float) -> tuple[np.ndarray, np.ndarray]:
    """Keep identical observations across candidates so edge loss cannot improve a score."""
    # Positive delay means the reference is recorded later than the lab's process time.
    features = np.array([_window_values(reference, lab.t_s + delay, window_s)
                         for delay in delays])
    common = np.isfinite(features).all(axis=0) & np.isfinite(lab.values)
    if np.count_nonzero(common) < MINIMUM_PAIRS:
        raise AlignmentError(f"Need at least {MINIMUM_PAIRS} shared valid pairs across all delays.")
    return features[:, common], lab.values[common]


def _correlations(features: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Compute signed Pearson correlations for all candidates without changing their rows."""
    centred = features - features.mean(axis=1, keepdims=True)
    residuals = targets - targets.mean()
    denominators = np.sqrt(np.sum(centred ** 2, axis=1) * np.sum(residuals ** 2))
    return np.divide(centred @ residuals, denominators,
                     out=np.full(len(features), np.nan), where=denominators > 0)


def _bootstrap_delays(features: np.ndarray, targets: np.ndarray,
                      delays: np.ndarray, samples: int) -> np.ndarray:
    """Resample paired rows and reselect the strongest absolute correlation each time."""
    generator = np.random.default_rng(BOOTSTRAP_SEED)
    selected = []
    for _ in range(samples):
        indices = generator.integers(0, len(targets), len(targets))
        scores = _correlations(features[:, indices], targets[indices])
        if np.isfinite(scores).any():
            selected.append(delays[int(np.nanargmax(np.abs(scores)))])
    if not selected:
        raise AlignmentError("Bootstrap samples are constant; supply more varied measurements.")
    return np.asarray(selected)


def _bootstrap_count(options: dict) -> int:
    """Validate the bounded count of uncertainty resamples."""
    samples = options.get("bootstrap_samples", DEFAULT_BOOTSTRAP_SAMPLES)
    if isinstance(samples, bool) or not isinstance(samples, int):
        raise AlignmentError("bootstrap_samples: supply an integer.")
    if not 20 <= samples <= MAXIMUM_BOOTSTRAP_SAMPLES:
        raise AlignmentError(f"bootstrap_samples: choose 20 to {MAXIMUM_BOOTSTRAP_SAMPLES}.")
    return samples


def _scan_report(delays: np.ndarray, correlations: np.ndarray,
                 selected: np.ndarray, pair_count: int) -> dict[str, Any]:
    """Serialize the correlation profile and grid-limited percentile uncertainty band."""
    best = int(np.nanargmax(np.abs(correlations)))
    lower, upper = np.percentile(selected, INTERVAL_PERCENTILES)
    # Half a grid step reflects resolution even when every resample chooses one candidate.
    half_step = float(delays[1] - delays[0]) / 2
    profile = [{"delay_s": float(delay), "correlation": float(score), "pairs": pair_count}
               for delay, score in zip(delays, correlations, strict=True) if np.isfinite(score)]
    return {"best_delay_s": float(delays[best]), "interval_low_s": float(lower - half_step),
            "interval_high_s": float(upper + half_step), "profile": profile,
            "method": "paired-bootstrap-95-percent", "pairs": pair_count,
            "boundary": bool(best in (0, len(delays) - 1)),
            "sign_convention": "positive means reference recorded later than target process time"}


def scan_alignment(lab: TagSeries, reference: TagSeries,
                   metadata: dict, options: dict) -> dict[str, Any]:
    """Scan relative delays using a composite mean and paired-bootstrap uncertainty.

    The model is target = intercept + slope * reference; maximizing absolute Pearson r
    minimizes affine-calibration SSE on common rows. The interval is conditional on the
    searched range and uses paired resampling (independent lab observations assumed).
    """
    options = _mapping(options, "options")
    delays = _candidate_delays(options)
    samples = _bootstrap_count(options)
    targets = align_target(lab, metadata)
    aligned_reference = align_target(reference, options.get("reference_metadata", {}))
    features, values = _paired_measurements(
        targets, aligned_reference, delays, _number(metadata, "composite_window_s"))
    correlations = _correlations(features, values)
    if not np.isfinite(correlations).any():
        raise AlignmentError("Cannot estimate delay from constant data; provide varied samples.")
    selected = _bootstrap_delays(features, values, delays, samples)
    return _scan_report(delays, correlations, selected, len(values))
