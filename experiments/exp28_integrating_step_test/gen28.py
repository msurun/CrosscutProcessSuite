"""Generator G28: open-loop step-test records of level loops for exp28 (frozen protocol, README.md).

Good cells (integrator with dead time), valve-deadband cells and the bad kinds B1-B4; dt = 1 s,
every record is a pure function of its seed. Written without looking at identify_ipdt; it only uses
the exp26 plant class and the crosscut_sim Ornstein-Uhlenbeck process.
"""

from __future__ import annotations

import sys
from collections import deque
from dataclasses import dataclass, replace
from itertools import product
from pathlib import Path

import numpy as np
from crosscut_sim.disturbances import OrnsteinUhlenbeck, OuShape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exp26_history_tuning_level"))
from g26_level import IntegratorWithDelay  # noqa: E402

DT_S = 1.0  # sample time, s
OUT_BIAS = 50.0  # OUT at which the integrator is at rest, %
PV_START = 50.0  # initial PV, %
OUT_LIMITS = (0.0, 100.0)  # OUT range, %
LEAD_S = 120.0  # shortest time before the first move, s
LEAD_REST_DIVISOR = 3.0  # amendment 1: lead = max(120 s, rest / 3) >= 25 % of the record
RATES = (0.002, 0.01, 0.05)  # k, %PV per %OUT per s
DELAYS = (5.0, 30.0)  # theta, s
PATTERNS = ("single", "doublet", "train")
NOISES = (0.05, 0.2)  # measurement noise std, % PV
LOADS = (0.0, 0.5)  # OU load std, % OUT
STEP_SIZES = (4.0, 8.0)  # s, % OUT (drawn per record: not a cell dimension)
DEADBAND = 0.5  # actuator deadband of the valve cells, % OUT (total width)
LOAD_TAU_S = 200.0  # OU time constant, s
PV_TRAVEL = 10.0  # intended PV travel of one step, % PV: d = round(PV_TRAVEL / (k s))
STEP_DURATION_LIMITS = (60.0, 900.0)  # clip of d, s
MIN_TAIL_S = 300.0  # tail after the last move is at least max(TAIL_DELAY_FACTOR theta, 300) s
TAIL_DELAY_FACTOR = 5.0
# Levels (multiples of s, relative to OUT_BIAS) after each move of a pattern.
_LEVELS = {"single": (1.0,), "doublet": (1.0, 0.0), "train": (1.0, -1.0, 1.0, 0.0)}
FOPDT_GAIN = 1.0  # B1/B2 static gain, %PV per %OUT
FOPDT_DELAY_S = 10.0
FOPDT_TAUS = {"B1": 60.0, "B2": 200.0}  # time constant per bad kind, s
BAD_WINDOW_S = 1200.0  # window of B1, B2 and B4, s
BAD_KINDS = ("B1", "B2", "B3", "B4")
B3_TAIL_FRACTION = (0.2, 0.9)  # B3 tail drawn as this fraction of the required minimum
B4_LOAD_STD = 0.5  # OU load of B4, % OUT


@dataclass(frozen=True)
class Cell:
    """One good (deadband 0) or valve (deadband > 0) cell of the grid."""

    rate: float  # k, %PV per %OUT per s
    delay_s: float  # theta, s
    pattern: str
    noise_std: float  # % PV
    load_std: float  # % OUT
    deadband: float = 0.0  # actuator deadband, % OUT

    @property
    def name(self) -> str:
        """Short unique label of the cell."""
        valve = f"_db{self.deadband:g}" if self.deadband else ""
        return (f"k{self.rate:g}_th{self.delay_s:g}_{self.pattern}"
                f"_N{self.noise_std:g}_L{self.load_std:g}{valve}")


@dataclass(frozen=True)
class Record:
    """One step-test record plus the truth needed to judge it."""

    t_s: np.ndarray
    out: np.ndarray  # controller output as recorded, %
    pv: np.ndarray  # measured PV, %
    kind: str  # "good", "valve", "B1".."B4"
    plant: dict  # true plant: {"type": "ipdt"|"fopdt", ...}
    meta: dict  # step size, step duration, last move time, cell name


def good_cells() -> list[Cell]:
    """The 72 good cells in protocol order: k, theta, pattern, noise, load."""
    return [Cell(*c) for c in product(RATES, DELAYS, PATTERNS, NOISES, LOADS)]


