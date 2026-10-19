"""Pick a representative data stretch to illustrate whole-record findings.

Findings such as `oscillating`, `poorPerformance` and `stiction` describe the
whole record, so there is no single "cause" stretch to point at. To give the
user something concrete to look at, we show the stretch where the problem is
most visible, and the UI labels it "example", not "cause".
"""

from __future__ import annotations

import numpy as np

from crosscut_loops.finding_windows import FindingWindow

WHOLE_RECORD_CODES = frozenset({"oscillating", "poorPerformance", "stiction"})

# Enough samples for the stretch to be worth looking at; also the lower clamp.
MIN_EXAMPLE_SAMPLES = 30

# Aim for this many signal periods inside the example stretch, when a period is known.
EXAMPLE_PERIODS = 6.0

# Fallback fraction of the record to show when the period is unknown.
FALLBACK_RECORD_FRACTION = 0.25


def _example_length(t_s: np.ndarray, period_s: float | None) -> int:
    """Return how many samples the example stretch should contain.

    Uses `EXAMPLE_PERIODS` periods when the period is a positive finite number,
    else a quarter of the record. The result is clamped to
    [MIN_EXAMPLE_SAMPLES, len(t_s)].
    """
    if period_s is not None and _is_usable_period(period_s):
        dt_s = float(np.median(np.diff(t_s)))
        length = round(EXAMPLE_PERIODS * period_s / dt_s)
    else:
        length = round(FALLBACK_RECORD_FRACTION * len(t_s))
    return int(np.clip(length, MIN_EXAMPLE_SAMPLES, len(t_s)))


def _is_usable_period(period_s: float | None) -> bool:
    """Return True when `period_s` is a positive finite number."""
    return period_s is not None and np.isfinite(period_s) and period_s > 0.0


def _absolute_errors(pv: np.ndarray, sp: np.ndarray) -> np.ndarray:
    """Return |pv - sp| with NaN turned into 0, so gaps never win.

    A missing sample must not be treated as a large deviation, otherwise the
    window we pick would be the one with the most gaps.
    """
    errors = np.abs(pv - sp)
    return np.asarray(np.nan_to_num(errors, nan=0.0))


def _window_error_sums(errors: np.ndarray, length: int) -> np.ndarray:
    """Return the sum of `errors` over every window of `length` samples.

    A cumulative sum lets us get all window sums in one pass instead of
    re-adding each window: the window starting at `i` sums to cumulative[i+length] - cumulative[i],
    with `cumulative` padded by a leading zero so the first window works too.
    """
    cumulative = np.concatenate(([0.0], np.cumsum(errors)))
    return cumulative[length:] - cumulative[:-length]


def _worst_start(errors: np.ndarray, length: int) -> int:
    """Return the start index of the window of `length` samples with the largest mean error.

    Ties go to the earliest window because `np.argmax` returns the first maximum.
    """
    window_sums = _window_error_sums(errors, length)
    return int(np.argmax(window_sums))


# codecheck: allow too-many-parameters (public signature used by overview and tests)
def example_window(
    code: str,
    t_s: np.ndarray,
    pv: np.ndarray,
    sp: np.ndarray,
    period_s: float | None,
) -> FindingWindow | None:
    """Pick a stretch of data to illustrate a whole-record finding.

    Returns the (start, end) times in seconds of the window with the largest
    mean |pv - sp|, or None when `code` is not a whole-record code, the record
    is empty or shorter than `MIN_EXAMPLE_SAMPLES`.

    Raises:
        ValueError: when `t_s`, `pv` and `sp` do not all have the same length.
    """
    if code not in WHOLE_RECORD_CODES:
        return None
    if not (len(t_s) == len(pv) == len(sp)):
        raise ValueError(
            f"t_s, pv and sp must have equal length, got {len(t_s)}, {len(pv)}, {len(sp)}"
        )
    if len(t_s) < MIN_EXAMPLE_SAMPLES:
        return None

    length = _example_length(t_s, period_s)
    start = _worst_start(_absolute_errors(pv, sp), length)
    return (float(t_s[start]), float(t_s[start + length - 1]))
