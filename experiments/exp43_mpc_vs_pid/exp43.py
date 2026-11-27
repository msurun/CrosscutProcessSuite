"""exp43: frozen-protocol comparison of MPC, tuned PID and fuzzy on the RougherSim grinding bed.

The plant is RougherSim (pinned commit in frozen_config.json) stepped in process. The MPC model is
identified from the #24 sequential step test plus one measured-disturbance pulse; PID is tuned
per loop by SIMC from the same identified model; fuzzy is a fixed rule base. All three act on the
setpoints of the same two flow/speed loops under the same range and move limits. Importing this
module never starts a simulation; ``python exp43.py --seeds development|held_out`` does.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from crosscut_fuzzy.model import system_from_dict
from crosscut_loops.tuning_rules import FopdtModel, lambda_from_robustness, simc_pi
from crosscut_mpc.identification import (
    Dataset,
    IdentificationRejected,
    IdentifiedModel,
    PairSpec,
    identify_mimo,
)
from crosscut_runtime.controllers.fuzzy import FuzzyController
from crosscut_runtime.controllers.mpc import MpcController
from crosscut_runtime.controllers.mpc_limits import clamp_move
from crosscut_runtime.controllers.mpc_model import BoundModel
from crosscut_runtime.controllers.protocol import Move, StepResult
from crosscut_runtime.variable_status import VariableStatus

HERE = Path(__file__).resolve().parent
CONFIG: dict[str, Any] = json.loads((HERE / "frozen_config.json").read_text(encoding="utf-8"))
MV_IDS = list(CONFIG["mvs"])  # model order: FIC102, SIC201
CV_IDS = list(CONFIG["cvs"])  # model order: JT101, PDT204
DV_ID = CONFIG["dv"]["id"]
CYCLE_S = float(CONFIG["plant"]["cycle_s"])
STEPS_PER_CYCLE = int(CYCLE_S / CONFIG["plant"]["dt_s"])
CONTROLLERS = ("pid", "fuzzy", "mpc")
# Ground truth of RougherSim step_test.json (seed 100024): CV unit per SP unit, self-regulating
# pairs only; pairs the truth calls integrating have no static gain and are listed as 0.0.
TRUTH_SP_GAINS = {
    ("WIC101", "PDT204"): 0.019542677837094367, ("WIC101", "DIT202"): 0.05632692747839742,
    ("FIC102", "PDT204"): 0.004300114459556536, ("FIC102", "DIT202"): 0.012519433346450818,
    ("FIC102", "JT101"): -28.750140364704063, ("SIC201", "PDT204"): 4.972410457531595,
    ("WIC101", "JT101"): 0.0, ("SIC201", "DIT202"): 0.0, ("SIC201", "JT101"): 0.0,
}
TRUTH_AMPLITUDE = {"WIC101": 8.0, "FIC102": 4.0, "SIC201": 2.0}


# ---------------------------------------------------------------- conditioning of a pair set
def conditioning(gains: Sequence[Sequence[float]], amplitudes: Sequence[float]) -> dict[str, Any]:
    """Condition number (columns scaled by test amplitude, rows to unit norm) and RGA of G.

    Rows are CVs, columns MVs. Scaling makes the number independent of engineering units.
    """
    matrix = np.asarray(gains, dtype=float) * np.asarray(amplitudes, dtype=float)
    scaled = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    cond = float(np.linalg.cond(scaled))
    try:
        rga = (matrix * np.linalg.inv(matrix).T).tolist()
    except np.linalg.LinAlgError:
        rga = None  # singular gain matrix: the RGA does not exist
    return {"cond": cond, "rga": rga}


def candidate_sets() -> dict[str, dict[str, Any]]:
    """Conditioning of the rejected L5 pair set and the chosen set, from the ground truth."""
    sets = {
        "rejected: WIC101,FIC102 -> PDT204,DIT202": (("WIC101", "FIC102"), ("PDT204", "DIT202")),
        "chosen: FIC102,SIC201 -> JT101,PDT204": (("FIC102", "SIC201"), ("JT101", "PDT204")),
    }
    out = {}
    for name, (mvs, cvs) in sets.items():
        gains = [[TRUTH_SP_GAINS[(m, c)] for m in mvs] for c in cvs]
        out[name] = conditioning(gains, [TRUTH_AMPLITUDE[m] for m in mvs])
    return out


def identified_conditioning(model: IdentifiedModel) -> dict[str, Any]:
    """Conditioning of the identified MV block (disabled pairs count as zero gain)."""
    gains = np.where(np.asarray(model.enabled), model.gains, 0.0)[:, : len(MV_IDS)]
    return conditioning(gains.tolist(), [CONFIG["mvs"][m]["amplitude"] for m in MV_IDS])


# ---------------------------------------------------------------------------- the plant
def scaled(value: float, cv: str) -> float:
    """CV value in the controller unit (JT101 in MW so the QP is not badly scaled; PDT204 kPa)."""
    return float(value) * float(CONFIG["cvs"][cv]["scale"])


def roughersim_dir() -> Path:
    """RougherSim checkout: ``ROUGHERSIM_DIR`` or the sibling ``../RougherSim``."""
    import os
    env = os.environ.get("ROUGHERSIM_DIR")
    return Path(env) if env else HERE.parents[2] / "RougherSim"


def check_pinned_commit(rs_dir: Path) -> str:
    """Return the checkout's commit; refuse a checkout that is not the pinned one."""
    sha = subprocess.run(["git", "-C", str(rs_dir), "rev-parse", "HEAD"], capture_output=True,
                         text=True, check=True).stdout.strip()
    if sha != CONFIG["plant"]["commit"]:
        raise RuntimeError(f"RougherSim at {sha}, protocol pins {CONFIG['plant']['commit']}")
    return sha


