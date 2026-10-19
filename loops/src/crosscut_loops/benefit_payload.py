"""JSON-ready payload of the benefit screen: estimate, assumptions, notes and distribution curves.

The estimate itself lives in ``crosscut_loops.benefit``; this module chooses the data window,
fills a default limit when the user gave none, and adds the two normal curves (PV now, PV after
the variance cut with the mean moved towards the limit) that the screen draws.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from crosscut_loops.benefit import (
    NOTE_BEYOND_LIMIT,
    NOTE_NEAR_LIMIT,
    NOTE_NO_VALUE,
    SIDE_UPPER,
    BenefitAssumptions,
    BenefitEstimate,
    estimate_benefit,
    render_benefit_markdown,
)
from crosscut_loops.overview import LoopTags

DEFAULT_LIMIT_SIGMAS = 4.0  # without a user limit: this many standard deviations from the mean
CURVE_SPAN_SIGMAS = 4.0  # the curves cover the mean plus/minus this many standard deviations
CURVE_POINTS = 120
NOTE_CODES = {
    NOTE_BEYOND_LIMIT: "beyond_limit",
    NOTE_NEAR_LIMIT: "near_limit",
    NOTE_NO_VALUE: "no_value",
}


@dataclass(frozen=True)
class BenefitRequest:
    """The user's assumptions and the data window; ``limit=None`` asks for a default limit."""

    limit: float | None = None
    side: str = SIDE_UPPER
    value_per_unit_h: float = 0.0
    margin_sigmas: float = 2.0
    std_reduction: float = 0.5
    start_s: float | None = None
    end_s: float | None = None
    # Measured PV standard deviations before and after a retune, in PV units. When both are
    # given they replace the assumed ``std_reduction``: reduction = 1 - after / before.
    std_before: float | None = None
    std_after: float | None = None


SOURCE_ASSUMED = "assumed"
SOURCE_RETUNE = "retune_measured"
MAX_MEASURED_REDUCTION = 0.99  # a measured cut is capped: the estimator needs a non-zero spread


def measured_reduction(request: BenefitRequest) -> float | None:
    """Variability cut measured by a retune, or None when the request carries no measurement.

    The cut is 1 - std_after / std_before, limited to [0, MAX_MEASURED_REDUCTION]: a retune
    that made the loop worse counts as no benefit, never as a negative one.
    """
    before, after = request.std_before, request.std_after
    if before is None or after is None or not math.isfinite(before + after) or before <= 0.0:
        return None
    cut = 1.0 - after / before
    return min(max(cut, 0.0), MAX_MEASURED_REDUCTION)


def benefit_payload(
    loop: LoopTags, t_s: np.ndarray, columns: Mapping[str, np.ndarray], request: BenefitRequest
) -> dict[str, object]:
    """Estimate and describe the benefit of cutting the variability of the loop's PV.

    The PV (process variable) is the measurement the loop controls, for example a
    temperature in degC or a flow in m3/h. Tightening its spread lets the mean move closer to
    an operating limit with the same margin, and that room has a money value; this function
    returns that value together with the numbers needed to audit it.

    The returned mapping is the JSON-ready body of one API response:
        "loop": the loop name, "unit": the engineering unit of the PV,
        "assumptions": what the estimator had to assume, "estimate": the benefit itself,
        "notes": warning codes (see NOTE_CODES), "curves": plot-ready series,
        "markdown": the same story rendered as a report fragment.

    Raises:
        ValueError: when the assumptions are inconsistent or the window has too few samples.
    """
    # Restrict the whole history to the analysis window named by the request, so every
    # number below comes from the same slice of time.
    pv = _window_of(t_s, columns[loop.pv], request)
    # The request may leave the limit unset (a default is derived from the data) and may carry
    # a measured before/after spread that replaces the assumed std_reduction.
    assumptions = _assumptions_of(request, pv)
    source = SOURCE_ASSUMED if measured_reduction(request) is None else SOURCE_RETUNE
    # Pure calculation: no file or network access, everything it needs is passed in.
    estimate = estimate_benefit(pv, assumptions)
    return {
        "loop": loop.name,
        "unit": loop.unit,
        # A limit of None means the caller gave none, so a default one was derived; the
        # assumption block says so.
        "assumptions": _assumptions_part(assumptions, request.limit is None, source, request),
        "estimate": _estimate_part(estimate),
        # The notes of the estimate become short codes the front end can translate. An
        # unknown note keeps its own text, so a new warning in benefit.py is never lost.
        "notes": [NOTE_CODES.get(note, str(note)) for note in estimate.notes],
        "curves": _curves(estimate, assumptions),
        "markdown": render_benefit_markdown(estimate, assumptions),
    }


