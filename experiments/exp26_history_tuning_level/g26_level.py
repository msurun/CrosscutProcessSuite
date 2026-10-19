"""Generator G26: integrator-with-dead-time level loops under a running PI controller.

Produces closed-loop history records and PI step responses for experiment 26. Independent of
the code under test (uses only the crosscut_sim PID and Ornstein-Uhlenbeck classes).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from itertools import product

import numpy as np
from crosscut_sim.disturbances import OrnsteinUhlenbeck, OuShape
from crosscut_sim.pid import PID, OutputLimits, PidTuning

DT_S = 1.0  # sample time, s
N_HISTORY = 8000  # history length, samples
OP_BIAS = 50.0  # OP at which the plant is at rest, %
PV_START = 50.0  # initial PV and SP, %
RATES = (0.01, 0.05)  # integrator gain k, %PV per %OP per s
DELAYS = (2.0, 10.0)  # dead time theta, s
TUNINGS = ("good", "sluggish")  # SIMC tau_c multiplier m = 1 and 3
_MULTIPLIER = {"good": 1.0, "sluggish": 3.0}
LOADS = (0.0, 1.0)  # load disturbance std, % OP
NOISES = (0.0, 0.2)  # measurement noise std, % PV
SEEDS = range(0, 25)
SP_STEP_SPACING_S = 1500.0  # mean time between SP steps, s
SP_STEP_RANGE = (2.0, 8.0)  # SP step magnitude, % PV
SP_LIMITS = (30.0, 70.0)  # SP bounds, % PV
LOAD_TAU_S = 200.0  # load OU time constant, s
RESPONSE_STEP = 5.0  # SP step in step_response, % PV
_STEP_TIME_S = 50.0  # time of the SP step in step_response, s


@dataclass(frozen=True)
class Case:
    """One simulated loop cell: plant rate, dead time, tuning label, load and noise levels."""

    rate: float  # %PV per %OP per s
    delay_s: float  # s
    tuning: str  # "good" or "sluggish"
    load_std: float  # % OP
    noise_std: float  # % PV

    @property
    def name(self) -> str:
        """Short unique label of the case."""
        return (
            f"k{self.rate:g}_th{self.delay_s:g}_{self.tuning}"
            f"_L{self.load_std:g}_N{self.noise_std:g}"
        )


def all_cases() -> list[Case]:
    """Return all 32 cases in a fixed order."""
    grid = product(RATES, DELAYS, TUNINGS, LOADS, NOISES)
    return [Case(*cell) for cell in grid]


def running_pi(case: Case) -> tuple[float, float]:
    """Return the running controller (kc, ti_s) from SIMC for an integrating process."""
    tau_c = case.delay_s * _MULTIPLIER[case.tuning]  # closed-loop time constant, s
    kc = 1.0 / (case.rate * (tau_c + case.delay_s))  # %OP per %PV
    ti_s = 4.0 * (tau_c + case.delay_s)  # s
    return kc, ti_s


class IntegratorWithDelay:
    """Pure integrator with dead time: dPV/dt = rate * u(t - delay)."""

    def __init__(self, rate: float, delay_s: float, dt_s: float) -> None:
        """Create the plant at rest (deviation 0) with an empty delay line."""
        self.rate = rate  # %PV per %OP per s
        self.dt_s = dt_s  # s
        self.state = 0.0  # PV deviation from PV_START, %
        self._line = deque([0.0] * round(delay_s / dt_s))

    def update(self, u: float) -> float:
        """Advance one sample with input u (% OP deviation); return the PV deviation (%)."""
        self._line.append(u)
        u_delayed = self._line.popleft()
        # Forward Euler is accurate enough here: dt = 1 s is far below the loop time scales.
        self.state += self.rate * u_delayed * self.dt_s
        return self.state


def _next_sp(sp: float, rng: np.random.Generator) -> float:
    """Return a new SP: old SP +- uniform step, reflected into SP_LIMITS and clipped."""
    low, high = SP_LIMITS
    step = rng.uniform(*SP_STEP_RANGE) * rng.choice((-1.0, 1.0))  # % PV
    new = sp + step
    if new > high:
        new = 2.0 * high - new
    elif new < low:
        new = 2.0 * low - new
    return float(np.clip(new, low, high))


def _history_sp(n: int, rng: np.random.Generator) -> np.ndarray:
    """Piecewise-constant SP (% PV) with Poisson step events of mean spacing SP_STEP_SPACING_S."""
    events = rng.random(n) < DT_S / SP_STEP_SPACING_S  # one draw per sample
    sp = np.empty(n)
    current = PV_START
    for k in range(n):
        if events[k]:
            current = _next_sp(current, rng)
        sp[k] = current
    return sp


def _load_and_noise(case: Case, n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Draw load d (% OP, OU) and measurement noise (% PV) arrays of length n."""
    shape = OuShape(0.0, case.load_std, LOAD_TAU_S)
    ou = OrnsteinUhlenbeck(shape, DT_S, rng)
    load = np.array([ou.update() for _ in range(n)])  # draws only if load_std > 0
    noise = case.noise_std * rng.standard_normal(n)
    return load, noise


def _closed_loop(case: Case, gains: tuple[float, float], sp: np.ndarray,
                 rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Run PI + plant against sp with the case's load and noise; return (op, pv_meas)."""
    n = len(sp)
    load, noise = _load_and_noise(case, n, rng)
    plant = IntegratorWithDelay(case.rate, case.delay_s, DT_S)
    # rate > 0: more OP raises PV, so the controller must be reverse acting (direct=False).
    pid = PID(PidTuning(*gains), DT_S, OutputLimits(0.0, 100.0), direct=False)
    pid.update(PV_START, PV_START, "MAN", OP_BIAS)
    op = np.empty(n)
    pv = np.empty(n)
    deviation = 0.0  # plant PV deviation, %
    for k in range(n):
        pv[k] = PV_START + deviation + noise[k]
        op[k] = pid.update(pv[k], sp[k], "AUTO")
        deviation = plant.update((op[k] - OP_BIAS) + load[k])
    return op, pv


def simulate_history(case: Case, seed: int) -> dict:
    """Simulate N_HISTORY samples of the running loop; return dict(t_s, sp, op, pv)."""
    rng = np.random.default_rng(seed)
    sp = _history_sp(N_HISTORY, rng)
    op, pv = _closed_loop(case, running_pi(case), sp, rng)
    return {"t_s": np.arange(N_HISTORY) * DT_S, "sp": sp, "op": op, "pv": pv}


def step_response(case: Case, kc: float, ti_s: float, seed: int) -> dict:
    """Simulate a +RESPONSE_STEP SP step at 50 s under PI; return dict(t_s, sp, pv, op)."""
    rng = np.random.default_rng(seed)
    horizon_s = _STEP_TIME_S + 40.0 * (case.delay_s + 4.0 / (case.rate * kc))
    n = math.ceil(horizon_s / DT_S)
    t_s = np.arange(n) * DT_S
    sp = np.where(t_s < _STEP_TIME_S, PV_START, PV_START + RESPONSE_STEP)
    op, pv = _closed_loop(case, (kc, ti_s), sp, rng)
    return {"t_s": t_s, "sp": sp, "pv": pv, "op": op}