def new_plant(seed: int, hardness_sigma: float) -> Any:
    """Build the grinding plant with a seed and an OU hardness disturbance of ``hardness_sigma``."""
    rs_dir = roughersim_dir()
    sys.path.insert(0, str(rs_dir / "src"))
    from roughersim.control.plant_loader import load_plant_dict
    doc = json.loads((rs_dir / CONFIG["plant"]["flowsheet"]).read_text(encoding="utf-8"))
    doc["seed"] = seed
    for item in doc["disturbances"]:
        if item["name"] == CONFIG["plant"]["hardness_disturbance"]:
            item["sigma"] = hardness_sigma
    return load_plant_dict(doc)


def warmed_plant(seed: int, hardness_sigma: float) -> Any:
    """A new plant run for the warm-up time (no recording)."""
    plant = new_plant(seed, hardness_sigma)
    plant.run(int(CONFIG["plant"]["warmup_s"] / CONFIG["plant"]["dt_s"]))
    return plant


# ----------------------------------------------------------------------- identification
def ident_events() -> list[dict[str, Any]]:
    """Operator SP events of the #24 sequential scenario, plus the added hardness block."""
    path = roughersim_dir() / CONFIG["plant"]["ident_scenario"]
    events = [{"t_s": e["t_s"], "tag": e["target"], "sp": e["params"]["value"]}
              for e in json.loads(path.read_text(encoding="utf-8"))["events"]]
    return events