def valve_cells() -> list[Cell]:
    """The 72 valve cells: the good cells with the actuator deadband."""
    return [replace(cell, deadband=DEADBAND) for cell in good_cells()]


def step_duration_s(slope: float, step: float) -> float:
    """d = round(PV_TRAVEL / (k s)) clipped to STEP_DURATION_LIMITS, s."""
    return float(np.clip(round(PV_TRAVEL / (slope * step)), *STEP_DURATION_LIMITS))


def required_tail_s(delay_s: float) -> float:
    """Minimum time after the last move: max(5 theta, 300) s."""
    return max(TAIL_DELAY_FACTOR * delay_s, MIN_TAIL_S)


def lead_s(pattern: str, duration_s: float, tail_s: float) -> float:
    """Amendment 1: max(120 s, rest / 3), rest = pattern duration + tail, whole seconds."""
    rest = duration_s * (len(_LEVELS[pattern]) - 1) + tail_s
    return float(max(LEAD_S, np.ceil(rest / LEAD_REST_DIVISOR / DT_S) * DT_S))


def out_signal(pattern: str, step: float, duration_s: float, tail_s: float) -> np.ndarray:
    """OUT (%) of the step test: lead, the pattern moves every duration_s, then tail_s."""
    levels = _LEVELS[pattern]
    move_times = lead_s(pattern, duration_s, tail_s) + duration_s * np.arange(len(levels))
    n = int(round((move_times[-1] + tail_s) / DT_S)) + 1  # t[-1] - last move = tail_s
    t = np.arange(n) * DT_S
    out = np.full(n, OUT_BIAS)
    for t_move, level in zip(move_times, levels, strict=True):
        out[t >= t_move] = OUT_BIAS + level * step
    return np.clip(out, *OUT_LIMITS)


def valve_step(position: float, out: float, band: float) -> float:
    """One sample of a backlash valve: it moves only once OUT leaves a band of total width band."""
    half = 0.5 * band
    if out > position + half:
        return out - half
    return out + half if out < position - half else position


def deadband_actuator(out: np.ndarray, band: float) -> np.ndarray:
    """Valve position (%) over a record, starting at rest at OUT_BIAS."""
    position = np.empty_like(out)
    pos = OUT_BIAS
    for i, value in enumerate(out):
        pos = valve_step(pos, value, band)
        position[i] = pos
    return position


