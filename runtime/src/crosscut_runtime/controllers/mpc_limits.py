"""Engine limits of an MPC controller from the catalogue variables and a reference point.

The engine works on deviations from one operating point; the runtime takes that point from the
live values when the controller starts (bumpless entry) and shifts the catalogue ranges by it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from crosscut_mpc.config import Limits
from crosscut_mpc.economics import Economics

FUNNEL_END_SHARE = 0.1  # a CV with a target is pulled to within this share of its range


class LimitsError(ValueError):
    """A variable lacks the range or step limit the engine needs."""


def range_of(var: Mapping[str, Any]) -> tuple[float, float]:
    """Operator range, else engineering range, of a variable."""
    limits = var.get("limits", {})
    bounds = limits.get("operator") or limits.get("eng")
    if bounds is None:
        raise LimitsError(f"{var['id']!r} needs limits.operator or limits.eng")
    return float(bounds["lo"]), float(bounds["hi"])


def _mv_steps(var: Mapping[str, Any], cycle_s: float) -> tuple[float, float]:
    """``(move_max, rate_max)`` of an MV; the rate defaults to the move limit per cycle."""
    limits = var.get("limits", {})
    if limits.get("move_max") is None:
        raise LimitsError(f"MV {var['id']!r} requires limits.move_max")
    move = float(limits["move_max"])
    rate = limits.get("rate_max")
    return move, float(rate) if rate is not None else move / cycle_s


def clamp_move(
    var: Mapping[str, Any], current: float, proposed: float, cycle_s: float,
    last: float | None = None,
) -> float:
    """The proposal cut to the step windows and the range.

    The solver certifies its plan only within a small tolerance, and a proposal may not have been
    applied: the step window is the overlap of ``current +- step`` and ``last +- step`` (the
    read-back window alone when they do not overlap). The result lies in the range; a setpoint
    outside the range only approaches it by one step.
    """
    move, rate = _mv_steps(var, cycle_s)
    step = min(move, rate * cycle_s)
    lo, hi = current - step, current + step
    if last is not None and max(lo, last - step) <= min(hi, last + step):
        lo, hi = max(lo, last - step), min(hi, last + step)
    r_lo, r_hi = range_of(var)
    if hi < r_lo:
        return hi
    if lo > r_hi:
        return lo
    return min(max(proposed, max(lo, r_lo)), min(hi, r_hi))


def build_limits(
    variables: Mapping[str, Mapping[str, Any]],
    ids: tuple[Sequence[str], Sequence[str]],
    ref: tuple[np.ndarray, np.ndarray],
    timing: tuple[float, int],
) -> Limits:
    """Limits in deviations from ``ref`` = (MV reference, CV reference); timing = (cycle_s, Np)."""
    mv_ids, cv_ids = ids
    cycle_s, horizon = timing
    mv = [range_of(variables[i]) for i in mv_ids]
    cv = [range_of(variables[i]) for i in cv_ids]
    steps = [_mv_steps(variables[i], cycle_s) for i in mv_ids]
    span = np.array([hi - lo for lo, hi in cv])
    targeted = np.array([variables[i].get("target") is not None for i in cv_ids])
    funnel_end = np.where(targeted, FUNNEL_END_SHARE * span, span)
    mv_ref, cv_ref = ref
    return Limits(
        np.array([lo for lo, _ in mv]) - mv_ref, np.array([hi for _, hi in mv]) - mv_ref,
        np.array([lo for lo, _ in cv]) - cv_ref, np.array([hi for _, hi in cv]) - cv_ref,
        np.array([float(variables[i].get("priority", 1)) for i in cv_ids]),
        np.array([m for m, _ in steps]), np.array([r for _, r in steps]),
        span / (horizon * cycle_s), span, funnel_end,
    )


def build_economics(
    block: Mapping[str, Any] | None,
    variables: Mapping[str, Mapping[str, Any]],
    ids: tuple[Sequence[str], Sequence[str]],
    ref: tuple[np.ndarray, np.ndarray],
) -> Economics | None:
    """Engine economics of a catalogue ``economics`` block; ``None`` when there is none.

    ``cv_value`` is [currency/(CV unit*h)], ``mv_cost`` [currency/(MV unit*h)], soft limits are
    absolute engineering values and are shifted by ``ref`` like the other limits. A variable
    without an entry has value 0 and no soft limit.
    """
    if not block:
        return None
    mv_ids, cv_ids = ids
    mv_ref, cv_ref = ref
    value, cost = block.get("cv_value", {}), block.get("mv_cost", {})
    soft = block.get("soft_limits", {})

    def bounds(names: Sequence[str], reference: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        lo = [float(soft.get(n, {}).get("lo", -np.inf)) for n in names]
        hi = [float(soft.get(n, {}).get("hi", np.inf)) for n in names]
        return np.array(lo) - reference, np.array(hi) - reference

    cv_lo, cv_hi = bounds(cv_ids, cv_ref)
    mv_lo, mv_hi = bounds(mv_ids, mv_ref)
    return Economics(
        np.array([float(value.get(i, 0.0)) for i in cv_ids]),
        np.array([float(cost.get(i, 0.0)) for i in mv_ids]), cv_lo, cv_hi, mv_lo, mv_hi,
    )
