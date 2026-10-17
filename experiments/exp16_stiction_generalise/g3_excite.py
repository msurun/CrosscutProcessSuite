"""
g3_excite.py - Excitation generator for the G3 closed-loop simulation.

Creates setpoint and load disturbance signals for a single simulation record.
The signals are deterministic given the RNG and designed to exercise the plant
with periods relative to a dominant loop time scale.

The module is pure: it reads no files, writes no files, and holds no state
between calls. All randomness comes from the passed-in Generator.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Excitation:
    """Setpoint and load signals plus metadata for one record."""

    sp: np.ndarray  # percent of range, around 50
    load: np.ndarray  # percent of range, around 0
    meta: dict  # drawn parameters for audit


def make_excitation(
    rng: np.random.Generator,
    case: str,
    n: int,
    dt_s: float,
    tscale: float,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Generate setpoint and load signals for the given case.

    Args:
        rng: NumPy random generator (deterministic if seeded).
        case: One of "stick", "load_sine", "load_square", "load_multitone",
              "sp_square", "sp_steps", "tuning_aggressive", "tuning_sluggish",
              "quiet".
        n: Number of samples in the record.
        dt_s: Sampling interval in seconds.
        tscale: Dominant loop time scale in seconds.

    Returns:
        Tuple (sp, load, meta). sp is in percent around 50, load in percent
        around 0. meta contains the amplitude as a fraction under "amp".

    Raises:
        ValueError: If case is not one of the supported strings.
    """
    sp = _make_setpoint(rng, case, n, dt_s, tscale)
    load = _make_load(rng, case, n, dt_s, tscale)
    meta = _make_meta(case, load)
    return sp, load, meta


def _make_setpoint(
    rng: np.random.Generator, case: str, n: int, dt_s: float, tscale: float
) -> np.ndarray:
    """Build the setpoint array for the given case."""
    if case == "sp_square":
        return _square_wave(rng, n, dt_s, tscale, offset=50.0)
    if case == "sp_steps":
        return _random_staircase(rng, n, dt_s, tscale, offset=50.0)
    return np.full(n, 50.0)


def _make_load(
    rng: np.random.Generator, case: str, n: int, dt_s: float, tscale: float
) -> np.ndarray:
    """Build the load disturbance array for the given case."""
    if case == "load_sine":
        return _periodic_load(rng, n, dt_s, tscale, kind="sine")
    if case == "load_square":
        return _periodic_load(rng, n, dt_s, tscale, kind="square")
    if case == "load_multitone":
        return _multitone_load(rng, n, dt_s, tscale)
    if case in ("tuning_aggressive", "tuning_sluggish", "sp_square", "sp_steps"):
        return _tiny_random_walk(rng, n, std=0.2)
    if case == "quiet":
        return _tiny_random_walk(rng, n, std=0.5)
    if case == "stick":
        return _constant_with_walk(rng, n, offset_min=5.0, offset_max=15.0, std=0.1)
    raise ValueError(f"Unknown case: {case!r}")


def _make_meta(case: str, load: np.ndarray) -> dict:
    """Create metadata dict; amplitude fraction is the max absolute load."""
    amp = float(np.max(np.abs(load))) / 100.0 if len(load) else 0.0
    return {"case": case, "amp": amp}


def _square_wave(
    rng: np.random.Generator,
    n: int,
    dt_s: float,
    tscale: float,
    offset: float,
) -> np.ndarray:
    """Generate a square wave with random period and amplitude."""
    period_s = _draw_period(rng, tscale)
    amplitude = _draw_amplitude(rng)
    phase = rng.uniform(0.0, period_s)
    time = np.arange(n) * dt_s
    wave = np.where(((time + phase) % period_s) < period_s / 2.0, 1.0, -1.0)
    return offset + amplitude * wave


def _random_staircase(
    rng: np.random.Generator,
    n: int,
    dt_s: float,
    tscale: float,
    offset: float,
) -> np.ndarray:
    """Generate a random staircase of 4-12 steps."""
    n_steps = int(rng.integers(4, 13))
    step_length = n // n_steps
    levels = rng.uniform(-1.0, 1.0, size=n_steps) * _draw_amplitude(rng)
    signal = np.repeat(levels, step_length)
    if len(signal) < n:
        signal = np.concatenate([signal, np.full(n - len(signal), signal[-1])])
    return offset + signal[:n]


def _periodic_load(
    rng: np.random.Generator,
    n: int,
    dt_s: float,
    tscale: float,
    kind: str,
) -> np.ndarray:
    """Generate a sine or square load disturbance with random period/amplitude."""
    period_s = _draw_period(rng, tscale)
    amplitude = _draw_amplitude(rng)
    phase = rng.uniform(0.0, period_s)
    time = np.arange(n) * dt_s
    if kind == "sine":
        return amplitude * np.sin(2.0 * np.pi * time / period_s + phase)
    wave = np.where(((time + phase) % period_s) < period_s / 2.0, 1.0, -1.0)
    return amplitude * wave


def _multitone_load(rng: np.random.Generator, n: int, dt_s: float, tscale: float) -> np.ndarray:
    """Generate a load of 2-3 incommensurate sine tones."""
    n_tones = int(rng.integers(2, 4))
    time = np.arange(n) * dt_s
    signal = np.zeros(n)
    for _ in range(n_tones):
        period_s = _draw_period(rng, tscale)
        phase = rng.uniform(0.0, period_s)
        signal += np.sin(2.0 * np.pi * time / period_s + phase)
    amplitude = _draw_amplitude(rng)
    return amplitude * signal / np.sqrt(n_tones)


def _tiny_random_walk(rng: np.random.Generator, n: int, std: float) -> np.ndarray:
    """Generate a small random walk for quiet or tuning cases."""
    steps = rng.normal(0.0, std, size=n)
    return np.cumsum(steps)


def _constant_with_walk(
    rng: np.random.Generator,
    n: int,
    offset_min: float,
    offset_max: float,
    std: float,
) -> np.ndarray:
    """Generate a constant offset plus a tiny random walk (stiction case)."""
    offset = rng.uniform(offset_min, offset_max)
    walk = _tiny_random_walk(rng, n, std)
    return offset + walk


def _draw_period(rng: np.random.Generator, tscale: float) -> float:
    """Draw a random period between 0.5 and 10 times the dominant time scale."""
    return rng.uniform(0.5 * tscale, 10.0 * tscale)


def _draw_amplitude(rng: np.random.Generator) -> float:
    """Draw a random amplitude in percent so the PV swing is 3-20 %."""
    return rng.uniform(3.0, 20.0)


if __name__ == "__main__":
    # Self-test: simulate a few combinations and print basic diagnostics.
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
    print(f"{'case':<20} {'n':>6} {'dt_s':>6} {'amp':>8} {'sp_min':>8} {'sp_max':>8}")
    for case in cases:
        n = 3000
        dt_s = 2.0
        tscale = 50.0
        sp, load, meta = make_excitation(rng, case, n, dt_s, tscale)
        amp = meta["amp"]
        print(f"{case:<20} {n:>6} {dt_s:>6.1f} {amp:>8.4f} {np.min(sp):>8.2f} {np.max(sp):>8.2f}")
