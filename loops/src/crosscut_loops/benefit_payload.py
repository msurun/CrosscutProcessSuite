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
    temperature in degC or a flow in m3/h. Smoothing its variability is expected to
    move the controlled variable closer to its setpoint, and that improvement has a
    money value; this function returns that value together with the numbers needed to
    audit it.

    The returned mapping is the JSON-ready body of one API response:
        "loop": the loop name, "unit": the engineering unit of the PV,
        "assumptions": what the estimator had to assume, "estimate": the benefit itself,
        "notes": human-readable caveats keyed by code, "curves": plot-ready series,
        "markdown": the same story rendered as a report fragment.

    Raises:
        ValueError: when the assumptions are inconsistent or the window has too few samples.
    """
    # Restrict the whole history to the analysis window named by the request, so every
    # number below comes from the same slice of time.
    pv = _window_of(t_s, columns[loop.pv], request)
    # Assumptions are derived from the data rather than trusted from the caller: the
    # request may leave them unset, and their units follow the PV's own unit.
    assumptions = _assumptions_of(request, pv)
    source = SOURCE_ASSUMED if measured_reduction(request) is None else SOURCE_RETUNE
    # Pure calculation: no file or network access, everything it needs is passed in.
    estimate = estimate_benefit(pv, assumptions)
    return {
        "loop": loop.name,
        "unit": loop.unit,
        # A limit of None means the caller did not cap how much variability can be
        # removed, which changes how the assumption block must be described.
        "assumptions": _assumptions_part(assumptions, request.limit is None, source, request),
        "estimate": _estimate_part(estimate),
        # _estimate_part above returns codes; here they become text the user can read,
        # so the API stays machine-friendly while the report stays understandable.
        # An unknown note keeps its own text, so a new warning in benefit.py is never lost.
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

    A benefit calculation is not run on the full lifetime of a PV plant: the caller picks an
    interval (for example a full year, or one sunny day) and only the samples in that interval
    are aggregated. The interval is given by the request as two optional timestamps, so an open
    end (start_s or end_s left at None) means "from the beginning" or "until the end".

    Parameters
    ----------
    t_s : np.ndarray
        Sample timestamps, dtype float64, in seconds on the same clock as request.start_s and
        request.end_s (UNIX epoch seconds). Strictly increasing.
    pv : np.ndarray
        AC power of the plant, dtype float64, in watt (W), sampled on t_s, i.e. pv[i] is the
        power measured at t_s[i]. Same length as t_s.
    request : BenefitRequest
        Holds the requested window as start_s and end_s (float64, seconds, UNIX epoch); either
        may be None, meaning that side of the window is unbounded.

    Returns
    -------
    np.ndarray
        The elements of pv whose timestamp falls inside the window, in the original order.
        Empty when no sample falls inside the window. A view-like new array, so the caller
        cannot modify the input through the result.
    """
    # Build the mask of samples to keep. Starting from all-True means an unbounded window
    # (both bounds None) returns the whole record without a special case, and each given bound
    # only narrows the mask further.
    keep = np.ones(len(t_s), dtype=bool)

    # Both bounds are inclusive: a sample exactly on start_s or end_s belongs to the window, so
    # the boundaries of two adjacent windows are unambiguous and no sample is counted twice.
    if request.start_s is not None:
        keep &= t_s >= request.start_s
    if request.end_s is not None:
        keep &= t_s <= request.end_s

    # Boolean-mask indexing keeps only the positions where keep is True. Because keep was built
    # over t_s, the mask and pv are aligned element by element (both sampled on the same grid).
    return pv[keep]


def _default_limit(pv: np.ndarray, side: str) -> float:
    """A placeholder limit a few standard deviations away from the mean, on the chosen side.

    Used when no explicit limit is configured: it is a rough boundary, not a statistical
    confidence bound. pv holds the process-variable samples for one signal, in the signal's
    own engineering units. side is SIDE_UPPER or the lower side and selects the sign
    of the offset, so the returned limit lies above the mean or below it.

    Returns the limit in the same unit as pv, or 0.0 when pv has no finite samples.
    """
    # Statistics ignore NaN and +/-inf samples; a single NaN would otherwise poison both
    # the mean and the standard deviation, so the mask is applied before anything else.
    finite = pv[np.isfinite(pv)]
    if finite.size == 0:
        return 0.0
    # The offset is a fixed multiple of the sample standard deviation (unit: same as pv).
    # DEFAULT_LIMIT_SIGMAS is that multiple, 4.0 by default, see DEFAULT_LIMIT_SIGMAS.
    # np.std here is the population (ddof=0) form, so the width does not depend on the sample count.
    offset = DEFAULT_LIMIT_SIGMAS * float(np.std(finite))
    # Arithmetic mean of the finite samples (unit: same as pv); it centres the placeholder band.
    mean = float(np.mean(finite))
    # Shift the band centre to the requested side: up for an upper limit, down for a lower one.
    return mean + offset if side == SIDE_UPPER else mean - offset


