"""
g3_sim.py - Closed-loop generator for G3 experiments (stiction vs healthy valve cases).

Simulates a SISO PI/PID loop with a sticking or healthy valve, self-regulating (F)
or integrating (L) plant. Pure functions only; deterministic given an RNG.
"""

from dataclasses import dataclass, field

import numpy as np
from g3_excite import make_excitation
from g3_valve import Valve, make_valve

# Ranges for plant parameter draws (log-uniform)
GAIN_F_RANGE = (0.5, 3.0)  # dimensionless
TAU_F_RANGE = (5.0, 200.0)  # seconds
DEADTIME_FRAC_RANGE = (0.1, 2.0)  # fraction of dominant time constant
GAIN_L_RANGE = (0.002, 0.05)  # 1/s
DEADTIME_L_RANGE = (1.0, 20.0)  # seconds
TAU2_FRAC_RANGE = (0.0, 0.5)  # fraction of first lag (optional second lag)
LAG_L_RANGE = (0.0, 10.0)  # seconds (optional first-order lag)
DT_CHOICES = (1.0, 2.0, 5.0)  # seconds
N_SETTLE = 500  # samples discarded before recording
N_RECORD_MIN, N_RECORD_MAX = 2000, 8000
PHASE_MARGIN_MIN, PHASE_MARGIN_MAX = 40.0, 70.0  # degrees
MIN_CYCLES_STICK = 5
MAX_PV_SWING = 60.0  # percent; larger swings mean an unstable loop
MAX_GROWTH = 3.0  # tail/head peak-to-peak ratio above which the loop is diverging
TWIN_RATIO_MAX = 0.5  # ideal-valve twin must swing less than this fraction of the stick record
MIN_PV_SWING = 1.0  # percent
MAX_REDRAWS = 40


@dataclass
class Clean:
    """Closed-loop record: setpoint, PV, OP in percent, dt in seconds."""

    sp: np.ndarray
    pv: np.ndarray
    op: np.ndarray
    dt_s: float
    swing: float
    meta: dict = field(default_factory=dict)


@dataclass
class PlantParams:
    """Plant and controller parameters for one draw."""

    kind: str
    gain: float
    tau: float  # dominant time constant (F) or unused (L)
    tau2: float  # second lag (F) or lag (L)
    theta: float  # dead time, seconds
    dt_s: float
    n_record: int
    n_total: int
    kc: float
    ti: float
    derivative_tau: float  # derivative filter time constant (0 = no derivative)
    tscale: float  # time scale for excitation periods


@dataclass
class SimState:
    """Mutable state during a simulation step."""

    plant_y: float  # plant output deviation
    plant_y_lag: float  # second lag state (F) or lag state (L)
    op: float  # controller output, percent
    integral: float  # integral of error
    derivative_state: float  # derivative filter state
    derivative_pv_prev: float  # previous pv for derivative
    op_bias: float  # bias such that initial state is steady

    def step_derivative(self, pv: float, dt_s: float, tau_d: float) -> float:
        """Update derivative state and return derivative term."""
        if tau_d <= 0:
            return 0.0
        alpha = dt_s / (tau_d + dt_s)
        self.derivative_state = (1 - alpha) * self.derivative_state + alpha * (
            pv - self.derivative_pv_prev
        ) / dt_s
        self.derivative_pv_prev = pv
        return -tau_d * self.derivative_state  # derivative on PV, negative sign


def _log_uniform(rng: np.random.Generator, low: float, high: float) -> float:
    """Draw from log-uniform distribution in [low, high]."""
    return float(np.exp(rng.uniform(np.log(low), np.log(high))))


def _draw_dt(rng: np.random.Generator) -> float:
    """Draw sampling time from allowed choices."""
    return float(DT_CHOICES[rng.integers(0, len(DT_CHOICES))])


def _draw_record_length(rng: np.random.Generator) -> int:
    """Draw record length (after settling) between bounds."""
    return int(rng.integers(N_RECORD_MIN, N_RECORD_MAX + 1))


def _draw_deadtime_fraction(rng: np.random.Generator) -> float:
    """Draw dead time as fraction of tau (F plants)."""
    if rng.random() < 0.3:  # include deadtime-dominant draws
        return float(rng.uniform(1.0, DEADTIME_FRAC_RANGE[1]))
    return float(rng.uniform(DEADTIME_FRAC_RANGE[0], 1.0))


