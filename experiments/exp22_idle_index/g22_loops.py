"""G22 synthetic loop generator for experiment 22 (idle index): FOPDT plant + PI controller.

Cases are 3 gains x 3 lag/dead-time pairs x 4 tunings x 3 disturbance kinds x 3 noise levels.
Independent of the detector under test; uses only crosscut_sim (Fopdt, PID, OU).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
from crosscut_sim.core import Fopdt
from crosscut_sim.disturbances import OrnsteinUhlenbeck, OuShape
from crosscut_sim.pid import PID, OutputLimits, PidTuning

DT_S = 1.0  # sample time [s]
N_SAMPLES = 8000  # samples per run [-]
OUT_BIAS = 50.0  # controller output bias [%]
PV_OPERATING_POINT = 50.0  # PV at the operating point [%]
SP_VALUE = 50.0  # constant set point [%]
GAINS = (1.0, -1.0, 3.0)  # plant gain K [PV % per OUT %]
LAGS = ((20.0, 2.0), (60.0, 10.0), (150.0, 30.0))  # (tau_s, theta_s) [s]
TUNINGS = ("good", "aggressive", "sluggish", "mild")
DISTURBANCES = ("steps", "steps_ou", "ou")
NOISE_FRACTIONS = (0.0, 0.005, 0.02)  # noise std as fraction of 10 |K| [-]
DEV_SEEDS = range(0, 20)
TEST_SEEDS = range(100, 120)

# (Kc multiplier, Ti multiplier) per tuning
_MULTIPLIERS = {
    "good": (1.0, 1.0),
    "aggressive": (1.8, 0.7),
    "sluggish": (0.2, 4.0),
    "mild": (0.5, 2.0),
}
_STEP_LIMIT = 15.0  # half-range of step disturbance levels [OUT %]


@dataclass(frozen=True)
class Case:
    """One simulated loop configuration."""

    gain: float
    tau_s: float
    theta_s: float
    tuning: str
    disturbance: str
    noise_fraction: float

    @property
    def name(self) -> str:
        """Human-readable case label."""
        return (
            f"K={self.gain:g} tau={self.tau_s:g} theta={self.theta_s:g} "
            f"{self.tuning} {self.disturbance} noise={self.noise_fraction:g}"
        )


def all_cases() -> list[Case]:
    """Return all 324 cases (gain x lag x tuning x disturbance x noise)."""
    combos = itertools.product(GAINS, LAGS, TUNINGS, DISTURBANCES, NOISE_FRACTIONS)
    return [Case(k, lag[0], lag[1], t, d, n) for k, lag, t, d, n in combos]


def pi_settings(case: Case) -> tuple[float, float]:
    """Return (kc [OUT %/PV %], ti_s [s]) from SIMC with tau_c = theta, scaled by tuning."""
    tau_c = case.theta_s
    kc = case.tau_s / (abs(case.gain) * (tau_c + case.theta_s))
    ti_s = min(case.tau_s, 4.0 * (tau_c + case.theta_s))
    kc_mult, ti_mult = _MULTIPLIERS[case.tuning]
    return kc * kc_mult, ti_s * ti_mult


def _step_disturbance(case: Case, rng: np.random.Generator) -> np.ndarray:
    """Piecewise-constant disturbance [OUT %]: 0 until first event, then uniform levels."""
    p_event = 1.0 / (10.0 * (case.tau_s + case.theta_s))  # per-sample probability [-]
    events = rng.random(N_SAMPLES) < p_event
    levels = rng.uniform(-_STEP_LIMIT, _STEP_LIMIT, N_SAMPLES)
    last = np.maximum.accumulate(np.where(events, np.arange(N_SAMPLES), 0))
    return np.where(events[last], levels[last], 0.0)


def _ou_disturbance(case: Case, rng: np.random.Generator) -> np.ndarray:
    """Ornstein-Uhlenbeck disturbance [OUT %] with sigma from the disturbance kind."""
    sigma = 5.0 if case.disturbance == "ou" else 2.0
    ou = OrnsteinUhlenbeck(OuShape(0.0, sigma, case.tau_s), DT_S, rng)
    return np.array([ou.update() for _ in range(N_SAMPLES)])


def _disturbance(case: Case, rng: np.random.Generator) -> np.ndarray:
    """Load disturbance sequence d_k [OUT %] for the case."""
    d = np.zeros(N_SAMPLES)
    if case.disturbance in ("steps", "steps_ou"):
        d += _step_disturbance(case, rng)
    if case.disturbance in ("steps_ou", "ou"):
        d += _ou_disturbance(case, rng)
    return d


def _build_loop(case: Case) -> tuple[Fopdt, PID]:
    """Create the plant and the bumplessly initialised PI controller."""
    kc, ti_s = pi_settings(case)
    plant = Fopdt(case.gain, case.tau_s, case.theta_s, DT_S)
    pid = PID(PidTuning(kc, ti_s), DT_S, OutputLimits(0.0, 100.0), direct=case.gain < 0)
    pid.update(PV_OPERATING_POINT, SP_VALUE, "MAN", OUT_BIAS)
    return plant, pid


def simulate(case: Case, seed: int) -> dict:
    """Run one closed-loop simulation; return t_s, pv, sp, out arrays and true_gain_sign."""
    rng = np.random.default_rng(seed)
    d = _disturbance(case, rng)
    noise_std = case.noise_fraction * 10.0 * abs(case.gain)  # [PV %]
    noise = rng.standard_normal(N_SAMPLES) * noise_std
    plant, pid = _build_loop(case)
    pv = np.zeros(N_SAMPLES)
    out = np.zeros(N_SAMPLES)
    for k in range(N_SAMPLES):
        pv[k] = PV_OPERATING_POINT + plant.value + noise[k]
        out[k] = pid.update(pv[k], SP_VALUE, "AUTO")
        plant.update((out[k] - OUT_BIAS) + d[k])
    return {
        "t_s": np.arange(N_SAMPLES) * DT_S,
        "pv": pv,
        "sp": np.full(N_SAMPLES, SP_VALUE),
        "out": out,
        "true_gain_sign": 1 if case.gain > 0 else -1,
    }
