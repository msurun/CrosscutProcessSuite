"""Model-predicted closed-loop comparison of two PID tunings on a FOPDT process (ADR 014).

A deliberately simple, deterministic simulation: a unit setpoint step on the loop
"ideal PID (derivative on the measurement, filter Tf = Td / N) + FOPDT plant", pure numpy,
fixed horizon, no randomness. The numbers are a MODEL PREDICTION, not a measurement; the plant
has no noise, no saturation, no valve dynamics and no model error. Nothing here writes anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp

import numpy as np

from crosscut_loops.tuning_rules import FopdtModel

HORIZON_FACTOR = 30.0  # horizon = 30 * (tau + theta), seconds: long enough for any sane tuning
STEPS = 6000  # fixed number of samples; dt = horizon / STEPS = (tau + theta) / 200
FILTER_RATIO_N = 10.0  # derivative filter Tf = Td / N, as in PidSettings
SETTLING_BAND = 0.02  # settling = last time the PV is outside +-2 % of the step size
DIVERGENCE_LIMIT = 1.0e3  # |PV| above this (in step sizes) marks the loop as diverged
MS_POINTS = 4000  # log-spaced frequencies for the sensitivity peak
MS_W_MIN_FACTOR = 1.0e-3  # lowest frequency = 1e-3 / (tau + theta), rad/s
MS_W_MAX_FACTOR = 1.0e2  # highest frequency = 1e2 / theta, rad/s
PREVIEW_LABEL = "model prediction"


@dataclass(frozen=True)
class PidTerms:
    """PID terms in seconds: gain kc (OUT per PV unit), integral time ti_s, derivative td_s."""

    kc: float
    ti_s: float
    td_s: float = 0.0


@dataclass(frozen=True)
class PreviewMetrics:
    """Metrics of one simulated setpoint step (step size = 1).

    Attributes:
        iae: Integral of the absolute error over the horizon, step-size seconds.
        overshoot_pct: Peak above the setpoint, percent of the step size (>= 0).
        settling_time_s: Last time outside the +-2 % band, seconds; None if never settled.
        ms: Peak of the sensitivity function |1 / (1 + L)|, dimensionless.
        diverged: True when the simulated PV left +-DIVERGENCE_LIMIT (unstable loop).
    """

    iae: float
    overshoot_pct: float
    settling_time_s: float | None
    ms: float
    diverged: bool


def _horizon_s(model: FopdtModel) -> float:
    """Return the fixed simulation horizon in seconds."""
    return HORIZON_FACTOR * (model.time_constant_s + model.delay_s)


def simulate_step(model: FopdtModel, pid: PidTerms) -> tuple[np.ndarray, float]:
    """Simulate a unit setpoint step; return (PV samples, sampling period dt in seconds).

    Discrete PID (backward-Euler integral, filtered derivative on the measurement) on the exact
    first-order discretisation of the plant with a dead time rounded to whole samples.
    """
    dt = _horizon_s(model) / STEPS
    decay = exp(-dt / model.time_constant_s)
    gain_step = model.gain * (1.0 - decay)
    delay = int(round(model.delay_s / dt))
    y, u = np.zeros(STEPS + 1), np.zeros(STEPS)
    integ = filt = 0.0
    for k in range(STEPS):
        err = 1.0 - y[k]
        integ += pid.kc / pid.ti_s * err * dt
        filt, deriv = _derivative(pid, filt, y[k], dt)
        u[k] = pid.kc * err + integ + deriv
        delayed = u[k - delay] if k >= delay else 0.0
        nxt = decay * y[k] + gain_step * delayed
        y[k + 1] = float(np.clip(nxt, -DIVERGENCE_LIMIT, DIVERGENCE_LIMIT))
    return y, dt


def _derivative(pid: PidTerms, filt: float, pv: float, dt: float) -> tuple[float, float]:
    """Advance the PV filter one step; return (new filter state, derivative term of the OUT)."""
    if pid.td_s <= 0.0:
        return filt, 0.0
    tf = pid.td_s / FILTER_RATIO_N
    filt += dt / (tf + dt) * (pv - filt)
    return filt, -pid.kc * pid.td_s * (pv - filt) / tf


def sensitivity_peak(model: FopdtModel, pid: PidTerms) -> float:
    """Return Ms = max |1 / (1 + L(jw))| of the continuous loop L = C * P, dimensionless.

    C = kc (1 + 1/(ti s) + td s / (Tf s + 1)), P = K exp(-theta s) / (tau s + 1).
    """
    span = model.time_constant_s + model.delay_s
    w = np.logspace(
        np.log10(MS_W_MIN_FACTOR / span), np.log10(MS_W_MAX_FACTOR / model.delay_s), MS_POINTS
    )
    s = 1j * w
    ctrl = pid.kc * (1.0 + 1.0 / (pid.ti_s * s))
    if pid.td_s > 0.0:
        ctrl = ctrl + pid.kc * pid.td_s * s / (pid.td_s / FILTER_RATIO_N * s + 1.0)
    plant = model.gain * np.exp(-model.delay_s * s) / (model.time_constant_s * s + 1.0)
    return float(np.max(np.abs(1.0 / (1.0 + ctrl * plant))))


def _settling_time_s(y: np.ndarray, dt: float) -> float | None:
    """Return the time of the last sample outside the 2 % band; None if still outside at the end."""
    outside = np.nonzero(np.abs(y - 1.0) > SETTLING_BAND)[0]
    if outside.size == 0:
        return 0.0
    if outside[-1] >= len(y) - 1:
        return None
    return float((outside[-1] + 1) * dt)


def step_metrics(model: FopdtModel, pid: PidTerms) -> PreviewMetrics:
    """Simulate one tuning and extract IAE, overshoot, settling time and Ms."""
    y, dt = simulate_step(model, pid)
    return PreviewMetrics(
        iae=float(np.sum(np.abs(1.0 - y[:-1])) * dt),
        overshoot_pct=max(0.0, float(np.max(y)) - 1.0) * 100.0,
        settling_time_s=_settling_time_s(y, dt),
        ms=sensitivity_peak(model, pid),
        diverged=bool(np.max(np.abs(y)) >= DIVERGENCE_LIMIT),
    )


def preview_record(current: PreviewMetrics, proposed: PreviewMetrics) -> dict[str, object]:
    """Build the `preview` block of a tuning proposal (labelled "model prediction")."""
    return {
        "label": PREVIEW_LABEL,
        "iae_ratio": proposed.iae / current.iae,
        "overshoot_pct": {"current": current.overshoot_pct, "proposed": proposed.overshoot_pct},
        "settling_time_s": {
            "current": current.settling_time_s,
            "proposed": proposed.settling_time_s,
        },
        "ms": {"current": current.ms, "proposed": proposed.ms},
    }