def record_ident_trace() -> dict[str, np.ndarray]:
    """Run the step test on a warmed plant; sample every controller cycle.

    Returns time [s] and, per tag, the SP (MV), measured hardness (DV) or measured CV.
    """
    ident = CONFIG["identification"]
    plant = warmed_plant(CONFIG["plant"]["ident_seed"], 0.0)
    events, nominal = ident_events(), {k: v["nominal"] for k, v in CONFIG["mvs"].items()}
    sp, rows, pending = dict(nominal), [], list(events)
    total = int(ident["dv_block_end_s"] / CONFIG["plant"]["dt_s"])
    for step in range(total):
        t = step * CONFIG["plant"]["dt_s"]
        while pending and pending[0]["t_s"] <= t:
            event = pending.pop(0)
            plant.submit_write(event["tag"], "sp", event["sp"])
            sp[event["tag"]] = event["sp"]
        if t in (ident["dv_block_start_s"], ident["dv_block_off_s"]):
            offset = CONFIG["dv"]["ident_offset"] if t == ident["dv_block_start_s"] else 0.0
            plant.set_disturbance_offset(CONFIG["dv"]["disturbance"], offset)
        plant.step()
        if step % STEPS_PER_CYCLE == 0:
            rows.append([t, *(sp[m] for m in MV_IDS), plant.readings[DV_ID][0],
                         *(scaled(plant.readings[c][0], c) for c in CV_IDS)])
    data = np.array(rows)
    names = ["t", *MV_IDS, DV_ID, *CV_IDS]
    return {name: data[:, i] for i, name in enumerate(names)}


def identify_from_trace(trace: Mapping[str, np.ndarray]) -> IdentifiedModel:
    """Fit every (CV, input) pair on its window and keep the pairs that are significant.

    A pair is enabled when it passes the Crosscut gate and its response to the test amplitude is at
    least ``min_signal_to_noise`` times the CV noise. The two required (diagonal) pairs must be
    enabled, else ``IdentificationRejected``.
    """
    ident, time = CONFIG["identification"], np.asarray(trace["t"])
    inputs = {m: np.asarray(trace[m]) - CONFIG["mvs"][m]["nominal"] for m in MV_IDS}
    inputs[DV_ID] = np.asarray(trace[DV_ID]) - float(np.asarray(trace[DV_ID])[0])
    outputs = {c: np.asarray(trace[c]) for c in CV_IDS}
    pairs = []
    for name in inputs:
        lo, hi = ident["windows_s"][name]
        start, stop = int(np.searchsorted(time, lo)), int(np.searchsorted(time, hi))
        pairs += [PairSpec(name, cv, start, stop) for cv in CV_IDS]
    model = identify_mimo(Dataset(time, inputs, outputs), pairs, ident["max_delay_s"])
    enabled = significant_pairs(model)
    for mv, cv in ident["required_pairs"]:
        if not enabled[CV_IDS.index(cv)][list(inputs).index(mv)]:
            raise IdentificationRejected(f"required pair {mv}->{cv} failed the gate or SNR rule")
    return dataclasses.replace(model, enabled=enabled)


def significant_pairs(model: IdentifiedModel) -> tuple[tuple[bool, ...], ...]:
    """Enable mask [CV][input]: gate passed and |K| x test amplitude >= SNR x CV noise sd."""
    amplitude = {m: CONFIG["mvs"][m]["amplitude"] for m in MV_IDS}
    amplitude[DV_ID] = CONFIG["dv"]["ident_offset"]
    snr = CONFIG["identification"]["min_signal_to_noise"]
    return tuple(
        tuple(bool(q.passed and abs(model.gains[r, c]) * amplitude[name]
                   >= snr * CONFIG["cvs"][cv]["noise_sd"])
              for c, (name, q) in enumerate(zip(model.input_names, row, strict=True)))
        for r, (cv, row) in enumerate(zip(model.cv_names, model.quality, strict=True)))


# --------------------------------------------------------------------------- catalogue
def catalogue(targets: Mapping[str, float]) -> list[dict[str, Any]]:
    """Controller variables with the common limits (the same document feeds every controller)."""
    variables: list[dict[str, Any]] = []
    for mv, spec in CONFIG["mvs"].items():
        variables.append({"id": mv, "role": "MV", "limits": {
            "operator": {"lo": spec["range"][0], "hi": spec["range"][1]},
            "move_max": spec["move_max"]}})
    for cv, spec in CONFIG["cvs"].items():
        variables.append({"id": cv, "role": "CV", "priority": spec["priority"],
                          "target": targets[cv],
                          "limits": {"operator": {"lo": spec["range"][0], "hi": spec["range"][1]}}})
    variables.append({"id": DV_ID, "role": "DV", "limits": {"eng": {"lo": 0.0, "hi": 3.0}}})
    return variables


