"""
Finds step tests in historian data: OUT moves in manual mode and SP moves in
auto mode, each with an analysis window before and after the step.
Analysis only, no plant writes. See docs/design/step-analyzer.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Robust standard deviation to standard deviation consistency factor for
# normally distributed data: MAD -> 1.4826 * sigma.
MAD_TO_STD_FACTOR = 1.4826

# The difference of two adjacent samples of white noise with standard
# deviation sigma has variance 2 * sigma^2, so dividing its spread by sqrt(2)
# recovers sigma.
DIFF_VARIANCE_FACTOR = np.sqrt(2.0)

# Median-difference half-window length in seconds for OUT event detection.
OUT_WINDOW_S = 60.0

# Minimum OUT window length in samples, whatever the sample period.
MIN_OUT_WINDOW_SAMPLES = 3

# Minimum OUT change (OUT units) that counts as a step, whatever the noise.
MIN_OUT_STEP_SIZE = 1.0

# An OUT change must be at least this many robust noise standard deviations.
OUT_STEP_NOISE_RATIO = 3.0

# Two OUT candidates closer than this many window lengths are one step.
OUT_MERGE_WINDOW_FACTOR = 2

# An SP change must be at least this many robust noise standard deviations.
SP_STEP_NOISE_RATIO = 3.0

# Minimum SP change (SP units); guards against denormal detector output on a
# perfectly flat signal where the robust noise is exactly zero.
MIN_SP_STEP_SIZE = 1e-9

# SP changes closer than this many seconds belong to the same step.
SP_MERGE_S = 60.0

# A segment is a run of samples without gaps larger than this many samples.
MAX_GAP_SAMPLES = 5

# A window needs at least this many samples before the event to see a baseline.
MIN_PRE_SAMPLES = 10

# A window needs at least this many samples after the event to see the response.
MIN_POST_SAMPLES = 30

MANUAL_MODE = 0
AUTO_MODE = 1
CAS_MODE = 2
RSP_MODE = 3

# Raw mode codes whose SP moves count as closed-loop (auto-like) SP steps:
# AUTO (operator SP) and RSP (remote setpoint written by the supervisor or
# gateway). CAS (2) is deliberately excluded: the master controller moves the SP
# continuously and correlated with disturbances, which biases identification.
CLOSED_LOOP_MODES = frozenset({AUTO_MODE, RSP_MODE})

OUT_STEP_KIND = "out_step"
SP_STEP_KIND = "sp_step"

MANUAL_MODE_NAME = "manual"
AUTO_MODE_NAME = "auto"

WINDOW_TOO_SHORT_REASON = "window_too_short"


@dataclass(frozen=True)
class StepEvent:
    """One step test with its analysis window.

    Attributes:
        kind: "out_step" or "sp_step".
        i: Sample index of the event (first sample at the new level).
        t_s: Event time in seconds (``t_s[i]``).
        size: Signed step size in OUT units (out_step) or SP units (sp_step).
        i0: First sample index of the analysis window.
        i1: Sample index just past the window (exclusive).
        mode: "manual" or "auto".
        pre: Number of window samples before the event, ``i - i0``.
    """

    kind: str
    i: int
    t_s: float
    size: float
    i0: int
    i1: int
    mode: str
    pre: int


@dataclass(frozen=True)
class SkippedEvent:
    """A candidate step whose analysis window was too short to be useful.

    Attributes:
        i: Sample index of the event.
        t_s: Event time in seconds.
        reason: Machine-readable reason code, "window_too_short".
    """

    i: int
    t_s: float
    reason: str


@dataclass(frozen=True)
class _Segment:
    """A run of samples without large gaps and without a mode change (half-open)."""

    start: int
    stop: int
    mode: int


@dataclass(frozen=True)
class _Candidate:
    """A step candidate before windowing: event sample index, signed size and segment."""

    i: int
    size: float
    segment: _Segment


def robust_noise_sd(pv: np.ndarray) -> float:
    """Estimate the noise standard deviation from the MAD of first differences.

    Uses ``1.4826 * MAD(diff(pv)) / sqrt(2)`` over the finite samples only,
    which is insensitive to trends and steps. Returns 0.0 when fewer than 3
    finite samples are available (no difference to work with).
    """
    signal = np.asarray(pv, dtype=float)
    finite = signal[np.isfinite(signal)]
    if finite.size < 3:
        return 0.0
    differences = np.diff(finite)
    mad = float(np.median(np.abs(differences - np.median(differences))))
    return float(MAD_TO_STD_FACTOR * mad / DIFF_VARIANCE_FACTOR)


def find_step_events(
    t_s: np.ndarray,
    pv: np.ndarray,
    sp: np.ndarray,
    out: np.ndarray,
    mode: np.ndarray,
    dt_s: float,
    pre_s: float = 600.0,
    post_s: float = 2400.0,
) -> tuple[list[StepEvent], list[SkippedEvent]]:
    """Find OUT steps in manual mode and SP steps in auto mode, with windows.

    Args:
        t_s: Sample times in seconds, increasing, gaps allowed (1-D).
        pv: Process variable samples (1-D); NaN treated as missing.
        sp: Setpoint samples (1-D); NaN treated as missing.
        out: Controller output samples (1-D); NaN treated as missing.
        mode: Mode samples (1-D), 0 = manual, 1 = automatic, NaN = unknown.
        dt_s: Nominal sample period in seconds; must be positive.
        pre_s: Window time before the event in seconds.
        post_s: Window time after the event in seconds.

    Returns:
        ``(events, skipped)``, both sorted by sample index. ``skipped`` holds
        candidates whose window had fewer than 10 pre or 30 post samples.

    Raises:
        ValueError: If the arrays differ in length or ``dt_s`` is not positive.
    """
    arrays = _validate_inputs(t_s, pv, sp, out, mode, dt_s)
    t_array, pv_array, sp_array, out_array, mode_array = arrays
    segments = _find_segments(mode_array, t_array, dt_s)
    candidates = _find_candidates(t_array, pv_array, sp_array, out_array, segments, dt_s)
    windows = _window_bounds(candidates, segments, dt_s, (pre_s, post_s))
    return _split_by_window_length(candidates, windows, t_array)


def _validate_inputs(
    t_s: np.ndarray,
    pv: np.ndarray,
    sp: np.ndarray,
    out: np.ndarray,
    mode: np.ndarray,
    dt_s: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Cast the signals to float arrays and check they line up."""
    if not np.isfinite(dt_s) or dt_s <= 0:
        raise ValueError(f"dt_s must be positive, got {dt_s!r}")
    arrays = tuple(np.asarray(signal, dtype=float) for signal in (t_s, pv, sp, out, mode))
    lengths = {array.size for array in arrays}
    if len(lengths) != 1:
        raise ValueError("t_s, pv, sp, out and mode must have the same length")
    if any(array.ndim != 1 for array in arrays):
        raise ValueError("t_s, pv, sp, out and mode must be 1-D arrays")
    return arrays