def draw_plant(
    rng: np.random.Generator, kind: str, case: str, dt_s: float, n_record: int
) -> PlantParams:
    """Draw plant parameters and SIMC controller tuning."""
    if kind == "F":
        gain = _log_uniform(rng, *GAIN_F_RANGE)
        tau = _log_uniform(rng, *TAU_F_RANGE)
        theta_frac = _draw_deadtime_fraction(rng)
        theta = theta_frac * tau
        tau2 = tau * float(rng.uniform(*TAU2_FRAC_RANGE))
        tau_eff = tau + tau2
        tau_c = max(theta, 0.3 * tau_eff) * float(rng.uniform(1.0, 2.0))
        kc = tau_eff / (gain * (tau_c + theta))
        ti = min(tau_eff, 4.0 * (tau_c + theta)) * float(rng.uniform(0.5, 2.0))
        tscale = tau_eff + theta
    else:  # "L"
        gain = _log_uniform(rng, *GAIN_L_RANGE)
        theta = _log_uniform(rng, *DEADTIME_L_RANGE)
        tau2 = float(rng.uniform(*LAG_L_RANGE))
        tau = 0.0
        tau_c = theta * float(rng.uniform(1.0, 3.0))
        kc = 1.0 / (gain * 2.0 * (tau_c + theta))
        ti = 4.0 * (tau_c + theta) * float(rng.uniform(1.0, 3.0))
        tscale = 4.0 * (tau_c + theta)
    derivative_tau = 0.0
    if rng.random() < 0.3:  # optional derivative filter
        derivative_tau = ti * float(rng.uniform(0.05, 0.2))
    # Apply tuning case modifications
    if case == "tuning_aggressive":
        kc *= float(rng.uniform(2.5, 4.0))
    elif case == "tuning_sluggish":
        ti *= float(rng.uniform(3.0, 6.0))
    # Ensure stability: phase margin check via simple approximation
    return PlantParams(
        kind,
        gain,
        tau,
        tau2,
        theta,
        dt_s,
        n_record,
        n_record + N_SETTLE,
        kc,
        ti,
        derivative_tau,
        tscale,
    )


def _phase_margin_ok(params: PlantParams) -> bool:
    """Check approximate phase margin for stability (healthy cases)."""
    if params.kind == "F":
        w_c = 1.0 / (params.tau + params.theta)
        pm = 90.0 - np.degrees(params.theta * w_c)
    else:
        w_c = 0.5 / params.theta
        pm = 45.0
    return PHASE_MARGIN_MIN <= pm <= PHASE_MARGIN_MAX


def _valid_draw(params: PlantParams) -> bool:
    """Return True if the draw is acceptable (stable, not degenerate)."""
    return _phase_margin_ok(params) and np.isfinite(params.kc) and params.kc > 0