# ------------------------------------------------------------------------------- PID
class PidController:
    """Two velocity-form PI loops (CV -> MV setpoint), tuned by SIMC from the identified model."""

    def __init__(self, tunings: Mapping[str, tuple[str, float, float]]) -> None:
        """``tunings``: MV id -> (CV id, signed gain kc [MV/CV], integral time [s])."""
        self.id = "pid"
        self._tunings = dict(tunings)
        self._vars: dict[str, Mapping[str, Any]] = {}
        self._previous: dict[str, float] = {}
        self._last: dict[str, float] = {}

    def apply_limits(self, variables: Sequence[Mapping[str, Any]]) -> None:
        """Take limits and CV targets of the current catalogue."""
        self._vars = {v["id"]: v for v in variables}

    def initialise(self, statuses: Sequence[VariableStatus]) -> None:
        """Forget the error memory; the next step starts without a kick."""
        del statuses
        self._previous, self._last = {}, {}

    def step(self, statuses: Sequence[VariableStatus]) -> StepResult:
        """One cycle: du = kc * ((e - e_prev) + dt/ti * e) per loop, cut to the common limits."""
        by_id = {s.variable_id: s for s in statuses}
        moves = []
        for mv, (cv, kc, ti_s) in self._tunings.items():
            error = float(self._vars[cv]["target"]) - float(by_id[cv].value or 0.0)
            current = float(by_id[mv].sp_value or 0.0)
            if mv in self._previous:
                delta = kc * ((error - self._previous[mv]) + CYCLE_S / ti_s * error)
                new = clamp_move(self._vars[mv], current, current + delta, CYCLE_S,
                                 self._last.get(mv))
                moves.append(Move(mv, mv, new, "pid"))
                self._last[mv] = new
            self._previous[mv] = error
        return StepResult(tuple(moves), "pid")


def pid_tunings(model: IdentifiedModel) -> dict[str, tuple[str, float, float]]:
    """SIMC PI per loop from the identified diagonal pair (sign of the gain kept in kc)."""
    robustness = CONFIG["controllers"]["pid"]["robustness"]
    result = {}
    for mv in MV_IDS:
        cv_id = next(c for c, s in CONFIG["cvs"].items() if s["loop_mv"] == mv)
        row, col = model.cv_names.index(cv_id), model.input_names.index(mv)
        fopdt = FopdtModel(abs(float(model.gains[row, col])),
                           float(model.time_constants_s[row, col]),
                           max(float(model.dead_times_s[row, col]), CYCLE_S / 2))
        pi = simc_pi(fopdt, lambda_from_robustness(fopdt, robustness))
        sign = 1.0 if model.gains[row, col] > 0 else -1.0
        result[mv] = (cv_id, sign * pi.kc, pi.ti_s)
    return result


# ----------------------------------------------------------------------------- fuzzy
def _terms(span: float, names: Sequence[str]) -> list[dict[str, Any]]:
    """Five triangular terms centred at -1, -0.4, 0, 0.4, 1 times ``span`` (edges closed)."""
    centres = [-span, -0.4 * span, 0.0, 0.4 * span, span]
    padded = [centres[0], *centres, centres[-1]]
    return [{"name": name, "shape": "tri", "params": padded[i:i + 3]}
            for i, name in enumerate(names)]


