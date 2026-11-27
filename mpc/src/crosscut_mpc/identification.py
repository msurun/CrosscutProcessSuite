"""Identify a MIMO FOPDT model pair by pair, with a per-pair quality gate (design note 2.1).

Each (MV, CV) and (DV, CV) pair is fitted on its own record window (a one-input-at-a-time
step test) with the loops FOPDT estimator, then judged by the loops fit gate. A model with
a failing pair cannot be turned into a controller model. Storage is in artifact.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from crosscut_loops.identification import identify_fopdt
from crosscut_loops.identification_quality import assess_fit
from crosscut_loops.tuning_rules import FopdtModel
from numpy.typing import NDArray

from .model import FopdtModel as MpcFopdtModel

Array = NDArray[np.float64]
METHOD = "fopdt_per_pair_ls"  # method label stored in the artifact


class IdentificationRejected(ValueError):
    """Raised when a pair fails its gate or cannot be fitted, so the model is unusable."""


@dataclass(frozen=True)
class Dataset:
    """Aligned records on a uniform grid: time [s] (N,), signals by tag name, each (N,)."""

    time_s: Array
    inputs: dict[str, Array]  # MVs first, then DVs, in matrix column order
    outputs: dict[str, Array]  # CVs in matrix row order


@dataclass(frozen=True)
class PairSpec:
    """One path to identify: input and CV names and the sample window [start, stop)."""

    input_name: str
    cv_name: str
    start: int
    stop: int


@dataclass(frozen=True)
class PairQuality:
    """Gate verdict for one pair (free-run R2 in [-inf, 1], event count, reasons)."""

    free_run_r2: float
    excitation_events: int
    passed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class IdentifiedModel:
    """Matrices are (CV, input) as in the MPC model; seconds, CV units per input unit."""

    input_names: tuple[str, ...]
    cv_names: tuple[str, ...]
    gains: Array
    time_constants_s: Array
    dead_times_s: Array
    cycle_s: float
    quality: tuple[tuple[PairQuality, ...], ...]  # [cv][input]
    windows: dict[str, tuple[float, float]]  # "input->cv": (t_start_s, t_stop_s)
    method: str = METHOD
    enabled: tuple[tuple[bool, ...], ...] | None = None  # [CV][input]; None enables all paths.
    edit_metadata: dict[str, object] | None = None  # Hashed provenance of an edited version.

    def __post_init__(self) -> None:
        """Reject malformed enable grids before converting or storing a model."""
        if self.enabled is None:
            return
        if len(self.enabled) != len(self.cv_names) or any(
            len(row) != len(self.input_names) for row in self.enabled
        ):
            raise ValueError("enabled must have one boolean per CV/input pair")
        if any(type(value) is not bool for row in self.enabled for value in row):
            raise ValueError("enabled must contain booleans; use true or false for every pair")

    def pair_enabled(self, row: int, column: int) -> bool:
        """Return whether a path participates, including legacy artifacts without flags."""
        return self.enabled is None or self.enabled[row][column]

    @property
    def accepted(self) -> bool:
        """True when every enabled pair passed the original identification gate."""
        return all(q.passed for row_index, row in enumerate(self.quality)
                   for column, q in enumerate(row) if self.pair_enabled(row_index, column))

    def to_mpc_model(self) -> MpcFopdtModel:
        """Return the controller model; refuse when any pair failed the gate."""
        if not self.accepted:
            failed = [
                f"{name}->{cv}: {'; '.join(q.reasons)}"
                for row_index, (cv, row) in enumerate(zip(self.cv_names, self.quality, strict=True))
                for column, (name, q) in enumerate(zip(self.input_names, row, strict=True))
                if not q.passed and self.pair_enabled(row_index, column)
            ]
            raise IdentificationRejected("pairs failed the quality gate: " + " | ".join(failed))
        # Disabled paths contribute zero CV-unit/input-unit gain, retaining their fitted values
        # in the artifact so re-enabling never destroys the original identification evidence.
        gains = self.gains if self.enabled is None else np.where(self.enabled, self.gains, 0.0)
        return MpcFopdtModel(gains, self.time_constants_s, self.dead_times_s, self.cycle_s)


def _cycle_s(time_s: Array) -> float:
    """Return the sampling period dt [s]; the grid must be uniform within 1 %."""
    steps = np.diff(time_s)
    if steps.size < 2 or np.any(steps <= 0) or np.ptp(steps) > 0.01 * steps[0]:
        raise IdentificationRejected("time grid must be uniform, increasing and have >2 samples")
    return float(steps[0])


def _fit_either_sign(
    u: Array, y: Array, dt_s: float, max_delay_s: float
) -> tuple[FopdtModel, float]:
    """Fit y ~ K*u with K > 0, or with the input negated for a negative-gain path.

    The loops estimator only accepts positive gains; fitting -u gives K' = -K. Returns the
    fit and sign s in {+1, -1} such that the true gain is s*K' (re-raises if both fail).
    """
    try:
        return identify_fopdt(u, y, dt_s, max_delay_s), 1.0
    except ValueError:
        return identify_fopdt(-u, y, dt_s, max_delay_s), -1.0


def _fit_pair(
    data: Dataset, spec: PairSpec, dt_s: float, max_delay_s: float
) -> tuple[tuple[float, float, float], PairQuality]:
    """Fit one window and return ((K, tau_s, theta_s), verdict); a failed fit fails the verdict."""
    window = slice(spec.start, spec.stop)
    u = data.inputs[spec.input_name][window]
    y = data.outputs[spec.cv_name][window]
    try:
        fit, sign = _fit_either_sign(u, y, dt_s, max_delay_s)
    except ValueError as err:
        events = int(np.count_nonzero(np.abs(np.diff(u)) > 0))
        return (1.0, dt_s, 0.0), PairQuality(float("-inf"), events, False, (f"fit failed: {err}",))
    verdict = assess_fit(fit, sign * u, y, dt_s)
    quality = PairQuality(
        verdict.free_run_r2, verdict.excitation_events, not verdict.low_confidence, verdict.reasons
    )
    return (sign * fit.gain, fit.time_constant_s, fit.delay_s), quality


def identify_mimo(data: Dataset, pairs: list[PairSpec], max_delay_s: float) -> IdentifiedModel:
    """Identify every listed pair; all (CV, input) combinations must appear exactly once.

    Per pair: y[k+1] = a*y[k] + b*u[k-d] + c (least squares over a delay scan), mapped to
    K = b/(1-a), tau = -dt/ln(a), theta = d*dt. Failing pairs keep placeholder values and
    a failed verdict; the model then reports accepted == False.
    """
    dt_s = _cycle_s(data.time_s)
    names, cvs = tuple(data.inputs), tuple(data.outputs)
    shape = (len(cvs), len(names))
    wanted = sorted((cv, name) for cv in cvs for name in names)
    if sorted((p.cv_name, p.input_name) for p in pairs) != wanted:
        raise ValueError("pairs must cover every (CV, input) combination exactly once")
    gains, taus, delays = (np.zeros(shape) for _ in range(3))
    quality: dict[tuple[int, int], PairQuality] = {}
    windows: dict[str, tuple[float, float]] = {}
    for spec in pairs:
        row, col = cvs.index(spec.cv_name), names.index(spec.input_name)
        (gains[row, col], taus[row, col], delays[row, col]), quality[row, col] = _fit_pair(
            data, spec, dt_s, max_delay_s
        )
        windows[f"{spec.input_name}->{spec.cv_name}"] = (
            float(data.time_s[spec.start]),
            float(data.time_s[spec.stop - 1]),
        )
    grid = tuple(tuple(quality[r, c] for c in range(shape[1])) for r in range(shape[0]))
    return IdentifiedModel(names, cvs, gains, taus, delays, dt_s, grid, windows)
