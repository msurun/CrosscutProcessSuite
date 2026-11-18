"""Locate windowed sensor faults without changing readiness verdicts.

Single-tag drift detection is weak: process ramps can look like sensor drift.
A correlated reference makes the residual trend more informative.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np

MAD_SCALE = 1.4826  # normal-consistent conversion from MAD to sigma
FIT_SAMPLES = 40  # maximum samples in a pairwise slope fit
SETPOINT_SHARE = 0.9  # fraction of exactly unchanged adjacent values
VARIABILITY_FACTOR = 4.0  # required movement relative to quantisation
MAX_GAP_PERIODS = 1.5  # largest connected gap, in median sample periods
RETURN_SIGMA = 2.0  # tolerated distance from the pre-spike value, in sigma
STEP_MIN_COUNT = 20  # minimum repeated differences supporting quantisation
STEP_MAX_RANGE_SHARE = 0.01  # largest resolution fraction of the observed range
SLOPE_FLOOR = 1e-12  # minimum slope scale in engineering units per second
STEP_SUPPORT = 0.05  # minimum share supporting the smallest quantisation step
STEP_RELATIVE_TOLERANCE = 1e-5  # relative rounding tolerance on repeated steps
NUMERICAL_MARGIN = 16  # floating-point epsilon multiplier, dimensionless


@dataclass(frozen=True)
class SensorFaultConfig:
    """Window durations in seconds; sigma thresholds are dimensionless.

    Windows overlap by half by default. Freeze requires 30 minutes, drift two
    hours, and spike clusters require two returning excursions above six sigma.
    """

    window_s: float = 3600.0
    step_s: float = 1800.0
    freeze_min_s: float = 1800.0
    spike_k: float = 6.0
    spike_min_count: int = 2
    spike_gap_s: float = 3600.0
    drift_z: float = 4.0
    drift_min_s: float = 7200.0

    def __post_init__(self) -> None:
        """Reject thresholds that cannot define a finite detection window."""
        thresholds = tuple(asdict(self).values())
        if not all(np.isfinite(value) and value > 0 for value in thresholds):
            raise ValueError("Sensor fault thresholds must be finite and positive.")
        if self.step_s > self.window_s or int(self.spike_min_count) != self.spike_min_count:
            raise ValueError("Use step_s <= window_s and an integer spike_min_count.")


@dataclass(frozen=True)
class SensorFaultFinding:
    """One merged event; score is threshold strength, not a probability."""

    tag: str
    kind: Literal["freeze", "drift", "spike"]
    start_s: float
    end_s: float
    score: float
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible event fields."""
        return asdict(self)


@dataclass(frozen=True)
class SensorRecord:
    """Aligned one-dimensional arrays and thresholds for one tag's analysis."""

    times: np.ndarray
    samples: np.ndarray
    adjusted: np.ndarray
    valid: np.ndarray
    tag: str
    config: SensorFaultConfig


def robust_sigma(values: np.ndarray) -> float:
    """Estimate normal-consistent spread in the input's engineering units."""
    return float(MAD_SCALE * np.median(np.abs(values - np.median(values))))


def estimate_resolution(values: np.ndarray) -> float:
    """Find a repeated smallest step; continuous noise gets a numerical floor.

    A quantisation lattice has many differences near its smallest positive step.
    Requiring repeated support avoids treating one tiny noisy difference as a step.
    """
    floor = np.finfo(float).eps * max(1.0, float(np.max(np.abs(values)))) * NUMERICAL_MARGIN
    differences = np.abs(np.diff(values))
    positive = differences[differences > floor]
    if not positive.size:
        return floor
    candidate = float(np.quantile(positive, STEP_SUPPORT))
    repeats = np.count_nonzero(
        np.isclose(positive, candidate, rtol=STEP_RELATIVE_TOLERANCE, atol=floor))
    supported = repeats >= STEP_MIN_COUNT and repeats / positive.size >= STEP_SUPPORT
    plausible = candidate <= STEP_MAX_RANGE_SHARE * float(np.ptp(values))
    return candidate if supported and plausible else floor


