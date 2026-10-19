"""
Guided valve stroke test: operator procedure, plan, and analysis of the PV response.

Nothing writes to a DCS; the plan is a procedure the operator executes. Deadband and
resolution are estimated from the PV response using definitions after ANSI/ISA-75.25.01
and ISA-TR75.25.02 as recalled (the standards were not read).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import numpy as np

# Analysis constants (units: % of output span unless noted)
CHANGE_FRACTION = 0.4          # fraction of smallest step below which OP change is noise
NOISE_SIGMAS = 3.0             # detection threshold multiplier for PV noise
MOVE_STEP_FRACTION = 0.5       # fraction of |K| * smallest step used in the moved test
RESOLUTION_SHARE = 0.75        # share of steps that must move to certify resolution
STEADY_FRACTION = 1 / 3        # last third of each segment used for steady values
MAD_TO_STD = 1.4826            # MAD to standard deviation for Gaussian noise


@dataclass(frozen=True)
class TestStep:
    """One operator step in a stroke test plan.

    Attributes:
        index: zero-based step number in the whole plan.
        op_target: output target in % of span.
        direction: +1 for up, -1 for down.
        size: nominal step size in % of span.
        dwell_s: dwell time in seconds.
        after_reversal: True if this is the first step of a leg after the first leg
            (i.e., immediately follows a direction change).
    """

    index: int
    op_target: float
    direction: int
    size: float
    dwell_s: int
    after_reversal: bool


@dataclass(frozen=True)
class StrokePlan:
    """A complete stroke test plan.

    Attributes:
        op_start: starting output in % of span.
        step_sizes: tuple of step sizes in % of span, one per leg group.
        steps_per_leg: tuple of leg lengths, one per step size.
        dwell_s: dwell time in seconds for every step.
        op_low: lower output limit in % of span.
        op_high: upper output limit in % of span.
        pv_band: abort band in PV units; None means no abort check.
        steps: tuple of TestStep, one per step in the whole plan.
    """

    op_start: float
    step_sizes: tuple[float, ...]
    steps_per_leg: tuple[int, ...]
    dwell_s: int
    op_low: float
    op_high: float
    pv_band: float | None
    steps: tuple[TestStep, ...]


@dataclass(frozen=True)
class SegmentMove:
    """A single OP step and the resulting PV change, as detected in the record.

    Attributes:
        start_index: sample index where the OP change starts.
        op_change: steady OP change in % of span (segment j minus segment j-1).
        pv_change: steady PV change in PV units (segment j minus segment j-1).
        moved: True if the valve visibly moved (see spec step 4).
        size: plan step size in % of span nearest to |op_change|.
        after_reversal: True if this step immediately follows a direction change.
    """

    start_index: int
    op_change: float
    pv_change: float
    moved: bool
    size: float
    after_reversal: bool


@dataclass(frozen=True)
class StrokeResult:
    """Results of a stroke test analysis.

    Attributes:
        deadband: estimated deadband in % of span, or None if not identifiable.
        deadband_bracket: (lower, upper) bracket in % of span for the reported deadband,
            or None if no bracket exists.
        deadband_lower_bound: largest leg travel without a move, as a lower bound in %
            of span; None if every leg had a move.
        resolution_le: largest step size in % of span that certifies resolution (<=), or
            None if no size meets the share threshold.
        gain: process gain K = dPV/dOP in PV units per % of span, or None if not
            identifiable.
        sigma_pv: estimated PV noise standard deviation in PV units.
        moves: list of SegmentMove, one per detected step, in order.
        pv_left_band: True if the abort band was violated.
        reason: human-readable explanation when a result is incomplete; "" if complete.
    """

    deadband: float | None
    deadband_bracket: tuple[float, float] | None
    deadband_lower_bound: float | None
    resolution_le: float | None
    gain: float | None
    sigma_pv: float
    moves: list[SegmentMove] = field(default_factory=list)
    pv_left_band: bool = False
    reason: str = ""


def _validate_plan_inputs(
    op_start: float,
    step_sizes: Sequence[float],
    steps_per_leg: Sequence[int],
    dwell_s: int,
    op_low: float,
    op_high: float,
) -> None:
    """Raise ValueError if plan inputs are inconsistent or out of range."""
    if len(step_sizes) != len(steps_per_leg):
        raise ValueError("step_sizes and steps_per_leg must have the same length")
    if dwell_s <= 0:
        raise ValueError("dwell_s must be positive")
    if op_low >= op_high:
        raise ValueError("op_low must be strictly less than op_high")
    if not op_low <= op_start <= op_high:
        raise ValueError("op_start must be within [op_low, op_high]")
    for size in step_sizes:
        if size <= 0:
            raise ValueError(f"step size must be positive, got {size}")


def _build_steps(
    op_start: float,
    step_sizes: Sequence[float],
    steps_per_leg: Sequence[int],
    dwell_s: int,
    op_low: float,
    op_high: float,
) -> tuple[tuple[TestStep, ...], float]:
    """Build all TestStep objects and return them with the final OP.

    Raises ValueError if any target leaves [op_low, op_high].
    """
    steps: list[TestStep] = []
    current_op = op_start
    index = 0
    for size, leg_length in zip(step_sizes, steps_per_leg, strict=True):
        # Three legs per size: up, down, up (two reversals).
        directions = (1, -1, 1)
        for leg_num, direction in enumerate(directions):
            for _ in range(leg_length):
                target = current_op + direction * size
                if not op_low <= target <= op_high:
                    raise ValueError(
                        f"step {index} target {target:.2f} outside [{op_low}, {op_high}]"
                    )
                after_reversal = leg_num > 0
                steps.append(
                    TestStep(
                        index=index,
                        op_target=target,
                        direction=direction,
                        size=size,
                        dwell_s=dwell_s,
                        after_reversal=after_reversal,
                    )
                )
                current_op = target
                index += 1
    return tuple(steps), current_op


def plan_stroke_test(
    op_start: float,
    dwell_s: int,
    op_low: float = 0.0,
    op_high: float = 100.0,
    pv_band: float | None = None,
    step_sizes: Sequence[float] = (1.0, 0.25),
    steps_per_leg: Sequence[int] = (4, 12),
) -> StrokePlan:
    """Create a stroke test plan.

    For each step size s with leg length m, the legs are up m steps, down m steps, up m
    steps (two reversals per size), starting from the OP reached by the previous size.

    Args:
        op_start: starting output in % of span.
        dwell_s: dwell time in seconds for every step.
        op_low: lower output limit in % of span.
        op_high: upper output limit in % of span.
        pv_band: abort band in PV units; None means no abort check.
        step_sizes: tuple of step sizes in % of span.
        steps_per_leg: tuple of leg lengths, one per step size.

    Returns:
        StrokePlan with all steps.

    Raises:
        ValueError: if inputs are inconsistent or any target leaves [op_low, op_high].
    """
    sizes = tuple(float(s) for s in step_sizes)
    lengths = tuple(int(m) for m in steps_per_leg)
    _validate_plan_inputs(op_start, sizes, lengths, dwell_s, op_low, op_high)
    steps, _ = _build_steps(op_start, sizes, lengths, dwell_s, op_low, op_high)
    return StrokePlan(
        op_start=op_start,
        step_sizes=sizes,
        steps_per_leg=lengths,
        dwell_s=dwell_s,
        op_low=op_low,
        op_high=op_high,
        pv_band=pv_band,
        steps=steps,
    )


def procedure_text(plan: StrokePlan) -> list[str]:
    """Return numbered operator instructions for executing the stroke test.

    Args:
        plan: the stroke test plan.

    Returns:
        List of strings, each a numbered step in plain English.
    """
    # The abort rule comes before the first move, so the operator knows it while stepping.
    abort = "If anything looks wrong at any time, abort: return the output to "
    abort += f"{plan.op_start:.2f}% and put the loop back in AUTO."
    if plan.pv_band is not None:
        abort = f"If the PV moves more than {plan.pv_band:.2f} from its starting value, " + abort
    texts = ["Put the loop in MANUAL.", abort]
    texts.append(f"Set the output to {plan.op_start:.2f}% and wait {plan.dwell_s} seconds.")
    texts += [
        f"Set the output to {step.op_target:.2f}% and wait {step.dwell_s} seconds."
        for step in plan.steps
    ]
    texts.append(f"Return the output to {plan.op_start:.2f}% and put the loop back in AUTO.")
    return [f"{number}. {text}" for number, text in enumerate(texts, start=1)]


def _find_change_points(op: np.ndarray, min_step: float) -> np.ndarray:
    """Return indices where the OP changes by more than CHANGE_FRACTION * min_step."""
    diff = np.abs(np.diff(op))
    change_indices = np.where(diff > CHANGE_FRACTION * min_step)[0] + 1
    return change_indices


def _steady_value(segment: np.ndarray, fraction: float = STEADY_FRACTION) -> float:
    """Return the median of the last `fraction` of a segment."""
    n = len(segment)
    start = n - max(1, int(n * fraction))
    return float(np.median(segment[start:]))


def _segment_steady_pv(pv: np.ndarray, change_points: np.ndarray) -> list[float]:
    """Return steady PV for each segment defined by change points."""
    boundaries = [0] + list(change_points) + [len(pv)]
    steady_values: list[float] = []
    for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
        steady_values.append(_steady_value(pv[start:end]))
    return steady_values


def _estimate_sigma_pv(pv: np.ndarray, change_points: np.ndarray) -> float:
    """Estimate PV noise std via MAD of segment residuals, scaled by MAD_TO_STD."""
    boundaries = [0] + list(change_points) + [len(pv)]
    residuals: list[float] = []
    for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
        segment = pv[start:end]
        n = len(segment)
        seg_start = n - max(1, int(n * STEADY_FRACTION))
        steady = np.median(segment[seg_start:])
        residuals.extend(segment[seg_start:] - steady)
    mad = float(np.median(np.abs(np.array(residuals))))
    return MAD_TO_STD * mad


def _classify_step(
    d_op: float, plan_sizes: tuple[float, ...], prev_direction: int
) -> tuple[float, int, bool]:
    """Return (size, direction, after_reversal) for a step given its OP change."""
    size = min(plan_sizes, key=lambda s: abs(s - abs(d_op)))
    direction = 1 if d_op > 0 else -1
    after_reversal = prev_direction != 0 and direction != prev_direction
    return size, direction, after_reversal


def _compute_gain(
    moves: Sequence[SegmentMove], sigma_pv: float, largest_size: float
) -> float | None:
    """Return median dPV/dOP over qualifying steps, or None if fewer than 2."""
    ratios: list[float] = []
    for move in moves:
        if move.size != largest_size or move.after_reversal:
            continue
        if abs(move.pv_change) > NOISE_SIGMAS * np.sqrt(2) * sigma_pv:
            ratios.append(move.pv_change / move.op_change)
    if len(ratios) < 2:
        return None
    return float(np.median(ratios))


def _compute_moved(
    moves: Sequence[SegmentMove], gain: float, sigma_pv: float, min_step: float
) -> list[bool]:
    """Return list of moved flags per move, with the spec's threshold."""
    threshold = max(NOISE_SIGMAS * np.sqrt(2) * sigma_pv, MOVE_STEP_FRACTION * abs(gain) * min_step)
    return [abs(m.pv_change) > threshold for m in moves]