def _assumptions_of(request: BenefitRequest, pv: np.ndarray) -> BenefitAssumptions:
    """The request as library assumptions, with a default limit when the user gave none."""
    limit = request.limit if request.limit is not None else _default_limit(pv, request.side)
    measured = measured_reduction(request)
    reduction = request.std_reduction if measured is None else measured
    return BenefitAssumptions(
        limit, request.side, request.value_per_unit_h, request.margin_sigmas, reduction
    )


def _window_of(t_s: np.ndarray, pv: np.ndarray, request: BenefitRequest) -> np.ndarray:
    """PV samples inside the requested window (the whole record when none is given).

    The window is given by the request as two optional timestamps; an open end (start_s or
    end_s left at None) means "from the beginning" or "until the end".

    Parameters
    ----------
    t_s : np.ndarray
        Sample timestamps in seconds, on the same clock as request.start_s and request.end_s;
        increasing.
    pv : np.ndarray
        Process variable samples in the loop's engineering unit; pv[i] belongs to t_s[i], so
        both have the same length.
    request : BenefitRequest
        Holds the requested window as start_s and end_s in seconds; either may be None.

    Returns
    -------
    np.ndarray
        The elements of pv whose timestamp falls inside the window, in the original order;
        empty when no sample falls inside. A new array (boolean-mask indexing copies), so the
        caller cannot modify the input through the result.
    """
    # Build the mask of samples to keep. Starting from all-True means an unbounded window
    # returns the whole record without a special case; each given bound only narrows the mask.
    keep = np.ones(len(t_s), dtype=bool)

    # Both bounds are inclusive: a sample exactly on start_s or end_s belongs to the window.
    if request.start_s is not None:
        keep &= t_s >= request.start_s
    if request.end_s is not None:
        keep &= t_s <= request.end_s

    # keep was built over t_s, so it is aligned element by element with pv.
    return pv[keep]


def _default_limit(pv: np.ndarray, side: str) -> float:
    """A placeholder limit a few standard deviations away from the mean, on the chosen side.

    Used when no explicit limit is given: it is a rough boundary, not a statistical
    confidence bound. pv holds the process-variable samples in engineering units. side is
    SIDE_UPPER or the lower side and selects the sign of the offset, so the returned limit lies
    above the mean or below it.

    Returns the limit in the same unit as pv, or 0.0 when pv has no finite samples.
    """
    # Statistics ignore NaN and +/-inf samples; a single NaN would otherwise poison both
    # the mean and the standard deviation, so the mask is applied before anything else.
    finite = pv[np.isfinite(pv)]
    if finite.size == 0:
        return 0.0
    # The offset is DEFAULT_LIMIT_SIGMAS standard deviations (unit: same as pv). np.std is the
    # population (ddof=0) form here; benefit.estimate_benefit uses ddof=1 for its own statistics.
    offset = DEFAULT_LIMIT_SIGMAS * float(np.std(finite))
    # Mean of the finite samples (unit: same as pv); the limit is placed relative to it.
    mean = float(np.mean(finite))
    # Above the mean for an upper limit, below it for a lower one.
    return mean + offset if side == SIDE_UPPER else mean - offset