def _find_segments(mode: np.ndarray, t_s: np.ndarray, dt_s: float) -> list[_Segment]:
    """Split the record where the mode changes (to a known value) or a gap opens.

    Only manual (0) and closed-loop (CLOSED_LOOP_MODES: auto 1, remote setpoint 3)
    runs become segments; samples with an unknown mode (NaN), CAS (2) or any
    other value belong to no segment and host no events.
    """
    segments: list[_Segment] = []
    current_mode = _known_mode(mode[0]) if mode.size else None
    start = 0
    for i in range(1, t_s.size):
        mode_i = _known_mode(mode[i])
        is_gap = not (t_s[i] - t_s[i - 1] <= MAX_GAP_SAMPLES * dt_s)
        if mode_i != current_mode or is_gap:
            segments.append(_Segment(start, i, current_mode)) if current_mode is not None else None
            start, current_mode = i, mode_i
    if current_mode is not None:
        segments.append(_Segment(start, t_s.size, current_mode))
    return segments


def _known_mode(value: float) -> int | None:
    """Map a raw mode sample to MANUAL_MODE or AUTO_MODE, or None when unknown.

    RSP is folded into AUTO_MODE (both are closed-loop); CAS and unexpected
    values give None.
    """
    if value == MANUAL_MODE:
        return MANUAL_MODE
    if value in CLOSED_LOOP_MODES:
        return AUTO_MODE
    return None


