"""Economic layer of the steady-state target: maximise value inside every limit.

The objective is per-site configuration. Value is per hour: rate = sum(v_c*y_c) - sum(k_m*u_m)
[currency/h] with y in CV units, u in MV units, v_c [currency/(CV unit*h)] signed (positive
means higher is better) and k_m [currency/(MV unit*h)] the cost of a higher MV. Signals are
deviations from the model operating point, so a rate is meaningful as a difference.
Priority is never traded for value: stage 1 is the existing priority solve (tracking with
priority relaxation); stage 2 maximises value with every CV bound no tighter than stage 1
allowed. Ties on the optimal face are broken toward the operator targets (stage 3).
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import optimize  # type: ignore[import-untyped]  # SciPy ships no typing metadata.

from .config import Controller, priority_weights
from .model import Array
from .planning import CycleInputs, steady_target, tracking_cost
from .qp import ACCEPTANCE_TOLERANCE, QuadraticProgram, Solution, solve

TIE_RELATIVE = 1e-6  # Share of the optimal value that stage 3 may give up to track targets.
RIDGE = 1e-6  # Relative curvature making the tie-break QP strictly convex (MV units^2).
Bounds = tuple[tuple[Array, Array], tuple[Array, Array]]  # ((CV lower, upper), (MV lower, upper))


@dataclass(frozen=True)
class Economics:
    """Per-hour value of each CV unit and cost of each MV unit, with optional soft limits.

    Soft limits lie inside the hard limits and only shape the economic optimum: use +-inf for none.
    """

    cv_value: Array
    mv_cost: Array
    cv_soft_lower: Array
    cv_soft_upper: Array
    mv_soft_lower: Array
    mv_soft_upper: Array

    def __post_init__(self) -> None:
        """Own read-only vectors; values must be finite, soft limits may be infinite."""
        for name in self.__dataclass_fields__:
            values = np.array(getattr(self, name), dtype=float, copy=True)
            finite_needed = name in ("cv_value", "mv_cost")
            if values.ndim != 1 or np.any(np.isnan(values)) or (
                    finite_needed and not np.all(np.isfinite(values))):
                raise ValueError(f"{name} must be a vector without NaN (values finite)")
            values.setflags(write=False)
            object.__setattr__(self, name, values)
        if np.any(self.cv_soft_lower > self.cv_soft_upper) or \
                np.any(self.mv_soft_lower > self.mv_soft_upper):
            raise ValueError("Soft lower limits must not exceed soft upper limits")

    @property
    def is_active(self) -> bool:
        """False when every value and cost is zero: the target is then plain tracking."""
        return bool(np.any(self.cv_value != 0) or np.any(self.mv_cost != 0))

    def rate(self, cvs: Array, mvs: Array) -> float:
        """Economic rate [currency/h] of CV and MV deviations."""
        return float(self.cv_value @ cvs - self.mv_cost @ mvs)


def neutral(cv_count: int, mv_count: int) -> Economics:
    """Economics with zero values, costs and no soft limits."""
    return Economics(np.zeros(cv_count), np.zeros(mv_count), np.full(cv_count, -np.inf),
                     np.full(cv_count, np.inf), np.full(mv_count, -np.inf),
                     np.full(mv_count, np.inf))


@dataclass(frozen=True)
class Binding:
    """A limit the optimum rests on and what relaxing it by one unit would earn.

    shadow_price is [currency/h per CV or MV unit]; it is the "why" of the target.
    """

    kind: str  # "mv" or "cv"
    index: int
    side: str  # "lower" or "upper"
    limit: str  # "hard" or "soft"
    shadow_price: float


@dataclass(frozen=True)
class EconomicReport:
    """Value of the economic target against the setpoint-tracking target, and what binds."""

    value_rate: float
    tracking_rate: float
    benefit_rate: float
    binding: tuple[Binding, ...]
    soft_limits_applied: bool
    status: str


@dataclass(frozen=True)
class EconomicTarget:
    """The steady-state solution handed to the dynamic layer plus its economic report."""

    solution: Solution
    report: EconomicReport | None


def steady_economic_target(controller: Controller, inputs: CycleInputs,
                           bias: Array) -> EconomicTarget:
    """Solve the steady-state target; economic when the controller carries active economics."""
    base = steady_target(controller, inputs, bias)
    economics = controller.economics
    if economics is None or not economics.is_active or base.values is None:
        return EconomicTarget(base, None)
    count = len(controller.limits.mv_lower)
    gains = controller.model.gains[:, :count]
    offset = bias + controller.model.gains[:, count:] @ np.asarray(inputs.disturbances)
    return optimise_value(controller, (gains, offset, inputs.targets), base)


def widened_cv_bounds(controller: Controller, tracked: Array) -> tuple[Array, Array]:
    """CV bounds no tighter than stage 1 achieved: priority relaxation is kept, not undone."""
    limits = controller.limits
    return np.minimum(limits.cv_lower, tracked), np.maximum(limits.cv_upper, tracked)


def soft_bounds(hard: tuple[Array, Array], soft: tuple[Array, Array]) -> tuple[Array, Array]:
    """Intersect hard with soft bounds row by row; a row whose intersection is empty stays hard."""
    lower, upper = np.maximum(hard[0], soft[0]), np.minimum(hard[1], soft[1])
    empty = lower > upper
    return np.where(empty, hard[0], lower), np.where(empty, hard[1], upper)


def optimise_value(controller: Controller, model: tuple[Array, Array, Array],
                   base: Solution) -> EconomicTarget:
    """Stages 2 and 3: LP for the value, then the QP toward targets on the optimal face."""
    gains, offset, _ = model
    economics = controller.economics
    assert economics is not None and base.values is not None
    cv_hard = widened_cv_bounds(controller, gains @ base.values + offset)
    mv_hard = (controller.limits.mv_lower, controller.limits.mv_upper)
    for use_soft in (True, False):
        cv, mv = cv_hard, mv_hard
        if use_soft:
            cv = soft_bounds(cv_hard, (economics.cv_soft_lower, economics.cv_soft_upper))
            mv = soft_bounds(mv_hard, (economics.mv_soft_lower, economics.mv_soft_upper))
        lp = solve_value_lp(economics, (gains, offset), (cv, mv))
        if lp.success:
            return finish_target(controller, model, ((cv, mv), use_soft), (lp, base))
    return EconomicTarget(base, EconomicReport(0.0, 0.0, 0.0, (), False,
                                               "economic LP infeasible; tracking target kept"))


def value_cost(economics: Economics, gains: Array) -> Array:
    """Objective vector c = k - G'v [currency/h per MV unit]; the constant -v'd is dropped."""
    return economics.mv_cost - gains.T @ economics.cv_value


def solve_value_lp(economics: Economics, model: tuple[Array, Array], bounds: Bounds) -> Any:
    """Minimise k'u - v'(G u + d) subject to lower <= G u + d <= upper and MV bounds (HiGHS)."""
    gains, offset = model
    (cv_lower, cv_upper), (mv_lower, mv_upper) = bounds
    matrix = np.vstack((gains, -gains))
    rhs = np.r_[cv_upper - offset, offset - cv_lower]
    return optimize.linprog(value_cost(economics, gains), A_ub=matrix, b_ub=rhs,
                            bounds=list(zip(mv_lower, mv_upper, strict=True)), method="highs")


def tie_break(controller: Controller, model: tuple[Array, Array, Array],
              bounds: Bounds, lp_values: Array) -> Array:
    """Closest-to-tracking point whose value is within TIE_RELATIVE of the LP optimum."""
    gains, offset, targets = model
    economics = controller.economics
    assert economics is not None
    (cv_lower, cv_upper), (mv_lower, mv_upper) = bounds
    weights = priority_weights(controller.limits.priorities)
    quadratic, linear = tracking_cost(gains, offset - targets, (weights, 0.0))
    count = len(mv_lower)
    quadratic = quadratic + RIDGE * np.max(np.diag(quadratic)) * np.eye(count)
    cost = value_cost(economics, gains)
    best = float(cost @ lp_values)
    # Row c'u <= c'u* + tol keeps the optimal face; tol is a share of the value scale.
    slack = TIE_RELATIVE * max(1.0, abs(best))
    matrix = np.vstack((gains, np.eye(count), cost[None, :]))
    program = QuadraticProgram(quadratic, linear, matrix,
                               np.r_[cv_lower - offset, mv_lower, -np.inf],
                               np.r_[cv_upper - offset, mv_upper, best + slack])
    tied = solve(program)
    return lp_values if tied.values is None else tied.values


def finish_target(controller: Controller, model: tuple[Array, Array, Array],
                  setup: tuple[Bounds, bool], solved: tuple[Any, Solution]) -> EconomicTarget:
    """Break ties, then report value, benefit over tracking and the binding limits."""
    gains, offset, _ = model
    bounds, use_soft = setup
    lp, base = solved
    economics = controller.economics
    assert economics is not None and base.values is not None
    values = tie_break(controller, model, bounds, np.asarray(lp.x))
    value = economics.rate(gains @ values + offset, values)
    tracking = economics.rate(gains @ base.values + offset, base.values)
    binding = binding_limits(controller, (gains @ values + offset, values), bounds, lp)
    solution = Solution(values, "economic", base.iterations, base.solve_time_s, base.relaxed)
    return EconomicTarget(solution, EconomicReport(value, tracking, value - tracking, binding,
                                                   use_soft, "optimal"))


def binding_limits(controller: Controller, levels: tuple[Array, Array], bounds: Bounds,
                   lp: Any) -> tuple[Binding, ...]:
    """Limits the final point rests on, priced by the LP duals (price 0 when degenerate)."""
    (cv_lower, cv_upper), (mv_lower, mv_upper) = bounds
    limits = controller.limits
    cvs = len(cv_lower)
    rows = np.asarray(lp.ineqlin.marginals)
    # Duals of the minimisation are <= 0; relaxing a limit by one unit earns -marginal.
    prices = {("cv", "upper"): -rows[:cvs], ("cv", "lower"): -rows[cvs:],
              ("mv", "upper"): -np.asarray(lp.upper.marginals),
              ("mv", "lower"): np.asarray(lp.lower.marginals)}
    table = {"cv": (levels[0], (cv_lower, cv_upper), (limits.cv_lower, limits.cv_upper)),
             "mv": (levels[1], (mv_lower, mv_upper), (limits.mv_lower, limits.mv_upper))}
    found = []
    for kind, (level, used, hard) in table.items():
        for side, bound, edge in zip(("lower", "upper"), used, hard, strict=True):
            for index in np.flatnonzero(np.abs(level - bound) <= ACCEPTANCE_TOLERANCE):
                label = "hard" if bound[index] == edge[index] else "soft"
                price = max(float(prices[(kind, side)][index]), 0.0)
                found.append(Binding(kind, int(index), side, label, price))
    return tuple(found)