def simulate_loop(
    params: PlantParams, sp: np.ndarray, load: np.ndarray, valve: Valve, load0: float
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate the closed loop; return (pv, op) arrays in percent."""
    n = len(sp)
    dt_s = params.dt_s
    # Initial op such that plant is at steady state: op0 = 50 - load0, clipped
    op0 = float(np.clip(50.0 - load0, 0.0, 100.0))
    valve.step(op0)  # initialise valve position
    state = SimState(
        plant_y=0.0,
        plant_y_lag=0.0,
        op=op0,
        integral=0.0,
        derivative_state=0.0,
        derivative_pv_prev=50.0,
        op_bias=op0,
    )
    pv_arr = np.empty(n)
    op_arr = np.empty(n)
    # Delay line for plant input (circular buffer)
    delay_steps = int(round(params.theta / dt_s))
    delay_buffer = np.zeros(delay_steps + 1)
    delay_idx = 0
    for i in range(n):
        pv = 50.0 + state.plant_y
        pv_arr[i] = pv
        op_arr[i] = state.op
        # Controller update (positional PI with derivative on PV)
        e = sp[i] - pv
        # Conditional integration anti-windup: stop integrating if op saturated
        op_unsaturated = state.op_bias + params.kc * (e + state.integral / params.ti)
        if params.derivative_tau > 0:
            op_unsaturated += state.step_derivative(pv, dt_s, params.derivative_tau)
        if (op_unsaturated <= 0.0 and e < 0.0) or (op_unsaturated >= 100.0 and e > 0.0):
            pass  # freeze integral
        else:
            state.integral += e * dt_s
        op = state.op_bias + params.kc * (e + state.integral / params.ti)
        if params.derivative_tau > 0:
            op += state.step_derivative(pv, dt_s, params.derivative_tau)
        state.op = float(np.clip(op, 0.0, 100.0))
        # Valve position (may differ from op due to stiction/actuator lag)
        valve_pos = valve.step(state.op)
        # Plant input: deviation from equilibrium plus load
        u = (valve_pos - 50.0) + load[i]
        # Delay line update
        delay_buffer[delay_idx] = u
        u_delayed = delay_buffer[(delay_idx - delay_steps) % (delay_steps + 1)]
        delay_idx = (delay_idx + 1) % (delay_steps + 1)
        # Plant dynamics
        if params.kind == "F":
            # First-order plus dead time, optional second lag
            y_new = params.gain * u_delayed
            if params.tau2 > 0:
                alpha2 = dt_s / (params.tau2 + dt_s)
                state.plant_y_lag = (1 - alpha2) * state.plant_y_lag + alpha2 * y_new
                y_new = state.plant_y_lag
            alpha = dt_s / (params.tau + dt_s)
            state.plant_y = (1 - alpha) * state.plant_y + alpha * y_new
        else:  # "L"
            # Integrator with gain, optional lag
            dy = params.gain * u_delayed * dt_s
            if params.tau2 > 0:
                alpha2 = dt_s / (params.tau2 + dt_s)
                state.plant_y_lag = (1 - alpha2) * state.plant_y_lag + alpha2 * dy
                dy = state.plant_y_lag
            state.plant_y += dy
    return pv_arr, op_arr


def _has_min_cycles(signal: np.ndarray, min_cycles: int) -> bool:
    """Check if detrended signal has at least min_cycles full cycles."""
    return count_cycles(signal) >= min_cycles


def count_cycles(signal: np.ndarray) -> int:
    """Count full cycles by zero crossings of linearly detrended signal."""
    if len(signal) < 3:
        return 0
    t = np.arange(len(signal))
    coeffs = np.polyfit(t, signal, 1)
    detrended = signal - np.polyval(coeffs, t)
    crossings = 0
    for i in range(1, len(detrended)):
        if detrended[i - 1] == 0.0:
            continue
        if (detrended[i - 1] < 0.0 < detrended[i]) or (detrended[i - 1] > 0.0 > detrended[i]):
            crossings += 1
    return crossings // 2  # full cycles = pairs of crossings


def _record_valid(rng, params, case: str, drive: tuple, pv: np.ndarray, load0: float) -> bool:
    """Stable loop; for "stick" the oscillation must vanish with an ideal valve (spec: validity)."""
    swing, quarter = float(np.ptp(pv)), len(pv) // 4
    growth = np.ptp(pv[-quarter:]) / max(float(np.ptp(pv[:quarter])), 1e-9)
    if not case.startswith("sp_") and (swing > MAX_PV_SWING or growth > MAX_GROWTH):
        return False
    if case != "stick":
        return True
    twin, _ = simulate_loop(params, drive[0], drive[1], make_valve(rng, "quiet"), load0)
    return float(np.ptp(twin[N_SETTLE:])) < TWIN_RATIO_MAX * swing


def simulate_clean(rng: np.random.Generator, kind: str, case: str) -> Clean:
    """Generate one closed-loop record; redraw until valid."""
    for _ in range(MAX_REDRAWS):
        dt_s = _draw_dt(rng)
        n_record = _draw_record_length(rng)
        params = draw_plant(rng, kind, case, dt_s, n_record)
        if not _valid_draw(params):
            continue
        # Excitation: sp around 50, load around 0, length n_total
        sp_full, load_full, exc_meta = make_excitation(
            rng, case, params.n_total, dt_s, params.tscale
        )
        valve = make_valve(rng, case)
        # Initial load (constant part) for steady-state start
        load0 = float(load_full[0])
        pv_full, op_full = simulate_loop(params, sp_full, load_full, valve, load0)
        # Discard settling samples
        pv = pv_full[N_SETTLE:]
        op = op_full[N_SETTLE:]
        sp = sp_full[N_SETTLE:]
        swing = float(np.ptp(pv))
        if not (np.all(np.isfinite(pv)) and np.all(np.isfinite(op)) and swing >= MIN_PV_SWING):
            continue
        if not _record_valid(rng, params, case, (sp_full, load_full), pv, load0):
            continue
        if case == "stick" and not _has_min_cycles(pv, MIN_CYCLES_STICK):
            continue
        meta = {
            "kind": kind,
            "case": case,
            "dt_s": dt_s,
            "n_record": n_record,
            "n_total": params.n_total,
            "gain": params.gain,
            "tau": params.tau,
            "tau2": params.tau2,
            "theta": params.theta,
            "kc": params.kc,
            "ti": params.ti,
            "derivative_tau": params.derivative_tau,
            "load0": load0,
            "swing": swing,
            "valve_model": valve.model,
            **exc_meta,
        }
        return Clean(sp=sp, pv=pv, op=op, dt_s=dt_s, swing=swing, meta=meta)
    raise RuntimeError(
        f"Could not generate valid record for kind={kind!r}, case={case!r} "
        f"after {MAX_REDRAWS} tries"
    )


if __name__ == "__main__":
    """Self-test: simulate 3 records of every kind/case combination."""
    rng = np.random.default_rng(42)
    cases = [
        "stick",
        "load_sine",
        "load_square",
        "load_multitone",
        "sp_square",
        "sp_steps",
        "tuning_aggressive",
        "tuning_sluggish",
        "quiet",
    ]
    print(f"{'kind':<4} {'case':<18} {'dt_s':>5} {'length':>7} {'cycles':>6} {'swing':>8}")
    for kind in ["F", "L"]:
        for case in cases:
            for _ in range(3):
                rec = simulate_clean(rng, kind, case)
                cycles = count_cycles(rec.pv)
                assert len(rec.sp) == len(rec.pv) == len(rec.op)
                assert np.all(np.isfinite(rec.pv)) and np.all(np.isfinite(rec.op))
                if case == "stick":
                    assert rec.meta["label"] == 1
                print(
                    f"{kind:<4} {case:<18} {rec.dt_s:>5.1f} {len(rec.pv):>7d} "
                    f"{cycles:>6d} {rec.swing:>8.2f}"
                )