def fuzzy_document() -> dict[str, Any]:
    """Rule base: error of each CV (PV - target) -> delta of the MV that moves it.

    Power too high needs more mill water (negative gain), pressure too high needs less pump speed.
    """
    spans = CONFIG["controllers"]["fuzzy"]
    err = ["neg_large", "neg_small", "zero", "pos_small", "pos_large"]
    delta = ["dec_large", "dec_small", "hold", "inc_small", "inc_large"]
    inputs = [{"id": "jt_err", "unit": "MW", "low": -spans["input_span"]["jt_err"],
               "high": spans["input_span"]["jt_err"],
               "terms": _terms(spans["input_span"]["jt_err"], err)},
              {"id": "pdt_err", "unit": "kPa", "low": -spans["input_span"]["pdt_err"],
               "high": spans["input_span"]["pdt_err"],
               "terms": _terms(spans["input_span"]["pdt_err"], err)}]
    outputs = [{"id": "FIC102", "unit": "m3/h", "low": -spans["fic_delta"],
                "high": spans["fic_delta"], "terms": _terms(spans["fic_delta"], delta)},
               {"id": "SIC201", "unit": "%", "low": -spans["sic_delta"],
                "high": spans["sic_delta"], "terms": _terms(spans["sic_delta"], delta)}]
    rules = [{"id": f"{i}_{n}", "if": [{"variable": i, "is": e}],
              "then": {"variable": mv, "is": d}}
             for i, mv, order in (("jt_err", "FIC102", delta), ("pdt_err", "SIC201", delta[::-1]))
             for n, (e, d) in enumerate(zip(err, order, strict=True))]
    return {"schema_version": "0.1.0", "name": "exp43 grinding fuzzy", "inputs": inputs,
            "outputs": outputs, "rules": rules}


def fuzzy_controller() -> FuzzyController:
    """The existing runtime fuzzy controller on the frozen rule base."""
    variables = catalogue({c: s["target"] for c, s in CONFIG["cvs"].items()})
    variables += [{"id": "jt_err", "role": "CV"}, {"id": "pdt_err", "role": "CV"}]
    doc = {"id": "fuzzy", "cycle_s": CYCLE_S, "variables": variables}
    return FuzzyController(doc, system_from_dict(fuzzy_document()), {m: m for m in MV_IDS})


# ------------------------------------------------------------------------------- MPC
def mpc_controller(model: IdentifiedModel) -> MpcController:
    """The runtime MPC controller on the identified model (bound in MV, CV, DV order)."""
    settings = CONFIG["controllers"]["mpc"]
    bound = BoundModel(model.to_mpc_model(), tuple(MV_IDS), tuple(CV_IDS), (DV_ID,))
    doc = {"id": "mpc", "cycle_s": CYCLE_S, "mpc": dict(settings),
           "variables": catalogue({c: s["target"] for c, s in CONFIG["cvs"].items()})}
    return MpcController(doc, bound, {m: m for m in MV_IDS})


def make_controller(name: str, model: IdentifiedModel) -> Any:
    """Controller by name (pid, fuzzy, mpc) built from the identified model."""
    if name == "pid":
        return PidController(pid_tunings(model))
    return fuzzy_controller() if name == "fuzzy" else mpc_controller(model)


# -------------------------------------------------------------------------- closed loop
def read_statuses(plant: Any, sp: Mapping[str, float],
                  targets: Mapping[str, float]) -> list[VariableStatus]:
    """Live statuses from the plant readings (noisy, as a DCS would deliver them)."""
    reading = {tag: value for tag, (value, _) in plant.readings.items()}
    pv = {"FIC102": reading["FIT102"], "SIC201": reading["SIT201"]}
    statuses = [VariableStatus(m, m, "good", (), pv[m], "", sp[m]) for m in MV_IDS]
    values = {c: scaled(reading[c], c) for c in CV_IDS} | {DV_ID: reading[DV_ID]}
    values["jt_err"] = values["JT101"] - targets["JT101"]
    values["pdt_err"] = values["PDT204"] - targets["PDT204"]
    statuses += [VariableStatus(k, k, "good", (), v, "") for k, v in values.items()]
    return statuses


def apply_event(plant: Any, event: Mapping[str, Any], targets: dict[str, float]) -> None:
    """Apply one scenario event: a CV target change or a hardness offset."""
    if event["kind"] == "target":
        targets[event["cv"]] = float(event["value"])
    else:
        plant.set_disturbance_offset(CONFIG["dv"]["disturbance"], float(event["value"]))