def _assumptions_part(
    assumptions: BenefitAssumptions, limit_is_default: bool, source: str, request: BenefitRequest
) -> dict[str, object]:
    """The assumptions that went into the number, echoed so the screen can print them.

    The front end re-displays these next to the computed benefit, so the user can see
    which inputs produced the figure and whether any of them was a fallback default.
    """
    return {
        # Upper bound on the quantity used in the calculation, in the units of the asset
        # (e.g. MW of capacity; 0 or None means unbounded depending on the caller).
        "limit": assumptions.limit,
        # True when the caller never supplied a limit and the model used its built-in one,
        # which the UI flags as an assumption worth reviewing rather than a user choice.
        "limit_is_default": limit_is_default,
        # Direction of the flow the benefit applies to, e.g. "export" or "import";
        # it decides the sign the benefit enters the optimisation with.
        "side": assumptions.side,
        # Money saved per unit per hour, in currency per unit per hour (e.g. EUR/MW/h).
        # Multiplying by the volume and the number of hours yields the benefit.
        "value_per_unit_h": assumptions.value_per_unit_h,
        # Number of standard deviations of headroom required above the expected value
        # when deciding how much capacity to commit: a higher number buys more safety
        # against forecast error (1.0 ≈ 84% confidence that the value is not exceeded).
        "margin_sigmas": assumptions.margin_sigmas,
        # Fraction of the forecast standard deviation that still contributes to the
        # constraint, in [0, 1]. Forecasting reduces uncertainty, so 0.5 means the model
        # treats only half of the raw spread as a risk.
        "std_reduction": assumptions.std_reduction,
        # Where the cut comes from: "assumed" (a slider value) or "retune_measured" (the
        # before/after spread of a retuned loop, echoed so the screen can show both numbers).
        "std_reduction_source": source,
        "std_before": request.std_before if source == SOURCE_RETUNE else None,
        "std_after": request.std_after if source == SOURCE_RETUNE else None,
    }


def _estimate_part(estimate: BenefitEstimate) -> dict[str, float | int]:
    """Flatten a BenefitEstimate into the numeric fields used downstream.

    A BenefitEstimate is the calibrated output of the measurement model: it carries
    the uncertainty of the benefit in two regimes (now and after the target change).
    Downstream code only needs the plain numbers, so this helper unpacks the object
    into a JSON-serialisable dictionary.

    Returns a dict mapping field name to its numeric value:
        mean:          expected benefit, in the same unit as the estimate (USD or score)
        std_now:       standard deviation of the benefit under current conditions, same unit
        std_target:    standard deviation of the benefit under the target conditions, same unit
        current_gap:   distance between the current mean and the target, same unit
        shift:         expected change in the mean produced by the intervention, same unit
        value_per_h:   benefit earned per unit of time, in unit per hour
        n_samples_used: number of observations the estimate was calibrated on, dimensionless

    Raises nothing; the fields are copied as-is without validation.
    """
    # One key per numeric attribute of the estimate. The dictionary is the boundary
    # between the rich domain object and the logging/serialisation layer, so the
    # key names are kept identical to the attribute names to stay easy to trace.
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

    Both curves are probability density functions of a normal (Gaussian)
    distribution, evaluated on the same horizontal grid so they can be plotted
    on top of each other.

    "now" is the sampling distribution of the estimated benefit as it stands in
    the data, with spread ``estimate.std_now``. "after" is the same distribution
    once the variance is cut to the target ``estimate.std_target`` and its mean
    is moved ``estimate.shift`` towards the decision limit, so the two curves
    can be compared at a glance: a curve that has narrowed and slid past the
    limit is the improvement the reader is hoping for.

    Returns a dict with the grid in ``"x"`` and the density values in ``"now"``
    and ``"after"``; each value is a list of floats because the result is meant
    to be JSON-serialised for the front end, not fed back into numpy.
    """
    # direction is positive for an upper limit so the mean moves up, and negative for a lower limit
    # so the mean moves down.
    direction = 1.0 if assumptions.side == SIDE_UPPER else -1.0
    mean_after = estimate.mean + direction * estimate.shift

    # Grid bounds: cover both means with CURVE_SPAN_SIGMAS times the wider ('now') standard
    # deviation on each side, so neither curve's tails are cut off.
    low = min(estimate.mean, mean_after) - CURVE_SPAN_SIGMAS * estimate.std_now
    high = max(estimate.mean, mean_after) + CURVE_SPAN_SIGMAS * estimate.std_now

    # Generate CURVE_POINTS evenly spaced x values between low and high; both densities are
    # evaluated on this same grid for plotting.
    x = np.linspace(low, high, CURVE_POINTS)
    return {
        "x": x.tolist(),
        "now": _normal(x, estimate.mean, estimate.std_now).tolist(),
        "after": _normal(x, mean_after, estimate.std_target).tolist(),
    }


def _normal(x: np.ndarray, mean: float, std: float) -> np.ndarray:
    """Normal probability density; a zero spread is widened a hair so it can be drawn."""
    spread = max(std, np.finfo(float).eps)
    density = np.exp(-0.5 * ((x - mean) / spread) ** 2) / (spread * np.sqrt(2.0 * np.pi))
    return np.asarray(density, dtype=float)
