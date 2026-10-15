"""Synthetic closed loops for calibrating the stiction tests (exp13): never SACAC data.

A PI controller drives a first-order (kind F) or integrating (kind L) process through the
two-parameter stiction valve of the simulator package. Non-sticking oscillating loops get a
sinusoidal load disturbance on top of a constant load and a healthy valve.
Returns (sp, pv, op, label) with label 1 = sticking.
"""

from __future__ import annotations

import numpy as np
from crosscut_sim.valve import StictionSpec, StictionValve

N_SAMPLES = 6000


def simulate(rng: np.random.Generator, kind: str, sticking: bool) -> tuple[np.ndarray, ...]:
    """One closed-loop record of 6000 samples (dt = 1): sp, pv, op, sticking label."""
    tau = rng.uniform(10.0, 40.0)
    gain = 1.0 if kind == "F" else rng.uniform(0.02, 0.06)
    kc = rng.uniform(0.6, 1.5) if kind == "F" else rng.uniform(1.0, 3.0)
    ti = tau * rng.uniform(0.8, 1.5) if kind == "F" else rng.uniform(40.0, 120.0)
    band = rng.uniform(1.0, 4.0)
    valve = StictionValve(
        StictionSpec(band, band * rng.uniform(0.3, 0.8)) if sticking else StictionSpec()
    )
    period = rng.uniform(60.0, 300.0)
    dist_amp = 0.0 if sticking else rng.uniform(0.5, 2.0)
    noise_sd = rng.uniform(0.02, 0.15)
    load = rng.uniform(1.0, 3.0) * rng.choice(
        [-1.0, 1.0]
    )  # constant load: the valve must move to hold sp
    pv = np.zeros(N_SAMPLES)
    op = np.zeros(N_SAMPLES)
    integral, y = 0.0, 0.0
    for t in range(N_SAMPLES):
        err = -y
        integral += kc * err / ti
        op[t] = kc * err + integral
        u = valve.move(op[t]) + load + dist_amp * np.sin(2 * np.pi * t / period)
        y += (gain * u - y) / tau if kind == "F" else gain * u
        pv[t] = y + noise_sd * rng.standard_normal()
    return np.zeros(N_SAMPLES), pv, op, np.array(float(sticking))