def load_and_noise(load_std: float, noise_std: float, n: int,
                   rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """OU load d (% OUT, tau 200 s, starts at 0) and white measurement noise (% PV)."""
    ou = OrnsteinUhlenbeck(OuShape(0.0, load_std, LOAD_TAU_S), DT_S, rng)
    load = np.array([ou.update() for _ in range(n)])
    return load, noise_std * rng.standard_normal(n)


class FopdtWithDelay:
    """First order plus dead time, exact zero-order-hold step: x+ = a x + (1 - a) K u(t - theta)."""

    def __init__(self, gain: float, tau_s: float, delay_s: float) -> None:
        """Plant at rest (deviation 0) with an empty delay line."""
        self.gain = gain
        self.alpha = float(np.exp(-DT_S / tau_s))
        self.state = 0.0  # PV deviation, %
        self._line = deque([0.0] * round(delay_s / DT_S))

    def update(self, u: float) -> float:
        """Advance one sample with input u (% OUT deviation); return the PV deviation (%)."""
        self._line.append(u)
        u_delayed = self._line.popleft()
        self.state = self.alpha * self.state + (1.0 - self.alpha) * self.gain * u_delayed
        return self.state


def make_plant(plant: dict) -> IntegratorWithDelay | FopdtWithDelay:
    """A fresh plant at rest from its description {"type", rate|gain+tau_s, delay_s}."""
    if plant["type"] == "ipdt":
        return IntegratorWithDelay(plant["rate"], plant["delay_s"], DT_S)
    return FopdtWithDelay(plant["gain"], plant["tau_s"], plant["delay_s"])


def open_loop_pv(plant: dict, actuator: np.ndarray, load: np.ndarray,
                 noise: np.ndarray) -> np.ndarray:
    """Measured PV (%) of the plant in MAN: PV[k] uses the input up to sample k - 1."""
    model = make_plant(plant)
    pv = np.empty(len(actuator))
    deviation = 0.0
    for i in range(len(actuator)):
        pv[i] = PV_START + deviation + noise[i]
        deviation = model.update(actuator[i] - OUT_BIAS + load[i])
    return pv


def _record(out: np.ndarray, plant: dict, band: float, disturbances: tuple) -> np.ndarray:
    """PV of a record: OUT through the valve (deadband ``band``) into the plant with load, noise."""
    load, noise = disturbances
    return open_loop_pv(plant, deadband_actuator(out, band), load, noise)


def cell_record(cell: Cell, seed: int) -> Record:
    """Step-test record of a good or valve cell; the step size is drawn from the seed."""
    rng = np.random.default_rng(seed)
    step = float(rng.choice(STEP_SIZES))
    duration = step_duration_s(cell.rate, step)
    tail = required_tail_s(cell.delay_s)
    out = out_signal(cell.pattern, step, duration, tail)
    plant = {"type": "ipdt", "rate": cell.rate, "delay_s": cell.delay_s}
    disturbances = load_and_noise(cell.load_std, cell.noise_std, len(out), rng)
    pv = _record(out, plant, cell.deadband, disturbances)
    last_move = float(len(out) - 1) * DT_S - tail
    meta = {"cell": cell.name, "step": step, "step_duration_s": duration, "last_move_s": last_move}
    kind = "valve" if cell.deadband else "good"
    return Record(np.arange(len(out)) * DT_S, out, pv, kind, plant, meta)


def _fopdt_record(kind: str, seed: int) -> Record:
    """B1/B2: FOPDT (K 1, theta 10 s) over 1200 s; even seed single, odd seed doublet."""
    rng = np.random.default_rng(seed)
    tau = FOPDT_TAUS[kind]
    step = float(rng.choice(STEP_SIZES))
    noise_std, load_std = float(rng.choice(NOISES)), float(rng.choice(LOADS))
    pattern = ("single", "doublet")[seed % 2]
    duration = step_duration_s(FOPDT_GAIN / tau, step)  # initial slope K / tau stands in for k
    # Window 1200 s with lead = rest / 3 (amendment 1): lead 300 s, rest 900 s.
    rest = BAD_WINDOW_S * LEAD_REST_DIVISOR / (LEAD_REST_DIVISOR + 1.0)
    tail = rest - duration * (pattern != "single")
    out = out_signal(pattern, step, duration, tail)
    plant = {"type": "fopdt", "gain": FOPDT_GAIN, "tau_s": tau, "delay_s": FOPDT_DELAY_S}
    pv = _record(out, plant, 0.0, load_and_noise(load_std, noise_std, len(out), rng))
    meta = {"cell": f"{kind}_{pattern}_N{noise_std:g}_L{load_std:g}", "step": step,
            "step_duration_s": duration, "pattern": pattern}
    return Record(np.arange(len(out)) * DT_S, out, pv, kind, plant, meta)


def _truncated_record(seed: int) -> Record:
    """B3: a good-cell record cut so that the time after the last move is below the minimum."""
    rng = np.random.default_rng(seed)
    cells = good_cells()
    cell = cells[int(rng.integers(len(cells)))]
    full = cell_record(cell, int(rng.integers(2**31)))
    tail = np.floor(rng.uniform(*B3_TAIL_FRACTION) * required_tail_s(cell.delay_s))
    keep = full.t_s <= full.meta["last_move_s"] + tail
    meta = {**full.meta, "cell": f"B3_{cell.name}", "tail_s": float(tail)}
    return Record(full.t_s[keep], full.out[keep], full.pv[keep], "B3", full.plant, meta)


def _no_move_record(seed: int) -> Record:
    """B4: OUT held at 50 % for 1200 s, OU load 0.5 % OUT only, plant drawn from the grid."""
    rng = np.random.default_rng(seed)
    rate, delay = float(rng.choice(RATES)), float(rng.choice(DELAYS))
    noise_std = float(rng.choice(NOISES))
    out = np.full(int(BAD_WINDOW_S / DT_S) + 1, OUT_BIAS)
    plant = {"type": "ipdt", "rate": rate, "delay_s": delay}
    pv = _record(out, plant, 0.0, load_and_noise(B4_LOAD_STD, noise_std, len(out), rng))
    meta = {"cell": f"B4_k{rate:g}_th{delay:g}_N{noise_std:g}"}
    return Record(np.arange(len(out)) * DT_S, out, pv, "B4", plant, meta)


def bad_record(kind: str, seed: int) -> Record:
    """Record of bad kind B1..B4 for one seed."""
    if kind in FOPDT_TAUS:
        return _fopdt_record(kind, seed)
    return _truncated_record(seed) if kind == "B3" else _no_move_record(seed)
