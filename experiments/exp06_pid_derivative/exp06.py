"""exp06: does AMIGO PID derivative action beat AMIGO PI on exact FOPDT loops?

Implements the frozen protocol of experiments/exp06_pid_derivative/README.md:
the same load-step IAE, sensitivity peak Ms and noise-amplification test on a
grid of normalized dead times, comparing amigo_pi with amigo_pid, and checks
the acceptance targets P1..P3. Results are written to results/results.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from crosscut_loops.tuning_pid import (
    PidSettings,
    amigo_pid,
    derivative_advice,
    high_frequency_gain,
)
from crosscut_loops.tuning_rules import FopdtModel, PiSettings, amigo_pi
from crosscut_sim.core import Fopdt

# --- Simulation setup (units in comment) -----------------------------------
SAMPLE_TIME_S = 0.5  # controller and process sample time in seconds
TOTAL_LAG_PLUS_DELAY_S = 100.0  # so that T + L = 100 s for every grid point
DISTURBANCE_SETTLING_FACTOR = 15.0  # simulate 15 * (T + L) seconds for IAE
LOAD_STEP_MAGNITUDE = 1.0  # unit step added at the process input
PROCESS_GAIN = 1.0  # K = 1, dimensionless

# --- Frequency-response setup ----------------------------------------------
MIN_OMEGA_RAD_S = 1e-4  # rad/s, lower end of the Ms grid
MAX_OMEGA_RAD_S = 1e2  # rad/s, upper end of the Ms grid
NUM_OMEGA_POINTS = 4000  # resolution of the log-spaced Ms grid

# --- Noise test setup ------------------------------------------------------
NOISE_STD = 0.01  # standard deviation of the PV noise, in PV units
NOISE_DURATION_S = 3000.0  # length of the noise run in seconds
NOISE_SEED = 1  # seed so PI and PID see the same noise sequence

# --- Acceptance targets (frozen in the README, 2026-10-14) -----------------
P1_MAX_TAU_NORMALIZED = 0.3  # P1 applies for tau_n <= 0.3
P1_MAX_IAE_RATIO = 0.8  # P1 requires IAE(PID)/IAE(PI) <= 0.8
P2_MAX_MS = 1.8  # P2 requires Ms(PID) <= 1.8 at every grid point
P3_MIN_TAU_NORMALIZED = 0.7  # P3 applies for tau_n >= 0.7
P3_MAX_IAE_RATIO = 0.9  # P3 requires IAE(PID)/IAE(PI) >= 0.9

# --- Grid of normalized dead times -----------------------------------------
TAU_NORMALIZED_GRID = (0.1, 0.2, 0.3, 0.5, 0.7, 0.9)

RESULTS_PATH = Path(__file__).resolve().parent / "results" / "results.md"


@dataclass(frozen=True)
class GridPoint:
    """One grid point: process model, PI settings and PID settings together."""

    tau_normalized: float
    model: FopdtModel
    pi_settings: PiSettings
    pid_settings: PidSettings


@dataclass(frozen=True)
class ClosedLoopResult:
    """Outcome of one closed-loop run: disturbance IAE and noise ratio inputs."""

    iae_load_step: float
    ms_peak: float
    high_frequency_gain: float


@dataclass(frozen=True)
class NoiseResult:
    """Standard deviation of the controller-output increments under PV noise."""

    output_increment_std: float


@dataclass(frozen=True)
class Row:
    """One fully evaluated grid point, ready for the results table."""

    point: GridPoint
    advice: bool
    iae_pi: float
    iae_pid: float
    ms_pi: float
    ms_pid: float
    noise_ratio: float

    @property
    def iae_ratio(self) -> float:
        """Return IAE(PID) / IAE(PI) for the load step (dimensionless)."""
        return self.iae_pid / self.iae_pi


def build_grid_point(tau_normalized: float) -> GridPoint:
    """Build the process model and both tunings for one normalized dead time.

    The grid keeps T + L = 100 s: L = 100 tau_n and T = 100 (1 - tau_n), so the
    process changes only in shape, not in speed. K = 1.
    """
    delay_s = TOTAL_LAG_PLUS_DELAY_S * tau_normalized
    time_constant_s = TOTAL_LAG_PLUS_DELAY_S * (1.0 - tau_normalized)
    model = FopdtModel(gain=PROCESS_GAIN, time_constant_s=time_constant_s, delay_s=delay_s)
    return GridPoint(
        tau_normalized=tau_normalized,
        model=model,
        pi_settings=amigo_pi(model),
        pid_settings=amigo_pid(model),
    )


def simulate_load_step(
    model: FopdtModel, settings: PidSettings, duration_s: float
) -> float:
    """Return the IAE of a unit load step at the process input, setpoint at zero.

    Ideal PID with derivative on the filtered measurement, explicit Euler for
    P and I and backward Euler for the derivative term. The disturbance enters
    as u + d with d = 1.0 from t = 0, which pushes the output away from zero.
    """
    process = Fopdt(
        gain=model.gain,
        tau_s=model.time_constant_s,
        delay_s=model.delay_s,
        dt_s=SAMPLE_TIME_S,
    )
    estimator = _PidEstimator(settings)
    number_of_steps = int(round(duration_s / SAMPLE_TIME_S))
    integral_abs_error = 0.0
    previous_measurement = 0.0
    measurement = 0.0
    for _ in range(number_of_steps):
        control = estimator.step(measurement, previous_measurement)
        # The unit step d = 1 adds to the controller output before the process.
        measurement = process.update(control + LOAD_STEP_MAGNITUDE)
        integral_abs_error += abs(measurement) * SAMPLE_TIME_S
        previous_measurement = measurement
    return integral_abs_error


class _PidEstimator:
    """Ideal PID with filtered derivative on the measurement, Euler stepping."""

    def __init__(self, settings: PidSettings) -> None:
        """Store the settings and zero the integral and derivative states."""
        self._settings = settings
        self._integral = 0.0
        self._derivative = 0.0

    def step(self, measurement: float, previous_measurement: float) -> float:
        """Return the controller output for this step, given PV now and before."""
        settings = self._settings
        error = -measurement  # setpoint r = 0, so e = r - y = -y
        self._integral += settings.kc / settings.ti_s * error * SAMPLE_TIME_S
        self._derivative = self._filtered_derivative(measurement, previous_measurement)
        return settings.kc * error + self._integral + self._derivative

    def _filtered_derivative(self, measurement: float, previous_measurement: float) -> float:
        """Backward-Euler derivative term on -y so a PV rise reduces the output."""
        settings = self._settings
        filter_time_s = settings.filter_time_s
        numerator = filter_time_s * self._derivative - settings.kc * settings.td_s * (
            measurement - previous_measurement
        )
        return numerator / (filter_time_s + SAMPLE_TIME_S)


def simulate_noise(model: FopdtModel, settings: PidSettings) -> NoiseResult:
    """Return the std of controller-output increments under PV noise, d = 0.

    Noise is added to the measurement only; the process input stays free of it,
    which is how a real loop behaves when the sensor is noisy. The seed is
    fixed so the PI and PID runs see the same noise sequence and are comparable.
    """
    process = Fopdt(
        gain=model.gain,
        tau_s=model.time_constant_s,
        delay_s=model.delay_s,
        dt_s=SAMPLE_TIME_S,
    )
    estimator = _PidEstimator(settings)
    rng = np.random.default_rng(NOISE_SEED)
    number_of_steps = int(round(NOISE_DURATION_S / SAMPLE_TIME_S))
    noise = rng.normal(0.0, NOISE_STD, size=number_of_steps)
    outputs = np.empty(number_of_steps)
    previous_measurement = 0.0
    previous_output = 0.0
    for step in range(number_of_steps):
        measurement = process.value + noise[step]  # current state, then noisy PV
        output = estimator.step(measurement, previous_measurement)
        outputs[step] = output - previous_output
        previous_measurement = measurement
        previous_output = output
        process.update(output)  # no load disturbance in the noise run
    return NoiseResult(output_increment_std=float(np.std(np.diff(outputs))))


def peak_sensitivity(model: FopdtModel, settings: PidSettings) -> float:
    """Return Ms = max |1 / (1 + C(jw) P(jw))| over a log-frequency grid.

    The process is exact, including the delay exp(-j w L); no Pade
    approximation is used, which matters because Ms is a robustness measure and
    the Pade error would show up near the phase crossover.
    """
    omega = np.logspace(
        np.log10(MIN_OMEGA_RAD_S), np.log10(MAX_OMEGA_RAD_S), NUM_OMEGA_POINTS
    )
    j_omega = 1j * omega
    filter_time_s = settings.filter_time_s
    controller = settings.kc * (
        1.0 + 1.0 / (j_omega * settings.ti_s) + j_omega * settings.td_s
        / (1.0 + j_omega * filter_time_s)
    )
    process = (
        model.gain
        * np.exp(-j_omega * model.delay_s)
        / (1.0 + j_omega * model.time_constant_s)
    )
    return float(np.max(np.abs(1.0 / (1.0 + controller * process))))


def evaluate_grid_point(tau_normalized: float) -> Row:
    """Run every experiment for one grid point and collect the numbers."""
    point = build_grid_point(tau_normalized)
    duration_s = DISTURBANCE_SETTLING_FACTOR * (
        point.model.time_constant_s + point.model.delay_s
    )
    iae_pi = simulate_load_step(point.model, _as_pid(point.pi_settings), duration_s)
    iae_pid = simulate_load_step(point.model, point.pid_settings, duration_s)
    noise_pi = simulate_noise(point.model, _as_pid(point.pi_settings))
    noise_pid = simulate_noise(point.model, point.pid_settings)
    advice, _reason = derivative_advice(point.model)
    return Row(
        point=point,
        advice=advice,
        iae_pi=iae_pi,
        iae_pid=iae_pid,
        ms_pi=peak_sensitivity(point.model, _as_pid(point.pi_settings)),
        ms_pid=peak_sensitivity(point.model, point.pid_settings),
        noise_ratio=noise_pid.output_increment_std / noise_pi.output_increment_std,
    )


def _as_pid(settings: PiSettings) -> PidSettings:
    """Lift PI settings to ideal PID settings with the derivative switched off.

    The simulation and the frequency response use one code path for both
    controllers; td_s = 0 makes them identical to the PI rule.
    """
    return PidSettings(kc=settings.kc, ti_s=settings.ti_s, td_s=0.0)


def check_targets(rows: list[Row]) -> dict[str, tuple[bool, str]]:
    """Evaluate P1..P3 against the frozen thresholds and return pass/fail text."""
    return {
        "P1": _check_p1(rows),
        "P2": _check_p2(rows),
        "P3": _check_p3(rows),
    }


def _check_p1(rows: list[Row]) -> tuple[bool, str]:
    """P1: PID IAE <= 0.8 x PI IAE for tau_n <= 0.3 at every grid point."""
    selected = [row for row in rows if row.point.tau_normalized <= P1_MAX_TAU_NORMALIZED]
    worst = max(selected, key=lambda row: row.iae_ratio)
    passed = all(row.iae_ratio <= P1_MAX_IAE_RATIO for row in selected)
    detail = (
        f"{passed}: worst ratio {worst.iae_ratio:.3f} at tau_n "
        f"{worst.point.tau_normalized} (<= {P1_MAX_IAE_RATIO})"
    )
    return passed, detail


def _check_p2(rows: list[Row]) -> tuple[bool, str]:
    """P2: Ms of the PID <= 1.8 at every grid point."""
    worst = max(rows, key=lambda row: row.ms_pid)
    passed = all(row.ms_pid <= P2_MAX_MS for row in rows)
    detail = (
        f"{passed}: worst Ms {worst.ms_pid:.3f} at tau_n "
        f"{worst.point.tau_normalized} (<= {P2_MAX_MS})"
    )
    return passed, detail


def _check_p3(rows: list[Row]) -> tuple[bool, str]:
    """P3: for tau_n >= 0.7 advice is False and IAE ratio >= 0.9."""
    selected = [row for row in rows if row.point.tau_normalized >= P3_MIN_TAU_NORMALIZED]
    advice_ok = all(not row.advice for row in selected)
    ratio_ok = all(row.iae_ratio >= P3_MAX_IAE_RATIO for row in selected)
    passed = advice_ok and ratio_ok
    worst = max(selected, key=lambda row: row.iae_ratio)
    detail = (
        f"{passed}: advice False {advice_ok}, worst ratio {worst.iae_ratio:.3f} at tau_n "
        f"{worst.point.tau_normalized} (>= {P3_MAX_IAE_RATIO})"
    )
    return passed, detail


def _format_table(rows: list[Row]) -> list[str]:
    """Return the markdown lines of the per-grid-point results table."""
    header = (
        "| tau_n | L (s) | T (s) | advice | Kc PI | Ti PI | Td PI | Kc PID | Ti PID | "
        "Td PID | IAE PI | IAE PID | ratio | Ms PI | Ms PID | Kc(1+N) | noise ratio |"
    )
    separator = "|" + "---|" * 18
    lines = [header, separator]
    for row in rows:
        point = row.point
        lines.append(
            f"| {point.tau_normalized:.1f} "
            f"| {point.model.delay_s:.1f} | {point.model.time_constant_s:.1f} "
            f"| {row.advice} "
            f"| {point.pi_settings.kc:.4f} | {point.pi_settings.ti_s:.4f} | 0.0000 "
            f"| {point.pid_settings.kc:.4f} | {point.pid_settings.ti_s:.4f} "
            f"| {point.pid_settings.td_s:.4f} "
            f"| {row.iae_pi:.4f} | {row.iae_pid:.4f} | {row.iae_ratio:.4f} "
            f"| {row.ms_pi:.4f} | {row.ms_pid:.4f} "
            f"| {high_frequency_gain(point.pid_settings):.4f} "
            f"| {row.noise_ratio:.4f} |"
        )
    return lines


def write_results_markdown(rows: list[Row], targets: dict[str, tuple[bool, str]]) -> Path:
    """Write the results table and the target section to results/results.md."""
    lines = ["# exp06: AMIGO PID vs AMIGO PI on exact FOPDT loops", ""]
    lines.append("## Grid results")
    lines.append("")
    lines.extend(_format_table(rows))
    lines.append("")
    lines.append("## Targets")
    lines.append("")
    for name in ("P1", "P2", "P3"):
        passed, detail = targets[name]
        lines.append(f"- **{name}**: {'PASS' if passed else 'FAIL'} - {detail}")
    lines.append(
        "- **P4 (informational)**: Kc(1+N) and the noise ratio are reported per grid "
        "point in the table above; no pass/fail threshold."
    )
    lines.append("")
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text("\n".join(lines), encoding="utf-8")
    return RESULTS_PATH


def main() -> None:
    """Run the experiment over the grid, check the targets and write the report."""
    rows = [evaluate_grid_point(tau) for tau in TAU_NORMALIZED_GRID]
    targets = check_targets(rows)
    path = write_results_markdown(rows, targets)
    print(f"Results written to {path}")


if __name__ == "__main__":
    main()
