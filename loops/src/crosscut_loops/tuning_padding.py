"""Padding of a suggested test window for an integrating (level) loop.

An integrating process needs a long quiet lead before the first OUT move (its slope must be known
at rest) and some settling after the last one. The padding extends the window inside the same
continuous manual stretch and never leaves the record.
"""

from __future__ import annotations

import numpy as np

from crosscut_loops.tuning_view import MANUAL_MODE, MOVE_STEP_PCT

LEAD_SHARE = 0.3  # aimed share of the extended window that is quiet lead before the first move
MIN_AFTER_S = 300.0  # aimed time kept after the last OUT move, in seconds


def pad_integrating_window(
    t_s: np.ndarray, mode: np.ndarray, out: np.ndarray, window: tuple[float, float]
) -> tuple[float, float]:
    """Extend ``window`` (start_s, end_s) so the lead and the settling are inside it.

    The limits are the first and last sample of the manual run that holds the window. Returns the
    window unchanged when it holds no OUT move or no manual sample.
    """
    inside = np.flatnonzero((t_s >= window[0]) & (t_s <= window[1]))
    if len(inside) == 0 or mode[inside[0]] != MANUAL_MODE:
        return window
    moved = np.flatnonzero(np.abs(np.diff(out[inside])) > MOVE_STEP_PCT)
    if len(moved) == 0:
        return window
    first = float(t_s[inside[0] + moved[0]])
    last = float(t_s[inside[0] + moved[-1] + 1])
    low, high = _manual_run_bounds(t_s, mode, int(inside[0]))
    end = min(high, max(window[1], last + MIN_AFTER_S))
    wanted = (first - LEAD_SHARE * end) / (1.0 - LEAD_SHARE)
    return max(low, min(window[0], wanted)), end


def _manual_run_bounds(t_s: np.ndarray, mode: np.ndarray, index: int) -> tuple[float, float]:
    """Times of the first and last sample of the manual run that contains sample ``index``."""
    manual = mode == MANUAL_MODE
    first = index
    while first > 0 and manual[first - 1]:
        first -= 1
    last = index
    while last < len(manual) - 1 and manual[last + 1]:
        last += 1
    return float(t_s[first]), float(t_s[last])
