"""Shifted synthetic closed loops for testing a stiction detector (exp15): never SACAC data.

Differs from synth14: Kano full-slip stiction plus actuator lag, wider process and
tuning ranges, extra dead time and AR(1) coloured measurement noise.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

N_SAMPLES = 12000  # raw samples per record (dt = 1 sample)
LIMIT = 1e3  # pv and op are clipped to +-LIMIT so a diverging loop stays finite
DT_FACTORS = (1, 2, 4, 8)
NOISE_FRACTION = {"low": 0.05, "mid": 0.15, "high": 0.4}  # noise std / noise-free pv std


@dataclass(frozen=True)
class ShiftRecord:
    """One decimated record; label 1.0 = sticking valve, half period in returned samples."""

    sp: np.ndarray
    pv: np.ndarray
    op: np.ndarray
    label: float
    dt_factor: int
    half_cycle_samples: float


@dataclass
class Loop:
    """Parameters of one closed loop (times in raw samples)."""

    kind: str  # "F" first order, "L" integrating
    tau: float  # time constant (F only)
    gain: float  # process gain (PV per OP; per sample for L)
    kc: float  # controller gain
    ti: float  # integral time [samples]
    delay: int  # extra dead time [samples]
    lag: float  # valve actuator lag [samples]
    band: float  # stiction band (0 = healthy valve) [OP units]
    load: float  # constant load disturbance [OP units]


def _make_process(rng: np.random.Generator, kind: str) -> tuple[float, float, int]:
    """Draw (tau, gain, dead time): tau 5..80 for F, gain 0.01..0.1 per sample for L."""
    tau = rng.uniform(5.0, 80.0)
    gain = 1.0 if kind == "F" else rng.uniform(0.01, 0.1)
    return tau, gain, int(rng.integers(0, 11))


def _make_tuning(rng: np.random.Generator, kind: str, tau: float, tuned_hot: bool) -> tuple:
    """Draw (kc, ti); 'tuned_hot' picks a high gain meant to sustain an oscillation."""
    if kind == "F":
        kc = rng.uniform(3.0, 6.0) if tuned_hot else rng.uniform(0.3, 2.0)
        return kc, tau * rng.uniform(0.5, 2.0)
    kc = rng.uniform(6.0, 12.0) if tuned_hot else rng.uniform(0.5, 5.0)
    return kc, rng.uniform(30.0, 200.0)


def _clip_gain(loop: Loop) -> None:
    """Limit kc of a healthy-tuned loop with theta = delay + lag + 1 samples of lag."""
    theta = loop.delay + loop.lag + 1.0
    if loop.kind == "F":
        loop.kc = min(loop.kc, max(0.3, 1.2 * loop.tau / theta))  # kc*K < ~tau/theta
    else:
        loop.kc = min(loop.kc, 0.5 / (loop.gain * theta))  # integrator: kc*g*theta < 0.5
        loop.ti = max(loop.ti, 8.0 * theta)  # keep the integral action slow


def _make_loop(rng: np.random.Generator, kind: str, case: str) -> Loop:
    """Draw process, valve, load and controller for one record."""
    tau, gain, delay = _make_process(rng, kind)
    hot = case == "tuning"
    kc, ti = _make_tuning(rng, kind, tau, hot)
    lag = rng.uniform(2.0, 6.0)
    band = rng.uniform(1.0, 4.0) if case == "stick" else 0.0
    load = rng.uniform(1.0, 3.0) * rng.choice([-1.0, 1.0])
    if hot:
        delay = max(delay, 6)  # dead time makes the high gain oscillate
    loop = Loop(kind, tau, gain, kc, ti, delay, lag, band, load)
    if not hot:
        _clip_gain(loop)
    return loop


def _disturbance(case: str, amp: float, period: float, t: int) -> float:
    """Load disturbance at sample t [OP units]: sine, square wave or none."""
    wave = np.sin(2 * np.pi * t / period)  # period in raw samples
    if case == "sine":
        return amp * wave
    if case == "square":
        return amp * (1.0 if wave >= 0 else -1.0)
    return 0.0


def _run_loop(loop: Loop, dist: tuple[str, float, float]) -> tuple[np.ndarray, np.ndarray]:
    """Noise-free PI loop, setpoint 0; Kano valve (full slip) then lag then dead time."""
    pv, op = np.zeros(N_SAMPLES), np.zeros(N_SAMPLES)
    buf = deque([0.0] * loop.delay)  # dead time = FIFO between valve and process
    y = integral = held = moved = 0.0  # held: slip state, moved: lagged valve position
    for t in range(N_SAMPLES):
        integral = float(np.clip(integral - loop.kc * y / loop.ti, -LIMIT, LIMIT))
        op[t] = np.clip(-loop.kc * y + integral, -LIMIT, LIMIT)
        if abs(op[t] - held) > loop.band:  # Kano: ignore command until gap > band, then jump
            held = op[t]
        moved += (held - moved) / loop.lag  # first-order actuator lag
        buf.append(moved)
        u = buf.popleft() + loop.load + _disturbance(dist[0], dist[1], dist[2], t)
        y += (loop.gain * u - y) / loop.tau if loop.kind == "F" else loop.gain * u
        y = float(np.clip(y, -LIMIT, LIMIT))
        pv[t] = y
    return pv, op


def _coloured_noise(rng: np.random.Generator, n: int, sd: float) -> np.ndarray:
    """AR(1) noise with phi uniform in 0..0.6, rescaled to sample std `sd`."""
    phi = rng.uniform(0.0, 0.6)
    w = rng.standard_normal(n)
    e = np.zeros(n)
    for t in range(1, n):
        e[t] = phi * e[t - 1] + w[t]
    return e * (sd / max(float(e.std()), 1e-12))


def _half_cycle(op: np.ndarray) -> float:
    """Half period [samples] from the first autocorrelation maximum after the first zero."""
    x = op - op.mean()
    n = len(x)
    spec = np.fft.rfft(x, 2 * n)
    acf = np.fft.irfft(spec * np.conj(spec))[: n // 2]
    if acf[0] <= 1e-12:
        return float("nan")
    acf = acf / acf[0]
    neg = np.flatnonzero(acf < 0)
    if len(neg) == 0:
        return float("nan")
    lag = neg[0] + int(np.argmax(acf[neg[0] :]))
    return lag / 2.0 if acf[lag] > 0.1 and lag > neg[0] else float("nan")


def simulate_shift(rng: np.random.Generator, kind: str, case: str, noise_level: str) -> ShiftRecord:
    """One shifted record: noise-free simulation, then AR(1) noise, then decimation."""
    loop = _make_loop(rng, kind, case)
    amp = rng.uniform(0.5, 2.0) if case in ("sine", "square") else 0.0
    period = rng.uniform(40.0, 400.0)
    pv, op = _run_loop(loop, (case, amp, period))
    sd = NOISE_FRACTION[noise_level] * float(pv[N_SAMPLES // 2 :].std())  # noise-free std
    pv_noisy = pv + _coloured_noise(rng, N_SAMPLES, sd)
    k = int(rng.choice(DT_FACTORS))  # every k-th sample, no averaging
    op_k = op[::k]
    return ShiftRecord(
        sp=np.zeros(len(op_k)),
        pv=pv_noisy[::k],
        op=op_k,
        label=float(case == "stick"),
        dt_factor=k,
        half_cycle_samples=_half_cycle(op_k),
    )
