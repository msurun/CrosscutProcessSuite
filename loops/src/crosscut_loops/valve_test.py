"""
Guided valve stroke test: operator procedure, plan, and analysis of the PV response.

Nothing writes to a DCS; the plan is a procedure the operator executes. Deadband and
resolution are estimated from the PV response using definitions after ANSI/ISA-75.25.01
and ISA-TR75.25.02 as recalled (the standards were not read).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

# Why a result can be incomplete: the English text (command line) and the stable code (UI).
NO_GAIN_REASON = "no gain: valve did not move"
NO_REVERSAL_MOVE_REASON = "no move after reversal within a leg"
REASON_CODES = {NO_GAIN_REASON: "no_gain", NO_REVERSAL_MOVE_REASON: "no_move_after_reversal"}


def reason_code(reason: str) -> str:
    """Stable code of a StrokeResult.reason: "" when complete, "other" for an unknown text."""
    return REASON_CODES.get(reason, "" if reason == "" else "other")


# Analysis constants (units: % of output span unless noted)
CHANGE_FRACTION = 0.4          # fraction of smallest step below which OP change is noise
NOISE_SIGMAS = 3.0             # detection threshold multiplier for PV noise
MOVE_STEP_FRACTION = 0.5       # fraction of |K| * smallest step used in the moved test
RESOLUTION_SHARE = 0.75        # share of steps that must move to certify resolution
STEADY_FRACTION = 1 / 3        # last third of each segment used for steady values
MAD_TO_STD = 1.4826            # MAD to standard deviation for Gaussian noise
MIN_GAP_DWELL_FRACTION = 0.25  # changes closer than this share of a dwell are one operator move
MIN_GAP_SAMPLES = 3            # floor of that gap, in samples


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
        moved: True if the PV change exceeds the noise gate and a share of the expected
            response (see `_compute_moved`).
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


@dataclass(frozen=True)
class _PlanInputs:
    """Validated-together inputs of `plan_stroke_test` (private parameter group)."""

    op_start: float
    step_sizes: tuple[float, ...]
    steps_per_leg: tuple[int, ...]
    dwell_s: int
    op_low: float
    op_high: float

    def to_plan(self, pv_band: float | None, steps: tuple[TestStep, ...]) -> StrokePlan:
        """Return the StrokePlan made of these inputs, the abort band and the built steps."""
        return StrokePlan(
            op_start=self.op_start,
            step_sizes=self.step_sizes,
            steps_per_leg=self.steps_per_leg,
            dwell_s=self.dwell_s,
            op_low=self.op_low,
            op_high=self.op_high,
            pv_band=pv_band,
            steps=steps,
        )


def _validate_plan_inputs(inputs: _PlanInputs) -> None:
    """Raise ValueError if plan inputs are inconsistent or out of range."""
    if len(inputs.step_sizes) != len(inputs.steps_per_leg):
        raise ValueError("step_sizes and steps_per_leg must have the same length")
    if inputs.dwell_s <= 0:
        raise ValueError("dwell_s must be positive")
    if inputs.op_low >= inputs.op_high:
        raise ValueError("op_low must be strictly less than op_high")
    if not inputs.op_low <= inputs.op_start <= inputs.op_high:
        raise ValueError("op_start must be within [op_low, op_high]")
    for size in inputs.step_sizes:
        if size <= 0:
            raise ValueError(f"step size must be positive, got {size}")


def _step_specs(inputs: _PlanInputs) -> Iterator[tuple[float, int, bool]]:
    """Yield (size, direction, after_reversal) for every step of the plan, in order."""
    # Three legs per size: up, down, up (two reversals).
    leg_directions = (1, -1, 1)
    for size, leg_length in zip(inputs.step_sizes, inputs.steps_per_leg, strict=True):
        for leg_number, direction in enumerate(leg_directions):
            for _ in range(leg_length):
                yield size, direction, leg_number > 0


def _build_steps(inputs: _PlanInputs) -> tuple[TestStep, ...]:
    """Build all TestStep objects of the plan.

    Raises ValueError if any target leaves [op_low, op_high].
    """
    steps: list[TestStep] = []
    current_op = inputs.op_start
    for size, direction, after_reversal in _step_specs(inputs):
        target = current_op + direction * size
        _check_target(target, len(steps), inputs)
        steps.append(TestStep(len(steps), target, direction, size, inputs.dwell_s, after_reversal))
        current_op = target
    return tuple(steps)


def _check_target(target: float, index: int, inputs: _PlanInputs) -> None:
    """Raise ValueError if the OP target of step `index` leaves the output limits."""
    if not inputs.op_low <= target <= inputs.op_high:
        raise ValueError(
            f"step {index} target {target:.2f} outside [{inputs.op_low}, {inputs.op_high}]"
        )


# codecheck: allow too-many-parameters (public signature used by valve_test_cli, run25, tests)
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

    For each step size with leg length m, the legs are up m steps, down m steps, up m
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
    sizes = tuple(float(size) for size in step_sizes)
    lengths = tuple(int(length) for length in steps_per_leg)
    inputs = _PlanInputs(op_start, sizes, lengths, dwell_s, op_low, op_high)
    _validate_plan_inputs(inputs)
    return inputs.to_plan(pv_band, _build_steps(inputs))


def procedure_steps(plan: StrokePlan) -> list[dict[str, Any]]:
    """Return the operator instructions as stable codes plus parameters (no prose).

    A UI translates each ``code``; ``procedure_text`` renders the same steps in English for the
    command line. Codes: ``manual``, ``abort`` (params ``op_start``, ``pv_band`` or None),
    ``set_start`` (``op``, ``dwell_s``), ``step`` (``op``, ``dwell_s``) and ``return_auto``
    (``op``). The abort rule comes before the first move, so the operator knows it while stepping.
    """
    steps: list[dict[str, Any]] = [
        {"code": "manual", "params": {}},
        {"code": "abort", "params": {"op_start": plan.op_start, "pv_band": plan.pv_band}},
        {"code": "set_start", "params": {"op": plan.op_start, "dwell_s": plan.dwell_s}},
    ]
    steps += [
        {"code": "step", "params": {"op": step.op_target, "dwell_s": step.dwell_s}}
        for step in plan.steps
    ]
    steps.append({"code": "return_auto", "params": {"op": plan.op_start}})
    return steps


def _procedure_sentence(step: dict[str, Any]) -> str:
    """One procedure step as an English sentence (the command-line wording)."""
    code, params = step["code"], step["params"]
    if code == "manual":
        return "Put the loop in MANUAL."
    if code == "abort":
        text = "If anything looks wrong at any time, abort: return the output to "
        text += f"{params['op_start']:.2f}% and put the loop back in AUTO."
        if params["pv_band"] is not None:
            band = f"{params['pv_band']:.2f}"
            text = f"If the PV moves more than {band} from its starting value, " + text
        return text
    if code == "return_auto":
        return f"Return the output to {params['op']:.2f}% and put the loop back in AUTO."
    return f"Set the output to {params['op']:.2f}% and wait {params['dwell_s']} seconds."


def procedure_text(plan: StrokePlan) -> list[str]:
    """Return numbered operator instructions for executing the stroke test.

    Args:
        plan: the stroke test plan.

    Returns:
        List of strings, each a numbered step in plain English.
    """
    sentences = [_procedure_sentence(step) for step in procedure_steps(plan)]
    return [f"{number}. {text}" for number, text in enumerate(sentences, start=1)]


def _find_change_points(op: np.ndarray, min_step: float, min_gap: int) -> np.ndarray:
    """Indices where the operator moved the OP to a new level.

    Three passes, so that ramps and OP noise do not shatter the record:
    1. level crossings: a point wherever the OP leaves the last level by more than
       CHANGE_FRACTION * min_step (catches fast steps and slow ramps alike);
    2. points closer than ``min_gap`` samples to the previous kept one are merged into it
       (a ramp or a noisy edge becomes one change at its start);
    3. boundaries whose steady OP did not really change are dropped (noise blips).
    """
    threshold = CHANGE_FRACTION * min_step
    crossings, level = [], float(op[0])
    for k in range(1, len(op)):
        if abs(op[k] - level) > threshold:
            crossings.append(k)
            level = float(op[k])
    kept: list[int] = []
    for k in crossings:
        if not kept or k - kept[-1] >= min_gap:
            kept.append(k)
    return _drop_flat_boundaries(op, kept, threshold)


def _drop_flat_boundaries(op: np.ndarray, points: list[int], threshold: float) -> np.ndarray:
    """Remove boundaries across which the steady OP changes by no more than ``threshold``."""
    changed = True
    while changed and points:
        steady = _segment_steady_pv(op, np.asarray(points, dtype=int))
        flat = [j for j in range(1, len(steady)) if abs(steady[j] - steady[j - 1]) <= threshold]
        changed = bool(flat)
        if changed:
            del points[flat[0] - 1]  # boundary j - 1 separates segments j - 1 and j
    return np.asarray(points, dtype=int)


def _steady_value(segment: np.ndarray, fraction: float = STEADY_FRACTION) -> float:
    """Return the median of the last `fraction` of a segment."""
    length = len(segment)
    start = length - max(1, int(length * fraction))
    return float(np.median(segment[start:]))


def _segment_steady_pv(pv: np.ndarray, change_points: np.ndarray) -> list[float]:
    """Return steady PV for each segment defined by change points."""
    boundaries = [0] + list(change_points) + [len(pv)]
    steady_values: list[float] = []
    for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
        steady_values.append(_steady_value(pv[start:end]))
    return steady_values


def _estimate_sigma_pv(pv: np.ndarray, change_points: np.ndarray) -> float:
    """Estimate PV noise std via MAD of segment residuals, scaled by MAD_TO_STD.

    The residuals are the steady part (last STEADY_FRACTION) of every segment minus its own
    median, so steps and slow drift between segments do not count as noise. For Gaussian
    noise std = 1.4826 * MAD, with MAD the median of the absolute residuals.
    """
    boundaries = [0] + list(change_points) + [len(pv)]
    residuals: list[float] = []
    for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
        segment = pv[start:end]
        steady_part = segment[len(segment) - max(1, int(len(segment) * STEADY_FRACTION)):]
        residuals.extend(steady_part - np.median(steady_part))
    mad = float(np.median(np.abs(np.array(residuals))))
    return MAD_TO_STD * mad


def _classify_step(
    d_op: float, plan_sizes: tuple[float, ...], prev_direction: int
) -> tuple[float, int, bool]:
    """Return (size, direction, after_reversal) for a step given its OP change."""
    size = min(plan_sizes, key=lambda plan_size: abs(plan_size - abs(d_op)))
    direction = 1 if d_op > 0 else -1
    after_reversal = prev_direction != 0 and direction != prev_direction
    return size, direction, after_reversal


def _compute_gain(
    moves: Sequence[SegmentMove], sigma_pv: float, largest_size: float
) -> float | None:
    """Return the median dPV/dOP over qualifying steps, or None if fewer than 2.

    Qualifying: a step of the largest size, not right after a reversal (the valve may still sit
    in its deadband there), whose PV change beats NOISE_SIGMAS * sqrt(2) * sigma_pv (the
    difference of two noisy values, see `_compute_moved`). Unit: PV units per % of span.
    """
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
    """Return the moved flag of every step.

    A step moved the valve when its PV change beats both the noise gate and a share of the
    response a free valve would give. A PV change is the difference of two noisy steady values,
    so single-sample noise would give it std sqrt(2) * sigma_pv (a conservative gate: the steady
    values are medians of several samples). Gain K times an OP step is the expected PV change
    (PV units).
    """
    threshold = max(NOISE_SIGMAS * np.sqrt(2) * sigma_pv, MOVE_STEP_FRACTION * abs(gain) * min_step)
    return [abs(move.pv_change) > threshold for move in moves]


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
        return None, None, lower, NO_REVERSAL_MOVE_REASON
    return (*_median_bracket(brackets[sized[0]]), lower, "")


def _median_bracket(brackets: list[tuple[float, float]]) -> tuple[float, tuple[float, float]]:
    """Median of the bracket midpoints (the estimate) and the bracket closest to it."""
    midpoints = [(low + high) / 2.0 for low, high in brackets]
    estimate = float(np.median(midpoints))
    closest = min(brackets, key=lambda bracket: abs((bracket[0] + bracket[1]) / 2.0 - estimate))
    return estimate, closest


def _estimate_resolution(
    moves: Sequence[SegmentMove], size_order: tuple[float, ...]
) -> float | None:
    """Return smallest size with >= RESOLUTION_SHARE of non-reversal post-move steps moving."""
    for size in sorted(size_order):  # smallest first: the finest size that passes wins
        qualifying = _post_move_flags(moves, size)
        if qualifying and sum(qualifying) / len(qualifying) >= RESOLUTION_SHARE:
            return size
    return None


def _post_move_flags(moves: Sequence[SegmentMove], size: float) -> list[bool]:
    """Moved flags of the steps of `size` that follow a move within the same leg."""
    qualifying: list[bool] = []
    leg_moved = False
    prev_direction = 0
    for move in moves:
        if move.after_reversal or prev_direction == 0:
            # A leg starts; a valve that broke free on this very step already moved.
            leg_moved = move.moved
            prev_direction = 1 if move.op_change > 0 else -1
            continue
        if move.size != size:
            continue
        if leg_moved:
            qualifying.append(move.moved)
        if move.moved:
            leg_moved = True
    return qualifying


def _check_record(t_s: np.ndarray, op: np.ndarray, pv: np.ndarray, plan: StrokePlan) -> None:
    """Raise ValueError if the plan or the record arrays are unusable."""
    if not plan.steps:
        raise ValueError("plan has no steps")
    if len(t_s) != len(op) or len(t_s) != len(pv):
        raise ValueError("t_s, op, and pv must have the same length")
    if not (np.all(np.isfinite(op)) and np.all(np.isfinite(pv)) and np.all(np.isfinite(t_s))):
        raise ValueError("t_s, op and pv must be finite (no NaN or gaps in the record)")


def _build_moves(
    change_points: np.ndarray,
    steady_op: list[float],
    steady_pv: list[float],
    plan_sizes: tuple[float, ...],
) -> list[SegmentMove]:
    """Build one SegmentMove (moved=False for now) per boundary between steady segments."""
    moves: list[SegmentMove] = []
    prev_direction = 0
    for j in range(1, len(steady_op)):
        op_change = steady_op[j] - steady_op[j - 1]
        size, direction, after_reversal = _classify_step(op_change, plan_sizes, prev_direction)
        pv_change = steady_pv[j] - steady_pv[j - 1]
        # moved=False is filled in later, once the gain is known
        start = change_points[j - 1]
        moves.append(SegmentMove(start, op_change, pv_change, False, size, after_reversal))
        prev_direction = direction
    return moves


def analyze_stroke_test(
    t_s: np.ndarray,
    op: np.ndarray,
    pv: np.ndarray,
    plan: StrokePlan,
) -> StrokeResult:
    """Analyze a stroke test record.

    Args:
        t_s: time in seconds (sets the sample interval; length is checked against op and pv).
        op: output in % of span.
        pv: process variable in PV units.
        plan: the stroke test plan.

    Returns:
        StrokeResult with deadband, resolution, gain, noise, and per-step moves.

    Raises:
        ValueError: if the plan has no steps or if array lengths differ.
    """
    _check_record(t_s, op, pv, plan)
    dt_s = float(np.median(np.diff(t_s))) if len(t_s) > 1 else 1.0
    min_gap = max(MIN_GAP_SAMPLES, int(plan.dwell_s * MIN_GAP_DWELL_FRACTION / dt_s))
    change_points = _find_change_points(op, min(plan.step_sizes), min_gap)
    if len(change_points) == 0:
        raise ValueError("no OP changes detected in the record")
    sigma_pv = _estimate_sigma_pv(pv, change_points)
    moves = _build_moves(
        change_points,
        _segment_steady_pv(op, change_points),
        _segment_steady_pv(pv, change_points),
        plan.step_sizes,
    )
    return _result_from_moves(moves, plan, sigma_pv, _pv_left_band(pv, plan.pv_band))


def _result_from_moves(
    moves: list[SegmentMove], plan: StrokePlan, sigma_pv: float, pv_left_band: bool
) -> StrokeResult:
    """Estimate gain, moved flags, deadband and resolution from the unflagged moves."""
    gain = _compute_gain(moves, sigma_pv, max(plan.step_sizes))
    if gain is None:
        return StrokeResult(None, None, None, None, None, sigma_pv, moves, pv_left_band,
                            NO_GAIN_REASON)
    flags = _compute_moved(moves, gain, sigma_pv, min(plan.step_sizes))
    moves = [replace(move, moved=flag) for move, flag in zip(moves, flags, strict=True)]
    deadband, bracket, lower_bound, reason = _estimate_deadband(moves, plan.step_sizes)
    resolution = _estimate_resolution(moves, plan.step_sizes)
    return StrokeResult(deadband, bracket, lower_bound, resolution, gain, sigma_pv, moves,
                        pv_left_band, reason)


def _pv_left_band(pv: np.ndarray, pv_band: float | None) -> bool:
    """Return True if pv_band is set and any |pv - pv[0]| > pv_band."""
    if pv_band is None:
        return False
    return bool(np.any(np.abs(pv - pv[0]) > pv_band))
