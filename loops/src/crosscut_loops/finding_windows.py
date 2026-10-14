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

MANUAL_MODE = 0.0
OUT_LOW = 0.0
OUT_HIGH = 100.0


# codecheck: allow too-many-parameters (public signature used by callers and tests)
def finding_window(
    code: str,
    t_s: np.ndarray,
    pv: np.ndarray,
    out: np.ndarray,
    mode: np.ndarray,
) -> FindingWindow | None:
    """Return the longest stretch (start_s, end_s) behind ``code``, or None if there is none.

    Args:
        code: the finding code ("manual", "saturated", "flatline", or anything else).
        t_s: sample times in SECONDS since the first sample.
        pv: controlled variable (process value) samples.
        out: actuator output samples, in the actuator's own units.
        mode: controller mode samples, where MANUAL_MODE marks manual operation.

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

    mask = _finding_mask(code, pv, out, mode)
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


def _finding_mask(
    code: str, pv: np.ndarray, out: np.ndarray, mode: np.ndarray
) -> np.ndarray | None:
    """Boolean mask of samples belonging to ``code``, or None when the code has no window.

    NaN never belongs to a run: every comparison against NaN is False, so the
    mask keeps those samples False.
    """
    if code == "manual":
        return np.asarray(mode == MANUAL_MODE)
    if code == "saturated":
        margin = SATURATION_MARGIN_FRACTION * (OUT_HIGH - OUT_LOW)
        return (out <= OUT_LOW + margin) | (out >= OUT_HIGH - margin)
    if code == "flatline":
        return _flatline_mask(pv)
    return None


def _flatline_mask(pv: np.ndarray) -> np.ndarray:
    """True for every sample inside a run of identical pv values of at least DEFAULT_MIN_FLAT_RUN.

    The sample where the repeated value first appears counts as part of the run.
    """
    # A run starts where the value changes from the previous sample. Prepending True
    # marks the first sample as a start (it has no predecessor) and gives every run a
    # leading boundary, so the diff below yields one length per run.
    run_starts = np.flatnonzero(np.append(True, pv[1:] != pv[:-1]))
    run_lengths = np.diff(np.append(run_starts, len(pv)))
    long_runs = run_lengths >= DEFAULT_MIN_FLAT_RUN
    # The mask is built by walking the long runs back to their start index.
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