def validate_series(t_s: np.ndarray, values: np.ndarray) -> None:
    """Require aligned one-dimensional samples and strictly increasing finite time."""
    if t_s.ndim != 1 or values.ndim != 1 or t_s.shape != values.shape:
        raise ValueError("Provide aligned one-dimensional timestamps and values.")
    if not np.all(np.isfinite(t_s)) or np.any(np.diff(t_s) <= 0):
        raise ValueError("Provide finite, strictly increasing timestamps in seconds.")


def fit_slope(t_s: np.ndarray, values: np.ndarray) -> float:
    """Return a decimated Theil–Sen slope in engineering units per second."""
    indices = np.unique(np.linspace(0, len(values) - 1, min(FIT_SAMPLES, len(values))).astype(int))
    times, samples = t_s[indices], values[indices]
    # For 1-D aligned arrays, upper-triangle pairs give dy/dt without zero denominators.
    left, right = np.triu_indices(len(indices), 1)
    return float(np.median((samples[right] - samples[left]) / (times[right] - times[left])))


def remove_reference(values: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Subtract an affine least-squares reference fit in the tag's units."""
    centered = reference - np.mean(reference)
    denominator = float(centered @ centered)
    coefficient = float(centered @ (values - np.mean(values))) / denominator if denominator else 0
    return values - coefficient * centered


def detect_sensor_faults(
    t_s: np.ndarray, values: np.ndarray, tag: str = "", config: SensorFaultConfig | None = None,
    *, good: np.ndarray | None = None, reference: np.ndarray | None = None,
) -> list[SensorFaultFinding]:
    """Detect events; invalid samples break runs and windows never bridge missing data."""
    times, samples = np.asarray(t_s, dtype=float), np.asarray(values, dtype=float)
    validate_series(times, samples)
    valid = np.isfinite(samples)
    if good is not None:
        validate_series(times, np.asarray(good))
        valid &= np.asarray(good, dtype=bool)
    if reference is not None:
        reference = np.asarray(reference, dtype=float)
        validate_series(times, reference)
        valid &= np.isfinite(reference)
    if np.count_nonzero(valid) < 3:
        return []
    adjusted = samples.copy()
    if reference is not None:
        adjusted[valid] = remove_reference(samples[valid], reference[valid])
    record = SensorRecord(times, samples, adjusted, valid, tag, config or SensorFaultConfig())
    return collect_findings(record)


def collect_findings(record: SensorRecord) -> list[SensorFaultFinding]:
    """Combine original-signal freezes/spikes with residual drift windows."""
    times, samples, valid = record.times, record.samples, record.valid
    tag, config = record.tag, record.config
    resolution = estimate_resolution(samples[valid])
    if robust_sigma(samples[valid]) <= resolution:
        return []
    differences = np.diff(samples)
    adjacent = valid[:-1] & valid[1:]
    if not np.any(adjacent) or np.mean(differences[adjacent] == 0) > SETPOINT_SHARE:
        return []
    freezes = find_freezes(times, samples, valid, (resolution, config.freeze_min_s))
    spikes = find_spike_samples(samples, valid, (resolution, config.spike_k))
    windows = build_windows(times, valid, config)
    findings = [SensorFaultFinding(tag, "freeze", start, end, score, evidence)
                for start, end, score, evidence in freezes]
    findings.extend(cluster_spikes(record, spikes))
    findings.extend(find_window_faults(record, windows))
    return merge_findings(findings)


def find_freezes(
    times: np.ndarray, samples: np.ndarray, valid: np.ndarray, thresholds: tuple[float, float],
) -> list[tuple[float, float, float, dict[str, float]]]:
    """Find sustained flat runs only when the rest of the tag clearly moves."""
    resolution, minimum_s = thresholds
    starts, ends = flat_run_bounds(times, samples, valid, resolution)
    findings = []
    low, high = np.min(samples[valid]), np.max(samples[valid])
    for start, end in zip(starts, ends, strict=True):
        duration = float(times[end] - times[start])
        outside = valid & ((np.arange(len(samples)) < start) | (np.arange(len(samples)) > end))
        level = float(np.median(samples[start:end + 1]))
        if duration <= minimum_s or not np.any(outside):
            continue
        if min(level - low, high - level) <= resolution:
            continue
        if robust_sigma(samples[outside]) > VARIABILITY_FACTOR * resolution:
            findings.append((float(times[start]), float(times[end]), duration / minimum_s,
                             {"duration_s": duration, "resolution": resolution}))
    return findings


def flat_run_bounds(
    times: np.ndarray, samples: np.ndarray, valid: np.ndarray, resolution: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Locate connected flat runs, including both endpoint samples."""
    period_s = float(np.median(np.diff(times)))
    connected = np.diff(times) <= MAX_GAP_PERIODS * period_s
    rounding = NUMERICAL_MARGIN * np.finfo(float).eps * max(1, np.max(np.abs(samples[valid])))
    edges = valid[:-1] & valid[1:] & connected & (np.abs(np.diff(samples)) <= resolution + rounding)
    starts = np.flatnonzero(edges & ~np.r_[False, edges[:-1]])
    ends = np.flatnonzero(edges & ~np.r_[edges[1:], False]) + 1
    return starts, ends


def find_spike_samples(
    samples: np.ndarray, valid: np.ndarray, thresholds: tuple[float, float],
) -> np.ndarray:
    """Mark excursions that reverse and return within two samples."""
    resolution, multiplier = thresholds
    differences = np.diff(samples)
    adjacent = valid[:-1] & valid[1:]
    sigma = max(robust_sigma(differences[adjacent]), resolution)
    spikes = np.zeros(len(samples), dtype=bool)
    for index in np.flatnonzero(adjacent & (np.abs(differences) > multiplier * sigma)) + 1:
        if index > 1 and spikes[index - 1]:
            continue
        spikes[index] = returns_to_baseline(samples, valid, index, sigma)
    return spikes


def returns_to_baseline(
    samples: np.ndarray, valid: np.ndarray, index: int, sigma: float,
) -> bool:
    """Require good samples and a return within one or two sample periods."""
    for distance in (1, 2):
        end = index + distance
        if end < len(samples) and np.all(valid[index - 1:end + 1]):
            if abs(samples[end] - samples[index - 1]) <= RETURN_SIGMA * sigma:
                return True
    return False


def build_windows(
    times: np.ndarray, valid: np.ndarray, config: SensorFaultConfig,
) -> list[np.ndarray]:
    """Return complete windows with at least three consecutive good observations."""
    windows = []
    period_s = float(np.median(np.diff(times)))
    last_start = times[-1] - config.window_s + period_s
    for start in np.arange(times[0], np.nextafter(last_start, np.inf), config.step_s):
        indices = np.flatnonzero((times >= start) & (times <= start + config.window_s))
        connected = np.all(np.diff(times[indices]) <= MAX_GAP_PERIODS * period_s)
        if len(indices) >= 3 and connected and np.all(valid[indices]):
            windows.append(indices)
    return windows


def cluster_spikes(record: SensorRecord, spikes: np.ndarray) -> list[SensorFaultFinding]:
    """Group returning excursions by elapsed time, independently of analysis windows."""
    spike_times = record.times[spikes]
    if not spike_times.size:
        return []
    # A 1-D array of event times (seconds) splits only when the quiet gap exceeds the limit.
    boundaries = np.flatnonzero(np.diff(spike_times) > record.config.spike_gap_s) + 1
    findings = []
    for cluster in np.split(spike_times, boundaries):
        count = len(cluster)
        if count >= record.config.spike_min_count:
            findings.append(SensorFaultFinding(
                record.tag, "spike", float(cluster[0]), float(cluster[-1]),
                count / record.config.spike_min_count, {"count": count}))
    return findings


def find_window_faults(
    record: SensorRecord, windows: list[np.ndarray],
) -> list[SensorFaultFinding]:
    """Compare robust window slopes with the record's typical slope distribution."""
    times, values, config = record.times, record.adjusted, record.config
    if not windows:
        return []
    slopes = np.array([fit_slope(times[indices], values[indices]) for indices in windows])
    center = float(np.median(slopes))
    # Slopes have units/second: one instrument step per window bounds credible precision.
    resolution = estimate_resolution(record.samples[record.valid])
    scale = max(robust_sigma(slopes), resolution / config.window_s, SLOPE_FLOOR)
    findings = []
    for indices, slope in zip(windows, slopes, strict=True):
        findings.extend(classify_window(record, indices, (slope, center, scale)))
    merged = merge_findings(findings)
    return [event for event in merged if event.kind != "drift"
            or event.end_s - event.start_s >= config.drift_min_s]


def classify_window(
    record: SensorRecord, indices: np.ndarray,
    slope_statistics: tuple[float, float, float],
) -> list[SensorFaultFinding]:
    """Produce drift candidates from normalised slope deviations."""
    slope, center, scale = slope_statistics
    config, tag = record.config, record.tag
    start, end = float(record.times[indices[0]]), float(record.times[indices[-1]])
    findings = []
    # A robust z score compares units/second against the same units/second.
    strength = abs(slope - center) / scale
    if strength >= config.drift_z:
        evidence = {"slope_per_s": float(slope), "robust_z": float(strength),
                    "last_window_start_s": start, "step_s": config.step_s}
        findings.append(SensorFaultFinding(tag, "drift", start, end, float(strength), evidence))
    return findings


def merge_findings(findings: list[SensorFaultFinding]) -> list[SensorFaultFinding]:
    """Merge overlapping same-kind events; opposite drift directions remain separate."""
    merged: list[SensorFaultFinding] = []
    for event in sorted(findings, key=lambda item: (item.tag, item.kind, item.start_s)):
        previous = merged[-1] if merged else None
        if previous and can_merge(previous, event):
            merged[-1] = SensorFaultFinding(event.tag, event.kind, previous.start_s,
                                           max(previous.end_s, event.end_s),
                                           max(previous.score, event.score),
                                           merge_evidence(previous, event))
        else:
            merged.append(event)
    return merged


def can_merge(previous: SensorFaultFinding, event: SensorFaultFinding) -> bool:
    """Check temporal overlap, identity and drift direction."""
    if (previous.tag, previous.kind) != (event.tag, event.kind):
        return False
    if previous.end_s < event.start_s:
        return False
    if event.kind != "drift":
        return True
    consecutive = event.start_s <= (
        previous.evidence["last_window_start_s"] + previous.evidence["step_s"])
    same_sign = np.sign(previous.evidence["slope_per_s"]) == np.sign(event.evidence["slope_per_s"])
    return bool(consecutive and same_sign)


def merge_evidence(previous: SensorFaultFinding, event: SensorFaultFinding) -> dict[str, Any]:
    """Keep strongest evidence while retaining the final window for continuity."""
    evidence = dict(previous.evidence if previous.score >= event.score else event.evidence)
    if event.kind == "drift":
        evidence["last_window_start_s"] = event.evidence["last_window_start_s"]
    return evidence


def score_findings(
    findings: Sequence[SensorFaultFinding],
    truth_events: Sequence[SensorFaultFinding | Mapping[str, Any]],
    tolerance_s: float = 0.0,
) -> tuple[float, float]:
    """Return event precision/recall using maximum one-to-one overlap matching.

    Truth events may be findings or dictionaries with tag, kind, start_s and end_s.
    Empty predictions/truth score one on their respective denominator.
    """
    if not np.isfinite(tolerance_s) or tolerance_s < 0:
        raise ValueError("Use a finite nonnegative event tolerance in seconds.")
    predictions = [event.to_dict() for event in findings]
    truth = [event.to_dict() if hasattr(event, "to_dict") else event for event in truth_events]
    matches: dict[int, int] = {}
    for index in range(len(predictions)):
        match_event(index, predictions, truth, (matches, set(), tolerance_s))
    return (len(matches) / len(predictions) if predictions else 1.0,
            len(matches) / len(truth) if truth else 1.0)


def match_event(
    index: int, predictions: list[dict[str, Any]], truth: list[Mapping[str, Any]],
    state: tuple[dict[int, int], set[int], float],
) -> bool:
    """Use augmenting paths so a broad prediction cannot steal a unique match."""
    matches, visited, tolerance = state
    event = predictions[index]
    for target, expected in enumerate(truth):
        same = (event["tag"], event["kind"]) == (expected["tag"], expected["kind"])
        overlaps = (event["start_s"] <= expected["end_s"] + tolerance
                    and event["end_s"] >= expected["start_s"] - tolerance)
        if target in visited or not same or not overlaps:
            continue
        visited.add(target)
        if target not in matches or match_event(matches[target], predictions, truth, state):
            matches[target] = index
            return True
    return False
