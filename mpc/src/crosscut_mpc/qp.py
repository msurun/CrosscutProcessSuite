"""Solve ordered, bounded quadratic programs using deterministic OSQP settings.

CV slack is enabled from lowest priority upward; MV rows are always hard.
"""

from dataclasses import dataclass

import numpy as np
import osqp  # type: ignore[import-untyped]  # OSQP does not ship typing metadata.
from scipy import sparse  # type: ignore[import-untyped]  # Sparse matrices cross solver boundary.

from .model import Array

SOLVER_TOLERANCE = 1e-7  # Absolute/relative residual tolerance in scaled engineering units.
ACCEPTANCE_TOLERANCE = 2e-5  # Maximum accepted constraint residual in engineering units.
MAX_ITERATIONS = 10000  # Iterations per attempt, never a wall-clock stopping rule.
SLACK_PENALTY = 1000.0  # Relative squared CV-slack cost.


@dataclass(frozen=True)
class QuadraticProgram:
    """Store min 0.5*x'P*x+q'x with lower <= matrix*x <= upper."""

    quadratic: Array
    linear: Array
    matrix: Array
    lower: Array
    upper: Array


@dataclass(frozen=True)
class Solution:
    """Return solver data; values absent means no certified feasible solution."""

    values: Array | None
    status: str
    iterations: int
    solve_time_s: float
    relaxed: tuple[int, ...] = ()


def solve(program: QuadraticProgram) -> Solution:
    """Solve once with a fresh solver; never reuse history-dependent warm starts."""
    if np.any(program.lower > program.upper):
        return Solution(None, "inconsistent hard bounds", 0, 0.0)
    solver = osqp.OSQP()
    solver.setup(P=sparse.csc_matrix(program.quadratic), q=program.linear,
                 A=sparse.csc_matrix(program.matrix), l=program.lower, u=program.upper,
                 verbose=False, eps_abs=SOLVER_TOLERANCE, eps_rel=SOLVER_TOLERANCE,
                 max_iter=MAX_ITERATIONS, adaptive_rho=True, adaptive_rho_interval=50,
                 polishing=False,
                 warm_starting=False, check_termination=25)
    result = solver.solve(raise_error=False)
    values = result.x if result.info.status_val == 1 else None
    status = str(result.info.status)
    if values is not None and not satisfies_bounds(program, values):
        values = None
        status = "constraint residual exceeds acceptance tolerance"
    return Solution(values, status, int(result.info.iter),
                    float(result.info.run_time))


def satisfies_bounds(program: QuadraticProgram, values: Array) -> bool:
    """Certify finite decisions and primal constraints before proposing a move."""
    # Check A*x in constraint engineering units, independently of OSQP's scaled residual.
    projected = program.matrix @ values
    return bool(np.all(np.isfinite(values)) and
                np.all(projected >= program.lower - ACCEPTANCE_TOLERANCE) and
                np.all(projected <= program.upper + ACCEPTANCE_TOLERANCE))


def with_slack(program: QuadraticProgram, cv_rows: int, weights: Array) -> QuadraticProgram:
    """Append one nonnegative symmetric slack per CV row; initially fix it to zero."""
    # [A_cv,-I] <= upper; [A_cv,+I] >= lower, slack in CV engineering units.
    # Hard rows get zero slack columns, so actuator limits can never be relaxed.
    size = len(program.linear)
    rows = len(program.lower)
    slack_map = np.vstack((np.eye(cv_rows), np.zeros((rows - cv_rows, cv_rows))))
    matrix = np.block([[program.matrix, -slack_map], [program.matrix, slack_map],
                       [np.zeros((cv_rows, size)), np.eye(cv_rows)]])
    quadratic = np.zeros((size + cv_rows, size + cv_rows))
    quadratic[:size, :size] = program.quadratic
    quadratic[size:, size:] = np.diag(2 * SLACK_PENALTY * weights)
    return QuadraticProgram(quadratic, np.r_[program.linear, np.zeros(cv_rows)], matrix,
                            np.r_[np.full(rows, -np.inf), program.lower, np.zeros(cv_rows)],
                            np.r_[program.upper, np.full(rows, np.inf), np.zeros(cv_rows)])


def solve_priorities(program: QuadraticProgram, priorities: Array, weights: Array) -> Solution:
    """Try hard CVs first, then enable slack for each priority group in stable order."""
    softened = with_slack(program, len(priorities), weights)
    relaxed: tuple[int, ...] = ()
    iterations, duration = 0, 0.0
    for priority in (None, *sorted(set(priorities), reverse=True)):
        if priority is not None:
            indices = np.flatnonzero(priorities == priority)
            softened.upper[-len(priorities) + indices] = np.inf
            relaxed += tuple(int(index) for index in indices)
        solution = solve(softened)
        iterations += solution.iterations
        duration += solution.solve_time_s
        if solution.values is not None:
            return Solution(solution.values[:len(program.linear)], solution.status,
                            iterations, duration, relaxed)
        if solution.status not in ("primal infeasible", "inconsistent hard bounds"):
            break  # Numerical failure is not evidence that a CV should be sacrificed.
    return Solution(None, solution.status, iterations, duration, relaxed)
