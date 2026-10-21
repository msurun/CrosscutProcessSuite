"""exp27: does the advisory supervisor (fuzzy v2) beat a crisp rule base in a closed loop?

Harness of the FROZEN protocol in README.md. Per seed the simulated mill circuit runs in three arms
(a: built-in operator; b: crisp advice; c: fuzzy v2 advice, b and c followed by a simulated
operator); arm c is replayed with injected mill_feed faults (E1) and arm a's moves are checked for
silence (E5).
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
from crosscut_fuzzy.model import FuzzySystem, system_from_dict
from crosscut_loops.overview import LoopTags
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import build_scenario
from crosscut_supervisor.advise import Advice
from crosscut_supervisor.config import SupervisorConfig, check_against_system, load_config
from crosscut_supervisor.gates import GateResult
from crosscut_supervisor.replay import ReplayData, ReplaySettings, advise_at, advise_series

HERE = Path(__file__).resolve().parent
V2_PATH = HERE.parents[1] / "fuzzy" / "examples" / "mill_feed_supervisor_v2.json"
BASELINE_PATH = HERE / "baseline_rulebase.json"
CONFIG_PATH = HERE / "supervisor_config.json"
SEED_SETS = {"dev": tuple(range(27001, 27011)), "test": tuple(range(27101, 27121))}

SAMPLE_S = 10.0  # record grid (s)
WINDOW_S = 1800.0  # supervisor look-back = operator period t_k = k * 1800 s
DELAY_S = 300.0  # D: an accepted advice is applied at t_k + D
ACCEPT_P = 0.8  # p: probability that the simulated operator follows a non-hold advice
P80_TARGET, P80_BAND = 150.0, 5.0  # onT: |P80 - 150| <= 5 um
POWER_HIGH = 3300.0  # high: mill power > 3300 kW
MOVE_MIN = 2.0  # E5: arm a moves with |delta SP| > 2 t/h

FEED = "sim.mc.mill_feed"
FEED_SP, FEED_OUT, FEED_MODE = FEED + "_sp", FEED + "_out", FEED + "_mode"
POWER, P80 = "sim.mc.mill_power", "sim.mc.p80"
RECORD_TAGS = (FEED, FEED_SP, FEED_OUT, FEED_MODE, POWER, P80)
MAN = 0.0  # mode code of manual in the simulator (0=MAN, 1=AUTO, 2=CAS)
# Per-loop knowledge of the mill_feed loop, the same values as supervisor/tests/test_replay.py.
# Without delay_s and ultimate_period_s module 1 rates the loop 'not_assessed' and the frozen gate
# (block_on 'unknown') would block every window, so the project-file knowledge must be given.
LOOP = LoopTags(
    name="mill_feed", pv=FEED, sp=FEED_SP, out=FEED_OUT, mode=FEED_MODE, unit="t/h",
    eng_min=0.0, eng_max=300.0, delay_s=30.0, ultimate_period_s=600.0,
    out_low=0.0, out_high=100.0,
)

E2_MAX_RATE = 4.0  # non-hold advices per hour (median over seeds)
E3_MARGIN, E3_SHARE = 0.05, 14 / 20  # onT(c) >= onT(b) + 0.05 on >= 14 of 20 seeds
E4_MAX = 0.01  # median of high(c) - high(b)
E5_MAX = 0.30  # median silent share


@dataclass(frozen=True)
class Plan:
    """Run length, start-up skip and the injected fault window (all in seconds)."""

    duration_s: float = 48 * 3600.0
    skip_s: float = 8 * 3600.0  # metrics over the last 40 h
    fault_start_s: float = 20 * 3600.0
    fault_len_s: float = 3600.0


@dataclass(frozen=True)
class Supervisor:
    """One rule base with the shared supervisor configuration."""

    system: FuzzySystem
    config: SupervisorConfig


@dataclass
class Record:
    """Preallocated recording on the 10 s grid; ``n`` samples are filled."""

    t_s: np.ndarray
    columns: dict[str, np.ndarray]
    n: int = 0

    @classmethod
    def empty(cls, size: int) -> Record:
        """A record with room for ``size`` samples of every recorded tag."""
        return cls(np.zeros(size), {tag: np.zeros(size) for tag in RECORD_TAGS})

    def append(self, t_s: float, plant: MillCircuitPlant) -> None:
        """Store the current value of every recorded tag at time ``t_s``."""
        self.t_s[self.n] = t_s
        for tag, column in self.columns.items():
            column[self.n] = plant.read(tag)[0]
        self.n += 1

    def data(self) -> ReplayData:
        """The filled part as supervisor replay data (views, no copy)."""
        return ReplayData(self.t_s[: self.n], {k: v[: self.n] for k, v in self.columns.items()})


@dataclass
class AdviceOperator:
    """Simulated operator of arms b/c: follows a non-hold advice with the pre-drawn acceptance."""

    supervisor: Supervisor
    accept: np.ndarray  # accept[k - 1] for the instant t_k = k * WINDOW_S
    sp_limits: tuple[float, float]
    pending: list[tuple[float, float]] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)

    def on_sample(self, t_s: float, record: Record) -> None:
        """At an operator instant ask the supervisor and maybe schedule a feed SP step."""
        k = int(round(t_s / WINDOW_S))
        if t_s <= 0 or abs(t_s - k * WINDOW_S) > 1e-6:
            return
        sup = self.supervisor
        advice, gate = advise_at(sup.system, sup.config, (record.data(), [LOOP]), (t_s, WINDOW_S))
        accepted = bool(self.accept[k - 1])
        delta = _signed_change(advice)
        if delta is not None and accepted:
            self.pending.append((t_s + DELAY_S, delta))
        self.log.append(_instant_entry(t_s, gate, delta, accepted))

    def apply_due(self, t_s: float, plant: MillCircuitPlant) -> None:
        """Write every scheduled SP step that is due, clipped to the engineering range."""
        while self.pending and self.pending[0][0] <= t_s + 1e-6:
            _, delta = self.pending.pop(0)
            target = plant.read(FEED_SP)[0] + delta
            plant.write(FEED_SP, float(np.clip(target, *self.sp_limits)))


def _signed_change(advice: Advice | None) -> float | None:
    """Signed feed change of a non-hold advice; None for silence or hold."""
    if advice is None or advice.direction == "hold" or advice.magnitude is None:
        return None
    return advice.magnitude if advice.direction == "increase" else -advice.magnitude


def _instant_entry(
    t_s: float, gate: GateResult, delta: float | None, accepted: bool
) -> dict[str, Any]:
    """One operator-instant log entry (JSON-ready)."""
    return {"t_s": t_s, "gate": gate.state, "reasons": list(gate.reasons), "advice": delta,
            "accepted": accepted, "applied": delta is not None and accepted}


def load_supervisors() -> dict[str, Supervisor]:
    """Arm b (crisp baseline) and arm c (fuzzy v2) with the shared, checked configuration."""
    config = load_config(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    result = {}
    for arm, path in (("b", BASELINE_PATH), ("c", V2_PATH)):
        system = system_from_dict(json.loads(path.read_text(encoding="utf-8")))
        check_against_system(config, system)
        result[arm] = Supervisor(system, config)
    return result


def make_plant(seed: int, plan: Plan, builtin_operator: bool) -> MillCircuitPlant:
    """Plant reset with the 'observational' scenario; the operator parameter off for arms b/c."""
    scenario = build_scenario("mill_circuit", "observational", duration_s=plan.duration_s)
    if not builtin_operator:  # Scenario.param: the first match wins
        scenario = replace(scenario, params=(("operator", 0.0),) + scenario.params)
    plant = MillCircuitPlant()
    plant.reset(seed, scenario)
    return plant


def simulate(seed: int, plan: Plan, operator: AdviceOperator | None) -> Record:
    """Run one arm and record the loop and supervisor tags every SAMPLE_S seconds."""
    plant = make_plant(seed, plan, builtin_operator=operator is None)
    dt = plant.dt_s
    n_steps, stride = int(round(plan.duration_s / dt)), int(round(SAMPLE_S / dt))
    record = Record.empty(n_steps // stride + 1)
    for step in range(n_steps):
        t_s = step * dt
        if operator is not None:
            operator.apply_due(t_s, plant)
        if step % stride == 0:
            record.append(t_s, plant)
            if operator is not None:
                operator.on_sample(t_s, record)
        plant.step()
    return record


def sp_limits() -> tuple[float, float]:
    """Engineering range of the feed setpoint tag (the operator's write limits)."""
    spec = MillCircuitPlant().tags[FEED_SP]
    if spec.eng_min is None or spec.eng_max is None:
        raise ValueError(f"{FEED_SP} has no engineering range")
    return float(spec.eng_min), float(spec.eng_max)


def acceptance_draws(seed: int, plan: Plan) -> np.ndarray:
    """One draw per operator instant from ONE generator of the seed; shared by arms b and c."""
    rng = np.random.default_rng(seed)
    return rng.random(int(plan.duration_s // WINDOW_S)) < ACCEPT_P


def plant_metrics(record: Record, plan: Plan) -> dict[str, float]:
    """onT and high shares over the samples after the start-up skip."""
    keep = record.data().t_s >= plan.skip_s
    p80 = record.columns[P80][: record.n][keep]
    power = record.columns[POWER][: record.n][keep]
    return {
        "onT": float(np.mean(np.abs(p80 - P80_TARGET) <= P80_BAND)),
        "high": float(np.mean(power > POWER_HIGH)),
    }


def advice_metrics(log: list[dict[str, Any]], plan: Plan) -> dict[str, Any]:
    """Advice rate (non-hold per hour), min spacing and gate-open share after the skip."""
    tail = [entry for entry in log if entry["t_s"] >= plan.skip_s]
    times = [entry["t_s"] for entry in tail if entry["advice"] is not None]
    hours = (plan.duration_s - plan.skip_s) / 3600.0
    return {
        "advice_rate": len(times) / hours,
        "min_spacing_s": float(np.min(np.diff(times))) if len(times) > 1 else None,
        "gate_open_share": _share(sum(e["gate"] == "open" for e in tail), len(tail)),
        "applied": sum(entry["applied"] for entry in tail),
    }


def _share(count: int, total: int) -> float:
    """count / total, NaN when total is zero."""
    return count / total if total else math.nan


def inject_fault(data: ReplayData, kind: str, plan: Plan) -> tuple[ReplayData, np.ndarray]:
    """Copy of ``data`` with a 'manual' or 'frozen' (PV and OUT held) mill_feed fault."""
    columns = {tag: column.copy() for tag, column in data.columns.items()}
    end = plan.fault_start_s + plan.fault_len_s
    mask = (data.t_s >= plan.fault_start_s) & (data.t_s < end)
    if kind == "manual":
        columns[FEED_MODE][mask] = MAN
    else:
        for tag in (FEED, FEED_OUT):
            columns[tag][mask] = columns[tag][mask][0]
    return ReplayData(data.t_s, columns), mask


def _fully_faulted(t_end: float, data: ReplayData, mask: np.ndarray) -> bool:
    """True when every sample of the window (t_end - WINDOW_S, t_end] is inside the fault."""
    window = (data.t_s > t_end - WINDOW_S) & (data.t_s <= t_end)
    return bool(window.any() and mask[window].all())


def _overlaps(t_end: float, data: ReplayData, mask: np.ndarray) -> bool:
    """True when at least one sample of the window (t_end - WINDOW_S, t_end] is faulted."""
    window = (data.t_s > t_end - WINDOW_S) & (data.t_s <= t_end)
    return bool(mask[window].any())


EXPECTED_REASON = {"manual": "manual:mill_feed", "frozen": "flatline:mill_feed"}


def fault_replay(sup: Supervisor, data: ReplayData, kind: str, plan: Plan) -> dict[str, Any]:
    """E1 for one fault: non-hold advices inside the fault and whether blocks name the fault."""
    patched, mask = inject_fault(data, kind, plan)
    advices = advise_series(sup.system, sup.config, patched, [LOOP], ReplaySettings(WINDOW_S))
    inside = [a for a in advices if _fully_faulted(a.t_ns / 1e9, patched, mask)]
    touching = [a for a in advices if _overlaps(a.t_ns / 1e9, patched, mask)]
    reasons = {r for a in touching if a.gate.state == "blocked" for r in a.gate.reasons}
    non_hold = [a for a in advices if a.direction != "hold"]
    return {
        "inside_non_hold": sum(a.direction != "hold" for a in inside),
        "named": EXPECTED_REASON[kind] in reasons,
        "blocked_reasons": sorted(reasons),
        "replay_rate": len(non_hold) / (plan.duration_s / 3600.0),
        "replay_min_spacing_s": _min_spacing([a.t_ns / 1e9 for a in non_hold]),
    }


def _min_spacing(times: list[float]) -> float | None:
    """Smallest gap between consecutive times, None for fewer than two."""
    return float(np.min(np.diff(times))) if len(times) > 1 else None


def silent_share(sup: Supervisor, record: Record, plan: Plan) -> dict[str, Any]:
    """E5: share of arm a feed moves (> MOVE_MIN, after the skip) with no advice from v2."""
    data = record.data()
    sp = data.columns[FEED_SP]
    jumps = np.flatnonzero(np.abs(np.diff(sp)) > MOVE_MIN)
    moves = [int(i) for i in jumps if data.t_s[i] >= plan.skip_s]
    silent = 0
    for i in moves:  # window ends on the last sample before the move
        window = (float(data.t_s[i]), WINDOW_S)
        advice, _ = advise_at(sup.system, sup.config, (data, [LOOP]), window)
        silent += _signed_change(advice) is None
    return {"moves": len(moves), "silent": silent, "silent_share": _share(silent, len(moves))}


def run_seed(seed: int, plan: Plan, sups: dict[str, Supervisor]) -> dict[str, Any]:
    """All arms, the two fault replays and E5 for one seed (deterministic per seed)."""
    draws, limits = acceptance_draws(seed, plan), sp_limits()
    record_a = simulate(seed, plan, None)
    result: dict[str, Any] = {"seed": seed, "arms": {"a": plant_metrics(record_a, plan)}}
    records = {}
    for arm in ("b", "c"):
        operator = AdviceOperator(sups[arm], draws, limits)
        records[arm] = simulate(seed, plan, operator)
        result["arms"][arm] = plant_metrics(records[arm], plan) | advice_metrics(operator.log, plan)
        result[f"log_{arm}"] = operator.log
    data_c = records["c"].data()
    result["e1"] = {kind: fault_replay(sups["c"], data_c, kind, plan) for kind in EXPECTED_REASON}
    result["e5"] = silent_share(sups["c"], record_a, plan)
    return result


def _median(values: list[float]) -> float:
    """Median ignoring NaN; NaN when nothing is left."""
    finite = [v for v in values if v is not None and not math.isnan(v)]
    return float(np.median(finite)) if finite else math.nan


def criteria(rows: list[dict[str, Any]], min_interval_s: float) -> dict[str, dict[str, Any]]:
    """E1..E5 values and pass/fail over the seeds of ``rows`` (frozen thresholds)."""
    arms = [row["arms"] for row in rows]
    e1 = [fault for row in rows for fault in row["e1"].values()]
    rate = _median([a["c"]["advice_rate"] for a in arms])
    gaps = [a["c"]["min_spacing_s"] for a in arms] + [f["replay_min_spacing_s"] for f in e1]
    wins = sum(a["c"]["onT"] >= a["b"]["onT"] + E3_MARGIN for a in arms)
    e4 = _median([a["c"]["high"] - a["b"]["high"] for a in arms])
    e5 = _median([row["e5"]["silent_share"] for row in rows])
    inside = sum(f["inside_non_hold"] for f in e1)
    spaced = all(g is None or g >= min_interval_s for g in gaps)
    return {
        "E1": {"value": f"{inside} inside, named {sum(f['named'] for f in e1)}/{len(e1)}",
               "pass": inside == 0 and all(f["named"] for f in e1)},
        "E2": {"value": f"median rate {rate:.2f}/h, spacing ok {spaced}",
               "pass": rate <= E2_MAX_RATE and spaced},
        "E3": {"value": f"{wins}/{len(rows)} seeds", "pass": wins >= E3_SHARE * len(rows)},
        "E4": {"value": f"{e4:+.4f}", "pass": e4 <= E4_MAX},
        "E5": {"value": f"{e5:.3f}", "pass": e5 <= E5_MAX},
    }


def seed_line(row: dict[str, Any]) -> str:
    """One markdown table row of per-seed results."""
    a, e1 = row["arms"], row["e1"]
    cells = [str(row["seed"])]
    cells += [f"{a[arm]['onT']:.3f}" for arm in "abc"] + [f"{a[arm]['high']:.3f}" for arm in "abc"]
    cells += [f"{a['c']['advice_rate']:.2f}", f"{a['c']['gate_open_share']:.2f}"]
    cells += [f"{row['e5']['silent']}/{row['e5']['moves']}"]
    cells += [f"{e1[k]['inside_non_hold']}/{'y' if e1[k]['named'] else 'n'}" for k in e1]
    return "| " + " | ".join(cells) + " |"


def report(name: str, rows: list[dict[str, Any]], verdict: dict[str, dict[str, Any]]) -> str:
    """Markdown report: per-seed table, criteria table and the gate-open median."""
    head = ("| seed | onT a | onT b | onT c | high a | high b | high c | rate c /h | gate open c "
            "| E5 silent/moves | E1 manual inside/named | E1 frozen inside/named |")
    lines = [f"# exp27 results: {name} seeds", "", head, "|" + "---|" * 12]
    lines += [seed_line(row) for row in rows]
    lines += ["", "| id | value | pass |", "|---|---|---|"]
    lines += [f"| {k} | {v['value']} | {'yes' if v['pass'] else 'NO'} |"
              for k, v in verdict.items()]
    gate = _median([row["arms"]["c"]["gate_open_share"] for row in rows])
    lines += ["", f"Median gate-open share of arm c (fault-free, operator instants): {gate:.3f}"]
    return "\n".join(lines) + "\n"


def run(seeds: tuple[int, ...], plan: Plan, out: Path, name: str) -> dict[str, Any]:
    """Run ``seeds``, write ``<name>_runs.json`` and ``<name>.md`` under ``out``."""
    sups = load_supervisors()
    rows = [run_seed(seed, plan, sups) for seed in seeds]
    verdict = criteria(rows, sups["c"].config.min_interval_s)
    out.mkdir(parents=True, exist_ok=True)
    payload = {"seeds": list(seeds), "plan": asdict(plan), "criteria": verdict, "runs": rows}
    (out / f"{name}_runs.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    (out / f"{name}.md").write_text(report(name, rows, verdict), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> None:
    """CLI: ``--seeds dev|test`` and ``--out`` (default: results/ next to this file)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", choices=sorted(SEED_SETS), required=True)
    parser.add_argument("--out", type=Path, default=HERE / "results")
    args = parser.parse_args(argv)
    payload = run(SEED_SETS[args.seeds], Plan(), args.out, args.seeds)
    print((args.out / f"{args.seeds}.md").read_text(encoding="utf-8"))
    print(json.dumps(payload["criteria"], indent=1))


if __name__ == "__main__":
    main()