def _assumptions_part(
    assumptions: BenefitAssumptions, limit_is_default: bool, source: str, request: BenefitRequest
) -> dict[str, object]:
    """The assumptions that went into the number, echoed so the screen can print them.

    The front end shows these next to the computed benefit, so the user can see which
    inputs produced the figure and whether the limit was a default.
    """
    return {
        # Limit of the PV in engineering units: the side of the process mean beyond which the
        # operation is not allowed to go.
        "limit": assumptions.limit,
        # True when the user gave no limit and a default one (DEFAULT_LIMIT_SIGMAS standard
        # deviations from the mean) was used; the UI flags it as an assumption to review.
        "limit_is_default": limit_is_default,
        # "upper" or "lower": on which side of the mean the limit sits.
        "side": assumptions.side,
        # Money value of one PV unit of room for one hour (currency per PV unit per hour).
        "value_per_unit_h": assumptions.value_per_unit_h,
        # Margin kept between the process mean and the limit, in standard deviations.
        "margin_sigmas": assumptions.margin_sigmas,
        # Fraction of the current PV standard deviation that is removed, in [0, 1): the target
        # standard deviation is (1 - std_reduction) times the current one.
        "std_reduction": assumptions.std_reduction,
        # Where the cut comes from: "assumed" (a slider value) or "retune_measured" (the
        # before/after spread of a retuned loop, echoed so the screen can show both numbers).
        "std_reduction_source": source,
        "std_before": request.std_before if source == SOURCE_RETUNE else None,
        "std_after": request.std_after if source == SOURCE_RETUNE else None,
    }


def _estimate_part(estimate: BenefitEstimate) -> dict[str, float | int]:
    """Flatten a BenefitEstimate into the numeric fields used downstream.

    Returns a dict mapping field name to its numeric value (PV = the loop's process variable):
        mean:          mean of the PV samples used
        std_now:       standard deviation of the PV samples, PV units
        std_target:    standard deviation aimed for after the reduction, PV units
        current_gap:   signed room between the mean and the limit; negative = already beyond it
        shift:         room the mean could move towards the limit, PV units, never negative
        value_per_h:   shift converted to money per hour (0.0 without a value per unit)
        n_samples_used: number of finite samples that went into the statistics

    Raises nothing; the fields are copied as they are.
    """
    # The key names are kept identical to the attribute names to stay easy to trace.
    return {
        "mean": estimate.mean,
        "std_now": estimate.std_now,
        "std_target": estimate.std_target,
        "current_gap": estimate.current_gap,
        "shift": estimate.shift,
        "value_per_h": estimate.value_per_h,
        "n_samples_used": estimate.n_samples_used,
    }


def _curves(estimate: BenefitEstimate, assumptions: BenefitAssumptions) -> dict[str, list[float]]:
    """Sample the two normal curves drawn on the benefit chart.

    Both curves are normal probability density functions of the PV, evaluated on the same
    horizontal grid so they can be plotted on top of each other.

    "now" has the current mean and spread (``estimate.mean``, ``estimate.std_now``). "after"
    has the reduced spread ``estimate.std_target`` and a mean moved ``estimate.shift`` towards
    the limit, so a curve that has narrowed and slid towards the limit shows the room gained.

    Returns a dict with the grid in ``"x"`` (PV units) and the density values in ``"now"`` and
    ``"after"``; plain lists of floats because the result is JSON-serialised for the front end.
    """
    # +1 for an upper limit (the mean moves up towards it), -1 for a lower limit.
    direction = 1.0 if assumptions.side == SIDE_UPPER else -1.0
    mean_after = estimate.mean + direction * estimate.shift

    # Grid bounds: cover both means with CURVE_SPAN_SIGMAS times the wider ('now') standard
    # deviation on each side, so neither curve's tails are cut off.
    low = min(estimate.mean, mean_after) - CURVE_SPAN_SIGMAS * estimate.std_now
    high = max(estimate.mean, mean_after) + CURVE_SPAN_SIGMAS * estimate.std_now

    # CURVE_POINTS evenly spaced PV values between low and high; both densities use this grid.
    grid = np.linspace(low, high, CURVE_POINTS)
    return {
        "x": grid.tolist(),
        "now": _normal(grid, estimate.mean, estimate.std_now).tolist(),
        "after": _normal(grid, mean_after, estimate.std_target).tolist(),
    }


def _normal(grid: np.ndarray, mean: float, std: float) -> np.ndarray:
    """Normal probability density; a zero spread is widened a hair so it can be drawn."""
    spread = max(std, np.finfo(float).eps)
    density = np.exp(-0.5 * ((grid - mean) / spread) ** 2) / (spread * np.sqrt(2.0 * np.pi))
    return np.asarray(density, dtype=float)
