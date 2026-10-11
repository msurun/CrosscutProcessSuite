"""JSON-ready payload of the benefit screen: estimate, assumptions, notes and distribution curves.

The estimate itself lives in ``crosscut_loops.benefit``; this module chooses the data window,
fills a default limit when the user gave none, and adds the two normal curves (PV now, PV after
the variance cut with the mean moved towards the limit) that the screen draws.
"""

from __future__ import annotations

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


def benefit_payload(
    loop: LoopTags, t_s: np.ndarray, columns: Mapping[str, np.ndarray], request: BenefitRequest
) -> dict[str, object]:
    """Estimate and describe the benefit of cutting the variability of the loop's PV.

    Raises:
        ValueError: when the assumptions are inconsistent or the window has too few samples.
    """
    pv = _window_of(t_s, columns[loop.pv], request)
    assumptions = _assumptions_of(request, pv)
    estimate = estimate_benefit(pv, assumptions)
    return {
        "loop": loop.name,
        "unit": loop.unit,
        "assumptions": _assumptions_part(assumptions, request.limit is None),
        "estimate": _estimate_part(estimate),
        "notes": [NOTE_CODES[note] for note in estimate.notes],
        "curves": _curves(estimate, assumptions),
        "markdown": render_benefit_markdown(estimate, assumptions),
    }


def _assumptions_of(request: BenefitRequest, pv: np.ndarray) -> BenefitAssumptions:
    """The request as library assumptions, with a default limit when the user gave none."""
    limit = request.limit if request.limit is not None else _default_limit(pv, request.side)
    return BenefitAssumptions(
        limit, request.side, request.value_per_unit_h, request.margin_sigmas, request.std_reduction
    )


def _window_of(t_s: np.ndarray, pv: np.ndarray, request: BenefitRequest) -> np.ndarray:
    """PV samples inside the requested window (the whole record when none is given)."""
    keep = np.ones(len(t_s), dtype=bool)
    if request.start_s is not None:
        keep &= t_s >= request.start_s
    if request.end_s is not None:
        keep &= t_s <= request.end_s
    return pv[keep]


def _default_limit(pv: np.ndarray, side: str) -> float:
    """A placeholder limit a few standard deviations away from the mean, on the chosen side."""
    finite = pv[np.isfinite(pv)]
    if finite.size == 0:
        return 0.0
    offset = DEFAULT_LIMIT_SIGMAS * float(np.std(finite))
    mean = float(np.mean(finite))
    return mean + offset if side == SIDE_UPPER else mean - offset


def _assumptions_part(assumptions: BenefitAssumptions, limit_is_default: bool) -> dict[str, object]:
    """The assumptions that went into the number, echoed so the screen can print them."""
    return {
        "limit": assumptions.limit,
        "limit_is_default": limit_is_default,
        "side": assumptions.side,
        "value_per_unit_h": assumptions.value_per_unit_h,
        "margin_sigmas": assumptions.margin_sigmas,
        "std_reduction": assumptions.std_reduction,
    }


def _estimate_part(estimate: BenefitEstimate) -> dict[str, float | int]:
    """The numeric fields of the estimate."""
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
    """Normal curves of the PV now and after the variance cut with the mean moved to the limit."""
    direction = 1.0 if assumptions.side == SIDE_UPPER else -1.0
    mean_after = estimate.mean + direction * estimate.shift
    low = min(estimate.mean, mean_after) - CURVE_SPAN_SIGMAS * estimate.std_now
    high = max(estimate.mean, mean_after) + CURVE_SPAN_SIGMAS * estimate.std_now
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