def run_closed_loop(plant: Any, controller: Any) -> dict[str, np.ndarray]:
    """Run the frozen scenario and return per-step truth traces (CV, SP, target, time)."""
    sp = {m: float(s["nominal"]) for m, s in CONFIG["mvs"].items()}
    targets = {c: float(s["target"]) for c, s in CONFIG["cvs"].items()}
    events = sorted(CONFIG["scenario"]["events"], key=lambda e: e["t_s"])
    controller.apply_limits(catalogue(targets))
    controller.initialise(read_statuses(plant, sp, targets))
    keys = ["t", *CV_IDS, *(f"sp_{m}" for m in MV_IDS), *(f"target_{c}" for c in CV_IDS)]
    trace: dict[str, list[float]] = {k: [] for k in keys}
    for cycle in range(int(CONFIG["scenario"]["duration_s"] / CYCLE_S)):
        while events and events[0]["t_s"] <= cycle * CYCLE_S:
            apply_event(plant, events.pop(0), targets)
        controller.apply_limits(catalogue(targets))
        result = controller.step(read_statuses(plant, sp, targets))
        for move in result.moves:
            sp[move.variable_id] = move.value
            plant.submit_write(move.variable_id, "sp", move.value)
        for k in range(STEPS_PER_CYCLE):
            plant.step()
            row = {"t": (cycle * STEPS_PER_CYCLE + k + 1) * CONFIG["plant"]["dt_s"]}
            row |= {c: scaled(plant.truth[c], c) for c in CV_IDS}
            row |= {f"sp_{m}": sp[m] for m in MV_IDS}
            row |= {f"target_{c}": targets[c] for c in CV_IDS}
            for key, value in row.items():
                trace[key].append(value)
    return {k: np.array(v) for k, v in trace.items()}


# ------------------------------------------------------------------------------- KPIs
def compute_kpis(trace: Mapping[str, np.ndarray]) -> dict[str, float]:
    """IAE, mean-square error, limit violation, MV travel and margin to the JT101 upper limit (MW).

    CV errors are divided by the CV operator span so the two CVs add up; violation integrals use
    the same scaling (units: seconds of span). Travel is summed |dSP| over the MV range.
    """
    dt = float(trace["t"][1] - trace["t"][0])
    kpis = {"iae": 0.0, "mse": 0.0, "violation": 0.0, "violation_time_s": 0.0}
    for cv, spec in CONFIG["cvs"].items():
        lo, hi = spec["range"]
        y, error = trace[cv], (trace[cv] - trace[f"target_{cv}"]) / (hi - lo)
        outside = np.maximum(y - hi, 0.0) + np.maximum(lo - y, 0.0)
        kpis["iae"] += float(np.sum(np.abs(error)) * dt)
        kpis["mse"] += float(np.mean(error ** 2))
        kpis["violation"] += float(np.sum(outside) * dt / (hi - lo))
        kpis["violation_time_s"] += float(np.count_nonzero(outside) * dt)
    kpis["travel"] = sum(
        float(np.sum(np.abs(np.diff(trace[f"sp_{m}"]))) / (s["range"][1] - s["range"][0]))
        for m, s in CONFIG["mvs"].items())
    start, stop = CONFIG["scenario"]["high_hardness_window_s"]
    window = (trace["t"] >= start) & (trace["t"] < stop)
    kpis["margin_mw"] = float(np.mean(CONFIG["cvs"]["JT101"]["range"][1] - trace["JT101"][window]))
    return kpis


def _ratios(mpc: Sequence[float], other: Sequence[float]) -> np.ndarray:
    """Paired MPC/other ratios; a zero-zero pair counts as 1 (a tie)."""
    a, b = np.asarray(mpc, dtype=float), np.asarray(other, dtype=float)
    return np.where((a == 0) & (b == 0), 1.0, a / np.where(b == 0, np.nan, b))


