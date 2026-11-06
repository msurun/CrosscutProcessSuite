"""Simulated first-order process with a PI controller, for the tuning-live e2e (ADR 014, L5).

One process, used twice with the same numbers: the live stack (tuning_stack.py) steps it in real
time on the OPC UA server, with the controller gain and integral time read from the server nodes
the gateway writes; `make_tuning_dataset.py` records the same process into a dataset so the
Tuning view can propose from it. PV follows OUT with gain 1, time constant 8 s, dead time 0.5 s
and a little measurement noise; the SP steps between 40 and 50 every 40 s after a quiet start.
"""

from __future__ import annotations

from collections import deque

import numpy as np

TAU_S = 8.0
THETA_S = 0.5
PROCESS_GAIN = 1.0
NOISE_SD = 0.03
TICK_S = 0.1  # integration step of the process
START_VALUE = 40.0
SP_LOW, SP_HIGH = 40.0, 50.0
SP_QUIET_S = 30.0  # SP stays at SP_LOW this long, so a history window can start at rest
SP_HALF_PERIOD_S = 40.0
INITIAL_KP = 1.0  # OUT per PV unit
INITIAL_TI_S = 10.0
OUT_RANGE = (0.0, 100.0)


def setpoint_at(t_s: float) -> float:
    """Setpoint at `t_s` seconds after the start: quiet at SP_LOW, then a step every half period."""
    if t_s < SP_QUIET_S:
        return SP_LOW
    phase = int((t_s - SP_QUIET_S) // SP_HALF_PERIOD_S)
    return SP_HIGH if phase % 2 == 0 else SP_LOW


class LoopSim:
    """The process and its incremental PI controller, started at rest at START_VALUE."""

    def __init__(self, seed: int = 1) -> None:
        """Start with PV = OUT = START_VALUE and zero error."""
        self._rng = np.random.default_rng(seed)
        self._pv = START_VALUE
        self._out = START_VALUE
        self._prev_error = 0.0
        self._delay: deque[float] = deque([START_VALUE] * max(1, round(THETA_S / TICK_S)))

    def advance(self, setpoint: float, kp: float, ti_s: float) -> tuple[float, float]:
        """One TICK_S step with the given tuning; returns (measured PV, OUT)."""
        measured = self._pv + float(self._rng.normal(0.0, NOISE_SD))
        error = setpoint - measured
        step = kp * (error - self._prev_error) + kp * error * TICK_S / ti_s
        self._prev_error = error
        self._out = float(np.clip(self._out + step, *OUT_RANGE))
        self._delay.append(self._out)
        applied = self._delay.popleft()
        target = START_VALUE + PROCESS_GAIN * (applied - START_VALUE)
        self._pv += TICK_S * (target - self._pv) / TAU_S
        return measured, self._out


def record(
    duration_s: float, sample_s: float, tuning: tuple[float, float]
) -> dict[str, np.ndarray]:
    """Run the loop for `duration_s` with a fixed tuning (kp, ti_s); sample every `sample_s`."""
    sim = LoopSim()
    every = round(sample_s / TICK_S)
    rows: dict[str, list[float]] = {"t": [], "pv": [], "sp": [], "out": []}
    for tick in range(round(duration_s / TICK_S)):
        t_s = tick * TICK_S
        setpoint = setpoint_at(t_s)
        pv, out = sim.advance(setpoint, *tuning)
        if tick % every == 0:
            for name, value in zip(rows, (t_s, pv, setpoint, out), strict=True):
                rows[name].append(value)
    return {name: np.array(values) for name, values in rows.items()}
