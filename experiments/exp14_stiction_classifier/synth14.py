"""Synthetic closed loops for the stiction classifier (exp14): never SACAC data.

Four cases share one PI loop: sticking valve, sine load, square load and an aggressive
tuning with dead time (healthy valve). Records are decimated by a random factor.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from crosscut_sim.valve import StictionSpec, StictionValve

N_SAMPLES = 12000
OP_LIMIT = 50.0  # controller output is clipped to [-50, 50] (percent of span)
DT_FACTORS = (1, 2, 4, 8)


@dataclass
class Loop:
    """Parameters of one closed loop (all times in samples, dt = 1)."""

    kind: str  # "F" first order, "L" integrating
    tau: float  # time constant of the first-order process
    gain: float  # process gain (PV units per OP unit; per sample for kind L)
    kc: float  # controller proportional gain
    ti: float  # controller integral time
    delay: int  # dead time in samples (valve output -> process)
    load: float  # constant load disturbance
    noise_sd: float  # measurement noise on pv


def _make_loop(rng: np.random.Generator, kind: str, tuning: bool) -> Loop:
    """Draw the process and controller; 'tuning' selects the aggressive, delayed setup."""
    tau = rng.uniform(10.0, 40.0)
    gain = 1.0 if kind == "F" else rng.uniform(0.02, 0.06)
    if tuning:
        kc = rng.uniform(2.5, 5.0) if kind == "F" else rng.uniform(6.0, 12.0)
        ti = tau if kind == "F" else rng.uniform(20.0, 40.0)
        delay = int(rng.integers(3, 9))
    else:
        kc = rng.uniform(0.6, 1.5) if kind == "F" else rng.uniform(1.0, 3.0)
        ti = tau * rng.uniform(0.8, 1.5) if kind == "F" else rng.uniform(40.0, 120.0)
        delay = 0
    load = rng.uniform(1.0, 3.0) * rng.choice([-1.0, 1.0])  # constant load: valve must move
    return Loop(kind, tau, gain, kc, ti, delay, load, rng.uniform(0.02, 0.15))


def _make_valve(rng: np.random.Generator, sticking: bool) -> StictionValve:
    """Stiction valve (deadband 1..4, jump 0.3..0.8 of it) or a healthy one."""
    if not sticking:
        return StictionValve(StictionSpec())
    band = rng.uniform(1.0, 4.0)
    return StictionValve(StictionSpec(band, band * rng.uniform(0.3, 0.8)))


def _disturbance(case: str, amp: float, period: float, t: int) -> float:
    """Load disturbance at sample t: sine, square wave (sign of the sine) or none."""
    wave = np.sin(2 * np.pi * t / period)
    if case == "sine":
        return amp * wave
    if case == "square":
        return amp * (1.0 if wave >= 0 else -1.0)
    return 0.0


def _run_loop(
    rng: np.random.Generator, loop: Loop, valve: StictionValve, dist: tuple[str, float, float]
) -> tuple[np.ndarray, np.ndarray]:
    """Closed PI loop with setpoint 0; returns (pv, op) of N_SAMPLES samples."""
    pv, op = np.zeros(N_SAMPLES), np.zeros(N_SAMPLES)
    buf = [0.0] * loop.delay  # dead time = FIFO on the valve output
    integral, y = 0.0, 0.0
    for t in range(N_SAMPLES):
        err = -y
        integral = float(np.clip(integral + loop.kc * err / loop.ti, -OP_LIMIT, OP_LIMIT))
        op[t] = np.clip(loop.kc * err + integral, -OP_LIMIT, OP_LIMIT)
        buf.append(valve.move(op[t]))
        u = buf.pop(0) + loop.load + _disturbance(dist[0], dist[1], dist[2], t)
        y += (loop.gain * u - y) / loop.tau if loop.kind == "F" else loop.gain * u
        pv[t] = y + loop.noise_sd * rng.standard_normal()
    return pv, op


def simulate14(
    rng: np.random.Generator, kind: str, case: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, int]:
    """One record: (sp, pv, op, label, dt_factor); label 1.0 = sticking, decimated by dt_factor."""
    loop = _make_loop(rng, kind, case == "tuning")
    valve = _make_valve(rng, case == "stick")
    amp = rng.uniform(0.5, 2.0) if case in ("sine", "square") else 0.0
    period = rng.uniform(60.0, 300.0)
    pv, op = _run_loop(rng, loop, valve, (case, amp, period))
    k = int(rng.choice(DT_FACTORS))  # every k-th sample, no averaging
    sp = np.zeros(N_SAMPLES)
    return sp[::k], pv[::k], op[::k], float(case == "stick"), k