def _find_candidates(
    t_s: np.ndarray,
    pv: np.ndarray,
    sp: np.ndarray,
    out: np.ndarray,
    segments: list[_Segment],
    dt_s: float,
) -> list[_Candidate]:
    """Collect OUT candidates from manual segments and SP candidates from auto."""
    noise_pv = robust_noise_sd(pv)
    out_threshold = max(MIN_OUT_STEP_SIZE, OUT_STEP_NOISE_RATIO * robust_noise_sd(out))
    sp_threshold = max(MIN_SP_STEP_SIZE, SP_STEP_NOISE_RATIO * noise_pv)
    candidates: list[_Candidate] = []
    for segment in segments:
        if segment.mode == MANUAL_MODE:
            candidates.extend(_out_candidates(out, segment, out_threshold, dt_s))
        else:
            candidates.extend(_sp_candidates(t_s, sp, segment, sp_threshold))
    return sorted(candidates, key=lambda candidate: candidate.i)


def _out_candidates(
    out: np.ndarray,
    segment: _Segment,
    threshold: float,
    dt_s: float,
) -> list[_Candidate]:
    """Find OUT steps as local maxima of the two-sided median difference.

    ``d[k] = median(out[k:k+m]) - median(out[k-m:k])`` compares the median of the
    sample block after ``k`` with the block before it, so single spikes vanish.
    Size in OUT units; the event index is the first sample after the move.
    """
    half = max(MIN_OUT_WINDOW_SAMPLES, round(OUT_WINDOW_S / dt_s))
    difference = _median_difference(out, segment, half)  # positions relative to segment.start
    loc = np.flatnonzero(np.abs(np.nan_to_num(difference)) >= threshold)
    if loc.size == 0:
        return []
    peaks = _cluster_peaks(difference, loc, 2 * half)
    return [_Candidate(segment.start + p, float(difference[p]), segment) for p in peaks]


def _median_difference(out: np.ndarray, segment: _Segment, half: int) -> np.ndarray:
    """Return the median-difference array d over the segment (index offset start+half)."""
    stop = segment.stop
    values = np.full(stop - segment.start, np.nan)
    for offset in range(half, stop - segment.start - half):
        i = segment.start + offset
        before = out[i - half : i]
        after = out[i : i + half]
        values[offset] = np.nanmedian(after) - np.nanmedian(before)
    return values


def _cluster_peaks(difference: np.ndarray, loc: np.ndarray, gap: int) -> list[int]:
    """Positions of the largest |d| of each cluster of above-threshold positions.

    A step makes |d| exceed the threshold over a plateau about two blocks wide around the step;
    positions closer than ``gap`` samples belong to one cluster (steps closer than two blocks
    merge, the larger wins; ties keep the first).
    """
    clusters: list[list[int]] = [[int(loc[0])]]
    for raw in loc[1:]:
        position = int(raw)
        if position - clusters[-1][-1] <= gap:
            clusters[-1].append(position)
        else:
            clusters.append([position])
    return [_plateau_centre(difference, c) for c in clusters]


