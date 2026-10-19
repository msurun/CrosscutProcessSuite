"""Map a loop finding code to the stretch of data that caused it.

The UI lets an operator click a finding and zoom the trend to the offending
stretch. This module turns the same signals the detectors used into the
(longest) contiguous window behind each finding, in seconds since the first
sample.
"""

from __future__ import annotations

import numpy as np

from crosscut_loops.metrics import DEFAULT_MIN_FLAT_RUN, SATURATION_MARGIN_FRACTION

FindingWindow = tuple[float, float]  # (start_s, end_s) seconds since the first sample

MANUAL_MODE = 0.0  # value of the mode signal that marks manual operation
OUT_LOW = 0.0  # default actuator range: a 0-100 % output
OUT_HIGH = 100.0


# codecheck: allow too-many-parameters (public signature used by callers and tests)
def finding_window(
    code: str,
    t_s: np.ndarray,
    pv: np.ndarray,
    out: np.ndarray,
    mode: np.ndarray,
    *,
    out_low: float = OUT_LOW,
    out_high: float = OUT_HIGH,
) -> FindingWindow | None:
    """Return the longest stretch (start_s, end_s) behind ``code``, or None if there is none.

    Args:
        code: the finding code ("manual", "saturated", "flatline", or anything else).
        t_s: sample times in SECONDS since the first sample.
        pv: controlled variable (process value) samples.
        out: actuator output samples, in the actuator's own units.
        mode: controller mode samples, where MANUAL_MODE marks manual operation.
        out_low: bottom of the actuator output range, in the same units as ``out``.
        out_high: top of the actuator output range; the saturation margin is a fraction
            of the span ``out_high - out_low``, so a 4-20 mA loop needs out_low=4.0.

    Returns:
        (start_s, end_s) of the longest run of samples matching ``code``, both bounds
        inclusive of the first and last sample of the run. None when the code has no
        window (unknown codes), when no run exists, or when the arrays are empty.

    Raises:
        ValueError: if the four signal arrays do not all have the same length.
    """
    t_s, pv, out, mode = _as_checked_arrays(t_s, pv, out, mode)
    if len(t_s) == 0:
        return None

    mask: np.ndarray | None
    if code == "saturated":
        mask = _saturated_mask(out, out_low, out_high)
    else:
        mask = _finding_mask(code, pv, mode)
    return _window_of_mask(t_s, mask)


def _window_of_mask(t_s: np.ndarray, mask: np.ndarray | None) -> FindingWindow | None:
    """Time bounds (start_s, end_s) of the longest True run in ``mask``, or None if none."""
    if mask is None:
        return None
    run = _longest_true_run(mask)
    if run is None:
        return None
    first, last = run
    return (float(t_s[first]), float(t_s[last]))


def _as_checked_arrays(
    t_s: np.ndarray,
    pv: np.ndarray,
    out: np.ndarray,
    mode: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert the four signals to float arrays and check that they have equal length.

    Raises:
        ValueError: if the four signal arrays do not all have the same length.
    """
    t_s = np.asarray(t_s, dtype=float)
    pv = np.asarray(pv, dtype=float)
    out = np.asarray(out, dtype=float)
    mode = np.asarray(mode, dtype=float)
    if not (len(t_s) == len(pv) == len(out) == len(mode)):
        raise ValueError("t_s, pv, out and mode must all have the same length")
    return t_s, pv, out, mode


def _finding_mask(code: str, pv: np.ndarray, mode: np.ndarray) -> np.ndarray | None:
    """Boolean mask of samples belonging to ``code``, or None when the code has no window.

    NaN never belongs to a run: every comparison against NaN is False, so the
    mask keeps those samples False.
    """
    if code == "manual":
        return np.asarray(mode == MANUAL_MODE)
    if code == "flatline":
        return _flatline_mask(pv)
    return None


def _saturated_mask(out: np.ndarray, out_low: float, out_high: float) -> np.ndarray:
    """True for samples within SATURATION_MARGIN_FRACTION of either end of the output range.

    The margin scales with the span, so a 4-20 mA output (span 16) gets a 0.08 margin while
    a 0-100 % valve gets 0.5. NaN compares False and therefore never counts as saturated.
    """
    margin = SATURATION_MARGIN_FRACTION * (out_high - out_low)
    return (out <= out_low + margin) | (out >= out_high - margin)


def _flatline_mask(pv: np.ndarray) -> np.ndarray:
    """True for every sample inside a run of identical pv values of at least DEFAULT_MIN_FLAT_RUN.

    The sample where the repeated value first appears counts as part of the run.
    """
    # A run starts where the value changes from the previous sample. Prepending True
    # marks the first sample as a start (it has no predecessor). Appending len(pv) below
    # supplies the end of the last run, so the diff yields one length per run.
    run_starts = np.flatnonzero(np.append(True, pv[1:] != pv[:-1]))
    run_lengths = np.diff(np.append(run_starts, len(pv)))
    long_runs = run_lengths >= DEFAULT_MIN_FLAT_RUN
    # Mark every sample of each long run: indices start .. start + length - 1.
    mask = np.zeros(len(pv), dtype=bool)
    for start, length in zip(run_starts[long_runs], run_lengths[long_runs], strict=True):
        mask[start : start + length] = True
    return mask


def _longest_true_run(mask: np.ndarray) -> tuple[int, int] | None:
    """First and last index (inclusive) of the longest run of True, or None if there is none.

    The mask is padded with one False on each side, so every True run is bounded by
    transitions in the padded array and the diff trick below finds them all.
    """
    padded = np.concatenate(([False], mask, [False]))
    transitions = np.flatnonzero(padded[1:] != padded[:-1])
    if len(transitions) == 0:
        return None
    starts = transitions[::2]
    lengths = transitions[1::2] - starts
    best = int(np.argmax(lengths))
    first = int(starts[best])
    return first, first + int(lengths[best]) - 1
