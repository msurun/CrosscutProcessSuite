"""
Detects stretches of historian data that already contain a natural step test.

A "natural step test" is a setpoint step followed by the loop responding: the
process variable (PV) moves towards the new setpoint (SP) and settles.  The
functions in this module are pure: they take arrays and return dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# A setpoint step must be at least this many times the PV noise standard
# deviation to be distinguishable from noise.
DEFAULT_MIN_STEP_NOISE_RATIO = 4.0

# A setpoint step must also be at least this fraction of the PV span, so that
# tiny steps on a large-range signal are ignored.
DEFAULT_MIN_STEP_SPAN_FRACTION = 0.01

# Number of samples recorded before the setpoint step that are kept in the
# window, to capture the baseline before the step.
DEFAULT_PRE_SAMPLES = 20

# Upper bound on window length, in samples, to keep the identification problem
# small.
DEFAULT_MAX_SAMPLES = 3000

# Windows shorter than this many samples are discarded: too few points to fit
# an identifiable model.
DEFAULT_MIN_SAMPLES = 60

# The PV is considered "settled" when it stays within this fraction of the step
# size of the new setpoint.
DEFAULT_SETTLE_FRACTION = 0.05

# Consistency constant turning the median absolute deviation into a standard
# deviation estimate for normally distributed data.
MAD_TO_STD_FACTOR = 1.4826

# A moving average of two adjacent differences has variance 2 * sigma^2; the
# square root converts its standard deviation back to the per-sample sigma.
DIFF_VARIANCE_FACTOR = np.sqrt(2.0)

# Setpoint moves closer than this many samples belong to the same step event.
MERGE_DISTANCE_SAMPLES = 5

# Maximum fraction of NaN samples in the inputs that we are willing to
# interpolate over.
MAX_NAN_FRACTION = 0.20

# The PV must stay within the settle band for this many consecutive samples
# before it is considered settled.
SETTLE_CONSECUTIVE_SAMPLES = 10

# Padding added after the first settled sample, as a fraction of the elapsed
# response length, so the window includes a bit of steady state.
SETTLE_TAIL_FRACTION = 0.20

SETPOINT_STEP_KIND = "setpoint_step"


@dataclass(frozen=True)
class ExcitationWindow:
    """A stretch of data containing a setpoint step and the loop's response.

    Attributes:
        start: First sample index included in the window.
        stop: Sample index just past the last included sample (exclusive).
        kind: Description of the excitation, always "setpoint_step".
        step_size: Signed setpoint change in SP units.
        settled: True if the PV settled inside the settle band before the
            window ended.
    """

    start: int
    stop: int
    kind: str
    step_size: float
    settled: bool


@dataclass(frozen=True)
class WindowSettings:
    """Tuning parameters for :func:`find_excitation_windows`.

    Attributes:
        min_step_noise_ratio: Minimum step size as a multiple of PV noise.
        min_step_span_fraction: Minimum step size as a fraction of PV span.
        pre_samples: Samples of baseline kept before the step.
        max_samples: Maximum window length in samples.
        min_samples: Minimum window length in samples.
        settle_fraction: Settle band as a fraction of the step size.
    """

    min_step_noise_ratio: float = DEFAULT_MIN_STEP_NOISE_RATIO
    min_step_span_fraction: float = DEFAULT_MIN_STEP_SPAN_FRACTION
    pre_samples: int = DEFAULT_PRE_SAMPLES
    max_samples: int = DEFAULT_MAX_SAMPLES
    min_samples: int = DEFAULT_MIN_SAMPLES
    settle_fraction: float = DEFAULT_SETTLE_FRACTION


@dataclass(frozen=True)
class _StepEvent:
    """An internal setpoint step: where it starts and how big it is."""

    index: int
    step_size: float


def find_excitation_windows(
    sp: np.ndarray,
    pv: np.ndarray,
    dt_s: float,
    settings: WindowSettings | None = None,
) -> list[ExcitationWindow]:
    """Find stretches of data containing a setpoint step and the PV response.

    Args:
        sp: Setpoint samples (1-D array-like).
        pv: Process variable samples (1-D array-like), same length as ``sp``.
        dt_s: Sample period in seconds; must be positive.
        settings: Tuning parameters, see :class:`WindowSettings` (defaults when None).

    Returns:
        Non-overlapping windows sorted by ``start``. Empty if no step is found.

    Raises:
        ValueError: If shapes differ, ``dt_s`` is not positive, or too many
            samples are NaN to interpolate.
    """
    settings = settings or WindowSettings()
    sp_array, pv_array = _prepare_inputs(sp, pv, dt_s)
    step_threshold = _step_threshold(pv_array, settings)
    events = _detect_step_events(sp_array, step_threshold)
    windows = [_build_window(event, sp_array, pv_array, settings) for event in events]
    return _select_non_overlapping(windows, settings.min_samples)


def _prepare_inputs(sp: np.ndarray, pv: np.ndarray, dt_s: float) -> tuple[np.ndarray, np.ndarray]:
    """Validate inputs, cast to float, and interpolate small NaN gaps."""
    sp_array = np.asarray(sp, dtype=float)
    pv_array = np.asarray(pv, dtype=float)
    if sp_array.ndim != 1 or pv_array.ndim != 1:
        raise ValueError("sp and pv must be 1-D arrays")
    if sp_array.shape != pv_array.shape:
        raise ValueError("sp and pv must have the same length")
    if not np.isfinite(dt_s) or dt_s <= 0:
        raise ValueError(f"dt_s must be positive, got {dt_s!r}")
    if sp_array.size == 0:
        return sp_array, pv_array
    return _interpolate_nans(sp_array), _interpolate_nans(pv_array)


def _interpolate_nans(signal: np.ndarray) -> np.ndarray:
    """Linearly interpolate NaN samples; raise if too many are missing."""
    missing = ~np.isfinite(signal)
    if not missing.any():
        return signal
    if missing.mean() > MAX_NAN_FRACTION:
        raise ValueError(
            f"{missing.mean():.0%} of samples are NaN, more than the "
            f"{MAX_NAN_FRACTION:.0%} we can interpolate over"
        )
    corrected = signal.copy()
    valid_index = np.arange(signal.size)[~missing]
    corrected[missing] = np.interp(np.arange(signal.size)[missing], valid_index, signal[~missing])
    return corrected


def _estimate_noise_std(pv: np.ndarray) -> float:
    """Estimate PV noise from the median absolute deviation of differences."""
    if pv.size < 2:
        return 0.0
    differences = np.diff(pv)
    mad = float(np.median(np.abs(differences - np.median(differences))))
    return float(MAD_TO_STD_FACTOR * mad / DIFF_VARIANCE_FACTOR)


def _step_threshold(pv: np.ndarray, settings: WindowSettings) -> float:
    """Minimum setpoint change (SP units) that counts as a real step."""
    noise_floor = settings.min_step_noise_ratio * _estimate_noise_std(pv)
    span = float(np.ptp(pv)) if pv.size else 0.0
    span_floor = settings.min_step_span_fraction * span
    return max(noise_floor, span_floor)


def _detect_step_events(sp: np.ndarray, threshold: float) -> list[_StepEvent]:
    """Find setpoint changes above threshold, merging nearby moves."""
    if sp.size < 2:
        return []
    changes = np.diff(sp)
    candidate_index = np.flatnonzero(np.abs(changes) >= threshold)
    if candidate_index.size == 0:
        return []
    return _merge_event_candidates(candidate_index, changes)


def _merge_event_candidates(candidate_index: np.ndarray, changes: np.ndarray) -> list[_StepEvent]:
    """Merge changes that belong to one step (ramp or extra samples)."""
    events: list[_StepEvent] = []
    current_start = int(candidate_index[0])
    current_change = float(changes[current_start])
    for raw_index in candidate_index[1:]:
        index = int(raw_index)
        if index - current_start <= MERGE_DISTANCE_SAMPLES:
            current_change += float(changes[index])
        else:
            events.append(_StepEvent(current_start + 1, current_change))
            current_start = index
            current_change = float(changes[index])
    events.append(_StepEvent(current_start + 1, current_change))
    return events


def _build_window(
    event: _StepEvent,
    sp: np.ndarray,
    pv: np.ndarray,
    settings: WindowSettings,
) -> ExcitationWindow:
    """Build the candidate window for one setpoint step event."""
    start = max(0, event.index - settings.pre_samples)
    new_setpoint = float(sp[event.index])
    settled_at = _first_settled_index(
        pv, event.index, new_setpoint, event.step_size, settings.settle_fraction
    )
    stop = _window_stop(event.index, start, settled_at, pv.size, settings)
    return ExcitationWindow(
        start=int(start),
        stop=int(stop),
        kind=SETPOINT_STEP_KIND,
        step_size=float(event.step_size),
        settled=bool(_is_settled_before(settled_at, stop)),
    )


def _settle_band(step_size: float, settle_fraction: float) -> float:
    """Absolute PV deviation from the new setpoint that counts as settled."""
    return settle_fraction * abs(step_size)


def _first_settled_index(
    pv: np.ndarray,
    step_index: int,
    new_setpoint: float,
    step_size: float,
    settle_fraction: float,
) -> int | None:
    """Return the first index where PV enters the settle band and stays.

    Returns ``None`` if the PV never settles after ``step_index``.
    """
    band = _settle_band(step_size, settle_fraction)
    inside = np.abs(pv[step_index:] - new_setpoint) <= band
    run_ends = _run_lengths(inside) >= SETTLE_CONSECUTIVE_SAMPLES
    first_run_end = np.argmax(run_ends)
    if not run_ends[first_run_end]:
        return None
    run_length = int(_run_lengths(inside)[first_run_end])
    return int(step_index + first_run_end - run_length + 1)


def _run_lengths(mask: np.ndarray) -> np.ndarray:
    """For each position, the length of the True run ending there (0 if False)."""
    lengths = np.zeros(mask.size, dtype=int)
    for i, value in enumerate(mask):
        if value:
            lengths[i] = lengths[i - 1] + 1 if i > 0 else 1
    return lengths


def _window_stop(
    step_index: int,
    start: int,
    settled_at: int | None,
    record_end: int,
    settings: WindowSettings,
) -> int:
    """Earliest of: settled+padded, start+max, or record end."""
    candidates = [start + settings.max_samples, record_end]
    if settled_at is not None:
        elapsed = settled_at - step_index
        tail = int(round(SETTLE_TAIL_FRACTION * elapsed))
        candidates.append(settled_at + tail)
    return min(candidates)


def _is_settled_before(settled_at: int | None, stop: int) -> bool:
    """True if the settle point was reached before the window ended."""
    return settled_at is not None and settled_at < stop


def _select_non_overlapping(
    windows: list[ExcitationWindow], min_samples: int
) -> list[ExcitationWindow]:
    """Drop short windows and trim overlaps, keeping windows sorted by start."""
    kept: list[ExcitationWindow] = []
    for window in sorted(windows, key=lambda window: window.start):
        trimmed = _trim_against_previous(window, kept)
        if trimmed is not None and trimmed.stop - trimmed.start >= min_samples:
            kept.append(trimmed)
    return kept


def _trim_against_previous(
    window: ExcitationWindow, kept: list[ExcitationWindow]
) -> ExcitationWindow | None:
    """Shorten ``window`` so it does not overlap the last kept window."""
    if not kept:
        return window
    new_start = max(window.start, kept[-1].stop)
    if new_start >= window.stop:
        return None
    return ExcitationWindow(
        start=new_start,
        stop=window.stop,
        kind=window.kind,
        step_size=window.step_size,
        settled=window.settled,
    )