def _reversal_legs(moves: Sequence[SegmentMove]) -> list[list[SegmentMove]]:
    """Split the steps into legs that start with a direction reversal.

    The first leg of the test starts from rest, not from a reversal, so it carries no deadband
    information (the valve's previous direction is unknown) and is dropped.
    """
    legs: list[list[SegmentMove]] = []
    for move in moves:
        if move.after_reversal:
            legs.append([move])
        elif legs:
            legs[-1].append(move)
    return legs


def _leg_bracket(leg: list[SegmentMove]) -> tuple[float, tuple[float, float]] | float:
    """(size, bracket) of one reversal leg, or the leg's total travel when nothing moved.

    T = output travel after the reversal up to and including the first visibly moving step;
    the valve broke free somewhere in that last step, so deadband lies in (T - s, T].
    """
    travel = 0.0  # cumulative |dOP| since the reversal, % of span
    for move in leg:
        travel += abs(move.op_change)
        if move.moved:
            return move.size, (travel - move.size, travel)
    return travel


def _estimate_deadband(
    moves: Sequence[SegmentMove], size_order: tuple[float, ...]
) -> tuple[float | None, tuple[float, float] | None, float | None, str]:
    """Estimate deadband from reversal legs; return (deadband, bracket, lower_bound, reason)."""
    brackets: dict[float, list[tuple[float, float]]] = {size: [] for size in size_order}
    lower_bounds: list[float] = []
    for leg in _reversal_legs(moves):
        outcome = _leg_bracket(leg)
        if isinstance(outcome, float):
            lower_bounds.append(outcome)  # no move in the whole leg: deadband > its travel
        else:
            brackets.setdefault(outcome[0], []).append(outcome[1])
    lower = max(lower_bounds) if lower_bounds else None
    sized = [size for size in sorted(brackets) if brackets[size]]
    if not sized:
        return None, None, lower, "no move after reversal within a leg"
    return (*_median_bracket(brackets[sized[0]]), lower, "")


