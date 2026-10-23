"""Numerics behind the tuning screen: model check, closed-loop step preview, test-window hints.

Everything here works on plain arrays and returns plain values, so the web layer only has to
choose a window and serialise the result.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from crosscut_loops.tuning_rules import FopdtModel, PiSettings

GOOD_R_SQUARED = 0.8  # share of PV variance the model explains: "good" at or above this
FAIR_R_SQUARED = 0.5  # "fair" at or above this, "poor" below
STEP_SAMPLES_PER_TIME_CONSTANT = 10  # preview resolution: the smaller of tau and delay / 10
PREVIEW_HORIZON_FACTOR = 6.0  # preview length in (time constant + delay)
PREVIEW_POINTS = 200
MAX_PREVIEW_STEPS = 20000  # upper bound on integration steps, keeps the request fast
PREVIEW_VALUE_LIMIT = 1e6  # a coarse step can make the Euler loop diverge; show a bounded value
MIN_OUT_MOVE_PCT = 1.0  # a stretch needs at least this OUT movement to count as a test
MANUAL_MODE = 0.0
MOVE_STEP_PCT = 0.5  # a sample-to-sample OUT change above this counts as a deliberate move
LEAD_S = 300.0  # quiet time kept before the first move, so the model sees the start at rest
TAIL_S = 900.0  # time kept after the last move, so the settling is inside the window


@dataclass(frozen=True)
class FitCheck:
    """How well a model reproduces the measured PV on the chosen window."""

    verdict: str  # "good", "fair" or "poor"
    r_squared: float


@dataclass(frozen=True)
class StepPreview:
    """Predicted closed-loop response of the model to a unit setpoint step."""

    t_s: np.ndarray
    pv: np.ndarray
    out: np.ndarray


def simulate_fopdt(model: FopdtModel, out: np.ndarray, dt_s: float, y0: float) -> np.ndarray:
    """PV that the model predicts for the input ``out``, starting at rest at ``y0``.

    Deviation form: the input before the window is taken as ``out[0]``, so the model only has to
    explain the movement inside the window (the identification fits a constant offset as well).

    The model is a FOPDT (first-order plus dead time): one capacity that reacts to the input
    through a pure transport delay. Its three parameters are the gain (output change per unit of
    input change at steady state), the time constant (how fast the output moves, in seconds) and
    the delay (dead time, in seconds). The recursion below is the exact discrete solution of
    ``tau * dy/dt + y = K * out(t - theta)`` (y is the PV) sampled at ``dt_s``, not an
    approximation.

    Returns one predicted value per sample of ``out`` (same length).
    """
    # Per-sample retention factor: the fraction of the previous deviation still visible after one
    # step. Exact for a first-order lag: exp(-dt_s / tau), dimensionless, in (0, 1).
    decay = float(np.exp(-dt_s / model.time_constant_s))

    # Dead time expressed in whole samples, so the input signal can be indexed. round() rather
    # than floor() because a delay between two samples is best represented by the nearest one.
    delay = int(round(model.delay_s / dt_s))

    # Deviation (y - y0, y being the PV) over time, filled in place. deviation[k] and out[k]
    # refer to the same instant: both series are aligned sample by sample.
    deviation = np.zeros(len(out))
    for k in range(len(out) - 1):
        # Input seen by the plant at step k, i.e. the value delay samples ago. Before the window
        # starts there is no history, so the pre-window input is assumed constant at out[0].
        delayed = out[k - delay] if k >= delay else out[0]

        # Forcing term over one step, from integrating the ODE with a constant input:
        # K * (1 - decay) * (u_delayed - u0). Unit: output units (gain times input units).
        drive = model.gain * (1.0 - decay) * (delayed - out[0])

        # Exponential-euler update: the previous deviation decays by `decay` while the input adds
        # `drive`. Equivalent to the standard filtered-form FOPDT recursion.
        deviation[k + 1] = decay * deviation[k] + drive

    # Skip back to absolute values: the recursion ran on deviations from y0.
    return y0 + deviation


def fit_check(
    model: FopdtModel, out: np.ndarray, pv: np.ndarray, dt_s: float
) -> tuple[FitCheck, np.ndarray]:
    """Compare the model with the measurement: R-squared, a verdict and the simulated PV.

    A first-order-plus-dead-time (FOPDT) model outputs a process variable (PV)
    from a manipulated variable (MV). We run it with the same MV sequence as the
    measurement and judge how well the result tracks the measured PV.

    Args:
        model: The fitted FOPDT model parameters.
        out: MV sequence (e.g. valve position in %), one sample per index.
        pv: Measured PV sequence, same length and time base as out.
        dt_s: Sampling interval in seconds.

    Returns:
        A ``(FitCheck, simulated)`` pair: the verdict and R-squared score, plus
        the simulated PV sequence on the same time base as pv.
    """
    # Simulate the model from the initial condition taken from the first sample
    # of the measurement, so both series start at the same point.
    simulated = simulate_fopdt(model, out, dt_s, float(pv[0]))
    # "Total sum of squares": how much the measured PV varies around its own
    # mean. It is the yardstick every R-squared score is measured against.
    spread = float(np.sum((pv - np.mean(pv)) ** 2))
    # R-squared = 1 - SSE/SST: the fraction of the measurement's variation the
    # model explains. Note `simulated` holds the noise-free model output, so
    # this denominator's SSE compares model residual to measurement spread.
    # When the measurement is constant (spread == 0) R-squared is undefined,
    # so we fall back to 0.0 rather than dividing by zero.
    r_squared = 1.0 - float(np.sum((pv - simulated) ** 2)) / spread if spread > 0.0 else 0.0
    return FitCheck(_verdict(r_squared), r_squared), simulated


def _verdict(r_squared: float) -> str:
    """Plain-language verdict for an R-squared value."""
    if r_squared >= GOOD_R_SQUARED:
        return "good"
    return "fair" if r_squared >= FAIR_R_SQUARED else "poor"


def closed_loop_step(model: FopdtModel, settings: PiSettings) -> StepPreview:
    """Simulate the loop (PI controller plus the model) for a unit setpoint step at time 0.

    Positional PI with a rectangular integral; the preview shows what the chosen robustness
    would do on the identified model, not on the real plant.

    Returns a coarse preview of the closed-loop response: the process variable and the
    controller output sampled at PREVIEW_POINTS equally spaced instants, starting at t = 0.
    """

    # Discrete integration time step: each dominant dynamic (time constant and dead time) is
    # sampled STEP_SAMPLES_PER_TIME_CONSTANT times. Taking the smaller of the two makes sure
    # the fastest of them is resolved well enough to keep the rectangular rule accurate [s].
    dt_s = min(model.time_constant_s, model.delay_s) / STEP_SAMPLES_PER_TIME_CONSTANT

    # Total simulated time; the response has essentially settled by then. PREVIEW_HORIZON_FACTOR
    # is the number of combined dynamics (time constant + dead time) the preview covers [s].
    horizon_s = PREVIEW_HORIZON_FACTOR * (model.time_constant_s + model.delay_s)

    # Cap the step count: for an extreme tau/delay ratio the step above would mean millions
    # of Euler steps. A coarser step loses accuracy there; the preview is coarse by design.
    dt_s = max(dt_s, horizon_s / MAX_PREVIEW_STEPS)

    # Number of integration steps, rounded up so the loop reaches at least the horizon.
    n_steps = int(np.ceil(horizon_s / dt_s))

    # Full-resolution simulation over n_steps instants, one PV/OUT pair per step.
    with np.errstate(all="ignore"):
        pv, out = _run_pi_loop(model, settings, dt_s, n_steps)
    pv, out = _bounded(pv), _bounded(out)

    # keep holds the indices of the samples we display. linspace spans the full range
    # 0 .. n_steps - 1 with at most PREVIEW_POINTS points, cast to int so they can index
    # the full-resolution arrays; the preview stays inside the simulated window.
    keep = np.linspace(0, n_steps - 1, min(PREVIEW_POINTS, n_steps)).astype(int)

    # Turn the indices back into seconds and pick the previewed pv and out samples.
    return StepPreview(t_s=keep * dt_s, pv=pv[keep], out=out[keep])


def _bounded(values: np.ndarray) -> np.ndarray:
    """Replace NaN and clip to +-PREVIEW_VALUE_LIMIT so a diverged preview stays JSON-safe."""
    limit = PREVIEW_VALUE_LIMIT
    return np.asarray(np.clip(np.nan_to_num(values, nan=limit), -limit, limit))


def _run_pi_loop(
    model: FopdtModel, settings: PiSettings, dt_s: float, n_steps: int
) -> tuple[np.ndarray, np.ndarray]:
    """Time loop of :func:`closed_loop_step`: returns the PV and OUT deviation arrays.

    Simulates a PI controller driving a first-order-plus-dead-time (FOPDT) process
    with unit step setpoint change. All values are deviations from steady state.

    Args:
        model: FOPDT process parameters (gain, time constant in s, dead time in s).
        settings: PI tuning parameters (gain ``kc``, integral time ``ti_s`` in s).
        dt_s: simulation time step in seconds.
        n_steps: number of time steps to simulate.

    Returns:
        Tuple ``(pv, out)`` of arrays of length ``n_steps``: process variable
        (controlled output) and controller output, both as deviations.
    """
    # Closed-form discretisation of the FOPDT first-order lag:
    # pv[k+1] = decay*pv[k] + K*(1-decay)*u[k-d], where decay = exp(-dt_s/tau).
    # Derivation: exact solution of tau*dpv/dt + pv = K*u over one time step
    # with u held constant (zero-order hold).
    decay = float(np.exp(-dt_s / model.time_constant_s))
    # Dead time expressed in whole samples: the number of past OUT samples to skip.
    # Rounding keeps the nearest integer; max(1, ...) avoids a zero-sample (no) delay.
    delay = max(1, int(round(model.delay_s / dt_s)))
    pv = np.zeros(n_steps)
    out = np.zeros(n_steps)
    # Integral of the error, accumulated in error units times seconds.
    integral = 0.0
    # One-step lookahead: each iteration writes pv[k+1], so we stop one step early
    # and back-fill the final OUT sample afterwards.
    for k in range(n_steps - 1):
        # Setpoint is a unit step: reference stays at 1.0 in deviation units.
        error = 1.0 - pv[k]
        # Rectangular (Euler) integration of the error over one time step.
        integral += error * dt_s
        # PI control law: u = kc*(e + (1/ti)*integral(e dt)).
        out[k] = settings.kc * (error + integral / settings.ti_s)
        # Dead-time buffer: the process sees OUT from `delay` samples ago.
        # Samples before the buffer is full have not yet reached the process => 0.
        delayed = out[k - delay] if k >= delay else 0.0
        pv[k + 1] = decay * pv[k] + model.gain * (1.0 - decay) * delayed
    # The loop stopped at k = n_steps-2; repeat the last OUT value to fill the array.
    out[-1] = out[-2]
    return pv, out


def suggest_windows(
    t_s: np.ndarray, mode: np.ndarray, out: np.ndarray, min_length_s: float
) -> list[tuple[float, float]]:
    """Manual-mode stretches in which the output really moved: good places to identify a model.

    A loop in MAN is open, so the response to OUT is not distorted by the controller. Each stretch
    is trimmed to a lead before the first OUT move and a tail after the last one. Returns
    (start_s, end_s) pairs, the biggest OUT movement first.

    Parameters
    ----------
    t_s : np.ndarray
        Sample times, in seconds (s), one per sample, assumed increasing.
    mode : np.ndarray
        Controller mode per sample; the numeric code MANUAL_MODE means the loop is open.
    out : np.ndarray
        Controller output (OUT) per sample, in percent; its moves are what excites the process.
    min_length_s : float
        Shortest accepted stretch, in seconds (s); shorter ones are discarded.

    Returns
    -------
    list[tuple[float, float]]
        (start_s, end_s) in seconds (s), sorted by decreasing peak-to-peak OUT move.
    """
    # Boolean mask, one entry per sample: True where the controller is in manual (open loop).
    manual = mode == MANUAL_MODE

    # How the run-detection works: padding the mask with a 0 on each side and taking the
    # first difference gives +1 at the first sample of a run and -1 at the sample just after
    # the last one. flatnonzero therefore returns alternating [run_start, run_stop, ...]
    # indices, where a run spans samples first .. stop-1 (stop is exclusive).
    edges = np.flatnonzero(np.diff(np.concatenate(([0], manual.astype(int), [0]))))

    # Each kept entry is (start_s, end_s, movement), movement being the peak-to-peak OUT change
    # over the stretch, used only as a ranking key.
    found: list[tuple[float, float, float]] = []
    for first, stop in zip(edges[::2], edges[1::2], strict=True):
        # _trim_to_moves drops idle lead-in/tail around the actual OUT moves and returns the
        # trimmed (start_s, end_s), or None when the stretch holds no usable movement.
        window = _trim_to_moves(t_s[first:stop], out[first:stop])
        # Keep only stretches long enough to identify a model: the response to the OUT move
        # needs time to develop, hence the minimum duration in seconds.
        if window is not None and window[1] - window[0] >= min_length_s:
            # np.ptp = max - min, i.e. the peak-to-peak amplitude of OUT over the stretch.
            found.append((*window, float(np.ptp(out[first:stop]))))

    # Sort by decreasing movement: the largest OUT excursion gives the best signal-to-noise.
    found.sort(key=lambda item: -item[2])
    # Drop the ranking key; the caller only needs the time bounds.
    return [(start, end) for start, end, _ in found]


def _trim_to_moves(t_s: np.ndarray, out: np.ndarray) -> tuple[float, float] | None:
    """Span of one MAN stretch from LEAD_S before its first OUT move to TAIL_S after its last."""
    # `out` is the controller output in percent and `t_s` its time in seconds over one manual
    # stretch. Only the span around real OUT moves is kept, so idle time before and after does
    # not dilute the identification.
    # `np.ptp` is "peak to peak", i.e. max minus min: the total spread of OUT, in percent.
    # A trace that barely wiggles carries no usable move information, so it is rejected.
    if float(np.ptp(out)) < MIN_OUT_MOVE_PCT:
        return None
    # `np.diff(out)` is the step between consecutive samples, in percent.
    # A step counts as a deliberate move when its size exceeds MOVE_STEP_PCT.
    # `np.flatnonzero` turns the boolean mask into the indices of those moves.
    moved = np.flatnonzero(np.abs(np.diff(out)) > MOVE_STEP_PCT)
    if len(moved) == 0:
        return None
    # The diff at index i is measured between samples i and i+1, so the move at `moved[0]`
    # ends at sample `moved[0] + 1`. Each edge is padded by a lead-in or tail-out,
    # then clamped to the recorded time base so the span never leaves the data.
    start = max(float(t_s[0]), float(t_s[moved[0]]) - LEAD_S)
    end = min(float(t_s[-1]), float(t_s[moved[-1] + 1]) + TAIL_S)
    # The returned pair is (first instant, last instant) of the window, in seconds.
    return start, end
