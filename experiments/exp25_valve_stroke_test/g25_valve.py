"""Synthetic stroke-test data generator G25 for exp25 (valve deadband / resolution).

A stick-slip valve (written from the ISA-style definitions) drives a FOPDT plant in
manual mode. Independent of the analyzer and of crosscut_sim/valve.py. Units: % of span.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product

import numpy as np
from crosscut_sim.core import Fopdt

DT_S = 1.0  # sample time, s
THETA_S = 1.0  # plant dead time, s
LOAD_SIZE = {"none": 0.0, "step": 0.3, "big_step": 5.0}  # load step, % output units


@dataclass(frozen=True)
class Case:
    """One simulated test condition (plant, noise, load and valve health)."""

    gain: float  # PV units per % output
    tau_s: float  # plant time constant, s
    noise_fraction: float  # noise std as a fraction of |gain|
    load: str  # "none", "step" (0.3 %) or "big_step" (5 %)
    deadband: float  # true valve deadband, % of span
    resolution: float  # true valve resolution, % of span

    @property
    def name(self) -> str:
        """Short unique label of the case."""
        return (f"K{self.gain}_tau{self.tau_s:g}_n{self.noise_fraction}_{self.load}"
                f"_db{self.deadband}_res{self.resolution}")


def dwell_for(tau_s: float) -> float:
    """Return the dwell per step in seconds: ceil(6 (tau + theta) / 10) * 10."""
    return math.ceil(6.0 * (tau_s + THETA_S) / 10.0) * 10.0


def _valve_pairs() -> list[tuple[float, float]]:
    """Return the (deadband, resolution) pairs: healthy valve, or resolution <= deadband."""
    pairs = []
    for deadband, resolution in product((0.0, 0.3, 0.8, 2.0), (0.0, 0.1, 0.4)):
        if deadband == 0.0 and resolution != 0.0:
            continue
        if resolution <= deadband:
            pairs.append((deadband, resolution))
    return pairs


def all_cases() -> list[Case]:
    """Enumerate the full validation grid of cases."""
    grid = product((0.8, 2.0, -1.5), (3.0, 20.0), (0.0, 0.05, 0.2), ("none", "step"),
                   _valve_pairs())
    return [Case(g, tau, n, load, db, res) for g, tau, n, load, (db, res) in grid]


def abort_cases() -> list[Case]:
    """Return the cases with a large (5 %) load disturbance for the abort check."""
    return [Case(2.0, 3.0, 0.05, "big_step", 0.3, 0.1)]


class StrokeValve:
    """Stick-slip valve with reversal deadband and same-direction resolution.

    Model: the valve remembers the last direction of command motion. When the command
    reverses, the command value at the turn is the reversal point and the valve holds
    still until the command has travelled `deadband` from that point. Once free, in the
    same direction it holds until |command - position| exceeds `resolution`, then it
    jumps to the command. deadband = resolution = 0 gives an exact follower.
    """

    def __init__(self, deadband: float, resolution: float) -> None:
        """Store the valve parameters (% of span); state is set by `reset`."""
        self.deadband = deadband
        self.resolution = resolution
        self.position = 0.0  # valve position, % of span
        self.direction = 1  # last direction of command motion (+1 up, -1 down)
        self.last_command = 0.0  # previous command, % of span
        self.reversal_point = 0.0  # command value where the direction last changed
        self.free = True  # False while the reversal deadband is still being crossed

    def reset(self, position: float) -> None:
        """Start at `position` (% of span) with direction up and no pending deadband."""
        self.position = position
        self.last_command = position
        self.reversal_point = position
        self.direction = 1
        self.free = True

    def _track_direction(self, command: float) -> None:
        """Detect a reversal of command motion and arm the deadband."""
        direction = 1 if command > self.last_command else -1
        if direction != self.direction:
            self.direction = direction
            self.reversal_point = self.last_command
            self.free = self.deadband <= 0.0
        self.last_command = command

    def move(self, command: float) -> float:
        """Apply a command (% of span) and return the new valve position (% of span)."""
        if command == self.last_command:
            return self.position
        self._track_direction(command)
        if not self.free and abs(command - self.reversal_point) >= self.deadband:
            self.free = True
        if self.free and abs(command - self.position) > self.resolution:
            self.position = command
        return self.position


def _noise_series(case: Case, n: int, rng: np.random.Generator) -> np.ndarray:
    """Return n noise samples with std = noise_fraction * |gain| (PV units)."""
    std = case.noise_fraction * abs(case.gain)
    return rng.normal(0.0, std, n) if std > 0 else np.zeros(n)


def _command_series(op_start: float, steps: list[tuple[float, float]]) -> np.ndarray:
    """Expand the plan into a per-second OP series with the initial hold."""
    plan = [(op_start, steps[0][1])] + list(steps)
    return np.concatenate([np.full(int(round(d / DT_S)), op) for op, d in plan])


def simulate_test(case: Case, op_start: float, steps: list[tuple[float, float]],
                  seed: int) -> dict:
    """Simulate a manual-mode stroke test and return t_s, op, pv and the true valve values."""
    rng = np.random.default_rng(seed)
    op = _command_series(op_start, steps)
    n = len(op)
    load_at = int(rng.integers(0, n))  # load step time, sample index
    load_size = LOAD_SIZE[case.load]
    noise = _noise_series(case, n, rng)
    valve = StrokeValve(case.deadband, case.resolution)
    valve.reset(op_start)
    plant = Fopdt(case.gain, case.tau_s, THETA_S, DT_S)
    pv = np.empty(n)
    for k in range(n):
        u = valve.move(float(op[k])) - op_start + (load_size if k >= load_at else 0.0)
        pv[k] = 50.0 + plant.value + noise[k]  # PV before this input acts, PV units
        plant.update(u)
    return {"t_s": np.arange(n) * DT_S, "op": op, "pv": pv,
            "true_deadband": case.deadband, "true_resolution": case.resolution}