def evaluate(kpis: Mapping[str, Mapping[str, Sequence[float]]]) -> dict[str, Any]:
    """Apply the frozen pass criteria. ``kpis[controller][kpi]`` lists one value per seed.

    P1 IAE: median paired ratio MPC/other <= iae_median_ratio_max and MPC wins on at least
    iae_win_share_min of the seeds. P2 violation: median MPC <= ratio x median other + epsilon.
    P3 travel: median paired ratio <= travel_median_ratio_max. Each against PID and fuzzy.
    """
    crit, out = CONFIG["criteria"], {}
    for other in ("pid", "fuzzy"):
        iae = _ratios(kpis["mpc"]["iae"], kpis[other]["iae"])
        travel = _ratios(kpis["mpc"]["travel"], kpis[other]["travel"])
        wins = float(np.mean(np.asarray(kpis["mpc"]["iae"]) < np.asarray(kpis[other]["iae"])))
        v_mpc, v_other = (float(np.median(kpis[n]["violation"])) for n in ("mpc", other))
        out[other] = {
            "P1_iae": bool(np.nanmedian(iae) <= crit["iae_median_ratio_max"]
                           and wins >= crit["iae_win_share_min"]),
            "P2_violation": bool(v_mpc <= crit["violation_median_ratio_max"] * v_other
                                 + crit["violation_tie_epsilon"]),
            "P3_travel": bool(np.nanmedian(travel) <= crit["travel_median_ratio_max"]),
            "iae_median_ratio": float(np.nanmedian(iae)), "iae_win_share": wins,
            "violation_median": {"mpc": v_mpc, other: v_other},
            "travel_median_ratio": float(np.nanmedian(travel)),
        }
    out["verdict"] = "advantage" if all(
        v for o in ("pid", "fuzzy") for k, v in out[o].items() if k.startswith("P")
    ) else "no demonstrated advantage"
    return out


# ------------------------------------------------------------------------------ driver
def run_seed(seed: int, model: IdentifiedModel) -> dict[str, dict[str, float]]:
    """All three controllers from the same warmed state (same noise streams) on one seed."""
    base = warmed_plant(seed, CONFIG["plant"]["hardness_sigma"])
    return {name: compute_kpis(run_closed_loop(copy.deepcopy(base), make_controller(name, model)))
            for name in CONTROLLERS}


def _seed_job(args: tuple[int, IdentifiedModel]) -> tuple[int, dict[str, dict[str, float]]]:
    """Process-pool entry: one seed."""
    return args[0], run_seed(*args)


def run_seeds(seeds: Sequence[int], model: IdentifiedModel, workers: int) -> dict[str, Any]:
    """Run seeds in parallel; return per-seed KPIs and the transposed KPI lists."""
    with ProcessPoolExecutor(workers) as pool:
        per_seed = dict(pool.map(_seed_job, [(s, model) for s in seeds]))
    table = {n: {k: [per_seed[s][n][k] for s in seeds] for k in per_seed[seeds[0]][n]}
             for n in CONTROLLERS}
    return {"per_seed": {str(s): per_seed[s] for s in seeds}, "kpis": table}


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: identify once, run the chosen seed set, write ``<out>/exp43_<set>.json``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", choices=("development", "held_out"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    commit = check_pinned_commit(roughersim_dir())
    model = identify_from_trace(record_ident_trace())
    result = run_seeds(CONFIG["seeds"][args.seeds], model, args.workers)
    result |= {"commit": commit, "evaluation": evaluate(result["kpis"]),
               "model": {"gains": model.gains.tolist(), "tau_s": model.time_constants_s.tolist(),
                         "theta_s": model.dead_times_s.tolist(),
                         "enabled": [list(r) for r in model.enabled or ()],
                         "inputs": list(model.input_names), "cvs": list(model.cv_names)},
               "conditioning": candidate_sets() | {"identified": identified_conditioning(model)}}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"exp43_{args.seeds}.json").write_text(json.dumps(result, indent=2),
                                                         encoding="utf-8")
    print(json.dumps(result["evaluation"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