def _plateau_centre(difference: np.ndarray, cluster: list[int]) -> int:
    """Middle position of the cluster samples whose |d| is within 5 % of the cluster maximum.

    The median-difference of a clean step is flat over several samples (the block medians flip
    one by one), so the centre of that plateau is the best estimate of the step sample.
    """
    sizes = np.abs(difference[cluster])
    top = [q for q, v in zip(cluster, sizes, strict=True) if v >= 0.95 * float(sizes.max())]
    return int(top[(len(top) - 1) // 2])


def _sp_candidates(
    t_s: np.ndarray,
    sp: np.ndarray,
    segment: _Segment,
    threshold: float,
) -> list[_Candidate]:
    """Find SP steps; changes closer than SP_MERGE_S are merged, size = sum.

    The event index is the first sample at the new level, i.e. the second
    sample of the first merged change.
    """
    changes = np.diff(sp[segment.start : segment.stop])
    times = t_s[segment.start : segment.stop]
    loc = np.flatnonzero(np.abs(changes) >= threshold)
    groups = _merge_sp_indices(loc, times)
    return [
        _Candidate(segment.start + group[0] + 1, float(np.sum(changes[group])), segment)
        for group in groups
    ]


def _merge_sp_indices(loc: np.ndarray, times: np.ndarray) -> list[list[int]]:
    """Group change positions whose span in time stays below SP_MERGE_S."""
    groups: list[list[int]] = []
    for raw_index in loc:
        index = int(raw_index)
        if groups and times[index] - times[groups[-1][0]] < SP_MERGE_S:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups


def _window_bounds(
    candidates: list[_Candidate],
    segments: list[_Segment],
    dt_s: float,
    limits_s: tuple[float, float],
) -> list[tuple[int, int]]:
    """Compute (i0, i1) for each candidate, clipped by segment and neighbours.

    ``i0`` keeps ``pre_s`` seconds before ``i`` but not past the segment start
    nor the previous candidate; ``i1`` keeps ``post_s`` seconds after ``i`` but
    not past the segment end nor the next candidate (its first sample).
    """
    pre_s, post_s = limits_s
    pre_samples = round(pre_s / dt_s)
    post_samples = round(post_s / dt_s)
    bounds: list[tuple[int, int]] = []
    for order, candidate in enumerate(candidates):
        previous_i = candidates[order - 1].i if order > 0 else None
        next_i = candidates[order + 1].i if order + 1 < len(candidates) else None
        i0 = max(candidate.segment.start, candidate.i - pre_samples)
        if previous_i is not None:
            i0 = max(i0, previous_i + 1)
        i1 = min(candidate.segment.stop, candidate.i + post_samples)
        if next_i is not None:
            i1 = min(i1, next_i)
        bounds.append((int(i0), int(i1)))
    return bounds


def _split_by_window_length(
    candidates: list[_Candidate],
    bounds: list[tuple[int, int]],
    t_s: np.ndarray,
) -> tuple[list[StepEvent], list[SkippedEvent]]:
    """Turn candidates into events; too-short windows become SkippedEvent."""
    events: list[StepEvent] = []
    skipped: list[SkippedEvent] = []
    for candidate, (i0, i1) in zip(candidates, bounds, strict=True):
        pre = candidate.i - i0
        post = i1 - candidate.i
        if pre < MIN_PRE_SAMPLES or post < MIN_POST_SAMPLES:
            when = float(t_s[candidate.i])
            skipped.append(SkippedEvent(candidate.i, when, WINDOW_TOO_SHORT_REASON))
        else:
            events.append(_make_event(candidate, i0, i1, float(t_s[candidate.i])))
    return events, skipped


def _make_event(candidate: _Candidate, i0: int, i1: int, event_time_s: float) -> StepEvent:
    """Assemble a StepEvent from a candidate and its window bounds."""
    is_manual = candidate.segment.mode == MANUAL_MODE
    return StepEvent(
        kind=OUT_STEP_KIND if is_manual else SP_STEP_KIND,
        i=candidate.i,
        t_s=event_time_s,
        size=candidate.size,
        i0=i0,
        i1=i1,
        mode=MANUAL_MODE_NAME if is_manual else AUTO_MODE_NAME,
        pre=candidate.i - i0,
    )
