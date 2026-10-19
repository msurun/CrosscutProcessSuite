"""Build the blind-review pack: 20 simulated loops, CSVs, review sheet and answer key.

Run ``python experiments/review_pack/make_pack.py``. Everything lands in ``out/`` next to this
file. ``answer_key.csv`` holds the author's injected truth and must NOT go to the reviewer.
Simulation: dt = 10 s, 6 h (2160 samples), seed = loop number, plant = Fopdt (or an
integrator for level loops) behind a StictionValve, PI control with the crosscut_sim PID.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from crosscut_sim.core import AUTO, MAN, Fopdt
from crosscut_sim.disturbances import OrnsteinUhlenbeck, OuShape
from crosscut_sim.pid import PID, OutputLimits, PidTuning
from crosscut_sim.valve import StictionSpec, StictionValve
from pack_catalog import KINDS, LoopSpec, build_catalog, tag_name
from pack_sheet import write_instructions, write_review_sheet

DT_S = 10.0
N_SAMPLES = 2160
OP0 = 50.0  # operating point of the valve, in %
OUT_DIR = Path(__file__).resolve().parent / "out"


@dataclass
class LoopData:
    """Simulated record of one loop (arrays of length ``N_SAMPLES``)."""

    tag: str
    spec: LoopSpec
    t_s: np.ndarray
    sp: np.ndarray
    pv: np.ndarray
    op: np.ndarray
    mode: np.ndarray


class LoopSimulator:
    """Closed loop of one spec: disturbances, plant, valve, sensor and PID, step by step."""

    def __init__(self, spec: LoopSpec, seed: int) -> None:
        """Set up all parts with ``seed`` as random seed."""
        self.spec = spec
        self.info = KINDS[spec.kind]
        self.noise_rng = np.random.default_rng(seed + 1000)
        shape = OuShape(spec.ou_mean, spec.ou_sigma, spec.ou_tau_s)
        self.ou = OrnsteinUhlenbeck(shape, DT_S, np.random.default_rng(seed))
        lag_gain = 1.0 if spec.integrating else spec.gain
        self.lag = Fopdt(lag_gain, spec.tau_s, spec.delay_s, DT_S)
        self.valve = StictionValve(StictionSpec(spec.deadband, spec.jump), OP0)
        self.pid = PID(PidTuning(spec.kc, spec.ti_s), DT_S, OutputLimits(0.0, 100.0))
        self.level = 0.0
        self.op = OP0
        self.man_out = OP0
        self.last_pv = self.info.pv0
        self.pid.update(self.info.pv0, self.info.pv0, "MAN", OP0)  # bumpless start

    def _load(self, k: int) -> float:
        """Load disturbance in % of valve opening: OU noise, steps and periodic part."""
        spec = self.spec
        hour = k * DT_S / 3600.0
        load = self.ou.update() + sum(d for h, d in spec.load_steps if hour >= h)
        if spec.period_s > 0:
            angle = 2 * math.pi * k * DT_S / spec.period_s + spec.period_phase
            load += spec.period_amp * math.sin(angle)
        return load

    def _process(self, u_pct: float) -> float:
        """True process value after one step with the valve input ``u_pct`` (deviation)."""
        y = self.lag.update(u_pct)
        if self.spec.integrating:
            self.level += self.spec.gain * y * DT_S
            y = self.level
        return self.info.pv0 + y

    def _measure(self, k: int, pv_true: float) -> float:
        """Sensor reading: noise, plus a frozen segment when the spec asks for one."""
        pv = pv_true + self.spec.noise * self.noise_rng.standard_normal()
        frozen = self.spec.frozen
        if frozen and frozen[0] * N_SAMPLES <= k < frozen[1] * N_SAMPLES:
            return self.last_pv
        self.last_pv = pv
        return pv

    def _setpoint(self, k: int) -> float:
        """Setpoint: the operating point plus the operator's step changes so far."""
        hour = k * DT_S / 3600.0
        return self.info.pv0 + sum(d for h, d in self.spec.sp_steps if hour >= h)

    def _control(self, k: int, pv: float, sp: float) -> tuple[float, int]:
        """PID output (quantised if asked) and the mode code for sample ``k``."""
        manual = k >= self.spec.auto_fraction * N_SAMPLES
        if manual and k == int(self.spec.auto_fraction * N_SAMPLES):
            self.man_out = self.op
        if manual and k == int(0.6 * N_SAMPLES):
            self.man_out = self.op + 4.0  # the operator nudges the output once
        out = self.pid.update(pv, sp, "MAN" if manual else "AUTO", self.man_out)
        if self.spec.quant > 0:
            out = round(out / self.spec.quant) * self.spec.quant
        return out, MAN if manual else AUTO

    def run(self, tag: str) -> LoopData:
        """Simulate the whole record and return it."""
        cols = np.zeros((4, N_SAMPLES))
        mode = np.zeros(N_SAMPLES)
        for k in range(N_SAMPLES):
            pos = self.valve.move(self.op)
            pv_true = self._process(pos - OP0 + self._load(k))
            pv, sp = self._measure(k, pv_true), self._setpoint(k)
            self.op, mode[k] = self._control(k, pv, sp)
            cols[:, k] = (k * DT_S, sp, pv, self.op)
        return LoopData(tag, self.spec, cols[0], cols[1], cols[2], cols[3], mode)


def simulate_all() -> list[LoopData]:
    """Simulate the 20 loops; loop number n uses seed n."""
    loops = []
    for number, spec in enumerate(build_catalog(), start=1):
        tag = tag_name(number, spec)
        loops.append(LoopSimulator(spec, seed=number).run(tag))
    return loops


def write_loop_csv(loop: LoopData, out_dir: Path) -> None:
    """Write ``<TAG>.csv`` with columns t_s, sp, pv, op, mode."""
    with open(out_dir / f"{loop.tag}.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["t_s", "sp", "pv", "op", "mode"])
        for k in range(N_SAMPLES):
            writer.writerow(
                [
                    f"{loop.t_s[k]:.0f}",
                    f"{loop.sp[k]:.4f}",
                    f"{loop.pv[k]:.4f}",
                    f"{loop.op[k]:.3f}",
                    int(loop.mode[k]),
                ]
            )


def write_meta_and_key(loops: list[LoopData], out_dir: Path) -> None:
    """Write ``loops_meta.csv`` (units, ranges) and the secret ``answer_key.csv``."""
    with open(out_dir / "loops_meta.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["tag", "unit", "eng_min", "eng_max", "process_kind"])
        for lp in loops:
            info = KINDS[lp.spec.kind]
            kind = "integrating" if lp.spec.integrating else "self_regulating"
            writer.writerow([lp.tag, info.unit, info.eng_min, info.eng_max, kind])
    ordered = sorted(loops, key=lambda lp: lp.spec.author_rank)
    with open(out_dir / "answer_key.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["tag", "injected_cause", "expected_category", "expected_action", "author_rank"]
        )
        for lp in ordered:
            s = lp.spec
            writer.writerow([lp.tag, s.cause, s.category, s.action, s.author_rank])


def main() -> None:
    """Simulate everything and write the whole pack to ``out/``."""
    OUT_DIR.mkdir(exist_ok=True)
    loops = simulate_all()
    for loop in loops:
        write_loop_csv(loop, OUT_DIR)
    write_meta_and_key(loops, OUT_DIR)
    write_review_sheet(loops, OUT_DIR / "review_sheet.html")
    write_instructions(loops, OUT_DIR)
    print(f"Wrote {len(loops)} loops to {OUT_DIR}")


if __name__ == "__main__":
    main()