def _median_bracket(brackets: list[tuple[float, float]]) -> tuple[float, tuple[float, float]]:
    """Median of the bracket midpoints (the estimate) and the bracket closest to it."""
    midpoints = [(low + high) / 2.0 for low, high in brackets]
    estimate = float(np.median(midpoints))
    closest = min(brackets, key=lambda b: abs((b[0] + b[1]) / 2.0 - estimate))
    return estimate, closest


def _estimate_resolution(
    moves: Sequence[SegmentMove], size_order: tuple[float, ...]
) -> float | None:
    """Return smallest size with >= RESOLUTION_SHARE of non-reversal post-move steps moving."""
    for size in sorted(size_order):  # smallest first: the finest size that passes wins
        qualifying: list[bool] = []
        leg_moved = False
        prev_direction = 0
        for move in moves:
            if move.after_reversal or prev_direction == 0:
                leg_moved = False
                prev_direction = 1 if move.op_change > 0 else -1
                continue
            if move.size != size:
                continue
            if leg_moved:
                qualifying.append(move.moved)
            if move.moved:
                leg_moved = True
        if qualifying and sum(qualifying) / len(qualifying) >= RESOLUTION_SHARE:
            return size
    return None


def analyze_stroke_test(
    t_s: np.ndarray,
    op: np.ndarray,
    pv: np.ndarray,
    plan: StrokePlan,
) -> StrokeResult:
    """Analyze a stroke test record.

    Args:
        t_s: time in seconds (unused except for length checks).
        op: output in % of span.
        pv: process variable in PV units.
        plan: the stroke test plan.

    Returns:
        StrokeResult with deadband, resolution, gain, noise, and per-step moves.

    Raises:
        ValueError: if the plan has no steps or if array lengths differ.
    """
    if not plan.steps:
        raise ValueError("plan has no steps")
    if len(t_s) != len(op) or len(t_s) != len(pv):
        raise ValueError("t_s, op, and pv must have the same length")
    min_step = min(plan.step_sizes)
    change_points = _find_change_points(op, min_step)
    if len(change_points) == 0:
        raise ValueError("no OP changes detected in the record")

    sigma_pv = _estimate_sigma_pv(pv, change_points)
    steady_pv = _segment_steady_pv(pv, change_points)
    steady_op = _segment_steady_pv(op, change_points)

    # Build SegmentMove list.
    moves: list[SegmentMove] = []
    prev_direction = 0
    for j in range(1, len(steady_op)):
        d_op = steady_op[j] - steady_op[j - 1]
        d_pv = steady_pv[j] - steady_pv[j - 1]
        size, direction, after_reversal = _classify_step(d_op, plan.step_sizes, prev_direction)
        moves.append(
            SegmentMove(
                start_index=change_points[j - 1],
                op_change=d_op,
                pv_change=d_pv,
                moved=False,  # filled in later
                size=size,
                after_reversal=after_reversal,
            )
        )
        prev_direction = direction

    # Compute gain.
    largest_size = max(plan.step_sizes)
    gain = _compute_gain(moves, sigma_pv, largest_size)
    if gain is None:
        return StrokeResult(
            deadband=None,
            deadband_bracket=None,
            deadband_lower_bound=None,
            resolution_le=None,
            gain=None,
            sigma_pv=sigma_pv,
            moves=moves,
            pv_left_band=_pv_left_band(pv, plan.pv_band),
            reason="no gain: valve did not move",
        )

    # Compute moved flags.
    moved_flags = _compute_moved(moves, gain, sigma_pv, min_step)
    moves = [replace(move, moved=flag) for move, flag in zip(moves, moved_flags, strict=True)]

    # Deadband.
    deadband, bracket, lower_bound, reason = _estimate_deadband(moves, plan.step_sizes)

    # Resolution.
    resolution = _estimate_resolution(moves, plan.step_sizes)

    return StrokeResult(
        deadband=deadband,
        deadband_bracket=bracket,
        deadband_lower_bound=lower_bound,
        resolution_le=resolution,
        gain=gain,
        sigma_pv=sigma_pv,
        moves=moves,
        pv_left_band=_pv_left_band(pv, plan.pv_band),
        reason=reason,
    )


def _pv_left_band(pv: np.ndarray, pv_band: float | None) -> bool:
    """Return True if pv_band is set and any |pv - pv[0]| > pv_band."""
    if pv_band is None:
        return False
    return bool(np.any(np.abs(pv - pv[0]) > pv_band))
