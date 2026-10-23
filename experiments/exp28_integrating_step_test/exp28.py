"""exp28 harness: step-test identification of level loops, refusals, PI safety, looks_integrating.

Runs the FROZEN protocols of README.md. Round 1 (default): per record identify_ipdt, SIMC PI from
the point estimate checked on the true plant (exp26 settled / oscillating definitions),
looks_integrating through the shipped tuning payload; results/<seeds>.md + _runs.json (I1..I4).
Round 2 (``--round 2``): new seeds, the PI is the one the shipped integrating payload proposes
(dead time delay_used_s), the dead-time interval is checked; results/<seeds>2.md (J1..J4)."""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from crosscut_loops.identification_ipdt import IpdtFit, identify_ipdt
from crosscut_loops.overview import LoopTags
from crosscut_loops.tuning_payload import tuning_payload
from crosscut_loops.tuning_rules_integrating import (
    lambda_from_robustness_integrating,
    simc_pi_integrating,
)
from crosscut_loops.tuning_types import TuningRequest
from crosscut_sim.pid import PID, OutputLimits, PidTuning

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "exp26_history_tuning_level"))
import gen28  # noqa: E402
from run26 import judge_response  # noqa: E402  (exp26 settled / oscillating definitions)

ROBUSTNESS = 0.5
ACCEPTED = ("ok", "low_confidence")
SP_STEP = 5.0  # % PV
SP_STEP_TIME_S = 50.0  # s; must equal run26.SP_STEP_TIME_S
HORIZON_FACTOR = 40.0  # T = 50 + 40 (theta + 4 / (k Kc))
K_TOL, THETA_TOL_ABS, THETA_TOL_REL = 0.15, 1.0, 0.30
I1_ACCEPT, I1_ACCURATE = 0.70, 0.90
I2_BLOCKED, I2_OK = 0.90, 0.05
I4_FIRE, I4_FALSE = 0.90, 0.10
RUNS_PER_CELL, RUNS_PER_BAD = 4, 25
MANUAL_MODE = 0.0
LOOP = LoopTags(name="LIC", pv="pv", sp="sp", out="out", mode="mode", unit="%",
                eng_min=0.0, eng_max=100.0, out_low=0.0, out_high=100.0,
                process_kind="self_regulating")
LOOKS_INTEGRATING_KINDS = ("good", "B1", "B2")
# Round 2: the same loop marked integrating, so the payload runs the shipped IPDT tuning path.
LOOP_INTEGRATING = dataclasses.replace(LOOP, process_kind="integrating")
J1_SAFE, J2_COVER, J3_BLOCKED, J3_ACCEPT, J4_OVERSHOOT = 1.0, 0.90, 0.90, 0.70, 0.35
INTERVAL_FIELDS = ("delay_lower_s", "delay_upper_s")  # IpdtFit fields of round 2
PAYLOAD_MODEL_KEYS = ("delay_lower_s", "delay_upper_s", "delay_used_s")  # payload "model" keys


@dataclasses.dataclass(frozen=True)
class Round:
    """Seed bases of one frozen round and the suffix of its result files."""

    dev: int
    good: int
    bad: int
    valve: int
    suffix: str


ROUNDS = {1: Round(dev=28001, good=28101, bad=28401, valve=28501, suffix=""),
          2: Round(dev=30001, good=30101, bad=30401, valve=30501, suffix="2")}


def plan(seeds: str, round_no: int = 1) -> list[tuple[str, object, int]]:
    """(kind, cell or bad kind, seed) for 'dev' or 'test' of one round, in protocol order."""
    good, base = gen28.good_cells(), ROUNDS[round_no]
    if seeds == "dev":
        return [("good", cell, base.dev + i) for i, cell in enumerate(good)]
    runs = [("good", c, base.good + RUNS_PER_CELL * i + j)
            for i, c in enumerate(good) for j in range(RUNS_PER_CELL)]
    runs += [(kind, kind, base.bad + RUNS_PER_BAD * i + j)
             for i, kind in enumerate(gen28.BAD_KINDS) for j in range(RUNS_PER_BAD)]
    runs += [("valve", c, base.valve + RUNS_PER_CELL * i + j)
             for i, c in enumerate(gen28.valve_cells()) for j in range(RUNS_PER_CELL)]
    return runs


def make_record(kind: str, spec: object, seed: int) -> gen28.Record:
    """Generate the record of one planned run."""
    if kind in ("good", "valve"):
        return gen28.cell_record(spec, seed)
    return gen28.bad_record(spec, seed)


def true_slope(plant: dict) -> float:
    """True k' (ipdt rate) or the initial slope K / tau of a FOPDT plant."""
    return plant["rate"] if plant["type"] == "ipdt" else plant["gain"] / plant["tau_s"]


def fit_summary(fit, plant: dict) -> dict:
    """Verdict, model, quality figures and the errors against the true plant."""
    k_hat, theta_hat = fit.model.slope_per_s, fit.model.delay_s
    k_true, theta_true = true_slope(plant), plant["delay_s"]
    rel_k = abs(k_hat - k_true) / k_true
    theta_err = theta_hat - theta_true
    accurate = rel_k <= K_TOL and abs(theta_err) <= max(THETA_TOL_ABS, THETA_TOL_REL * theta_true)
    return {
        "verdict": fit.verdict, "reasons": list(fit.reasons), "k_hat": k_hat,
        "theta_hat": theta_hat, "r2": fit.r_squared,
        "slope_rel_se": fit.slope_rel_se if math.isfinite(fit.slope_rel_se) else None,
        "up_down_ratio": fit.up_down_ratio, "rel_k_err": rel_k, "theta_err": theta_err,
        "accurate": bool(accurate),
    }


def proposed_pi(k_hat: float, theta_hat: float) -> dict | None:
    """SIMC PI at robustness 0.5; direct action for a negative slope (as the library's report)."""
    try:
        tau_c = lambda_from_robustness_integrating(theta_hat, ROBUSTNESS)
        pi = simc_pi_integrating(k_hat, theta_hat, tau_c)
    except ValueError as error:
        return {"error": str(error)}
    return {"kc": pi.kc, "ti_s": pi.ti_s, "tau_c_s": tau_c, "direct": k_hat < 0.0}


def closed_loop(plant: dict, pi: dict, band: float) -> dict:
    """+5 % SP step at 50 s under the PI on the true plant, no load, no noise; exp26 judgement."""
    horizon = SP_STEP_TIME_S + HORIZON_FACTOR * (
        plant["delay_s"] + 4.0 / (true_slope(plant) * pi["kc"]))
    n = math.ceil(horizon / gen28.DT_S)
    t_s = np.arange(n) * gen28.DT_S
    sp = np.where(t_s < SP_STEP_TIME_S, gen28.PV_START, gen28.PV_START + SP_STEP)
    out, pv = _run_loop(plant, pi, sp, band)
    verdict = judge_response({"t_s": t_s, "sp": sp, "pv": pv, "op": out}, SP_STEP)
    return {k: (bool(v) if isinstance(v, (bool, np.bool_)) else float(v))
            for k, v in verdict.items()} | {"horizon_s": float(horizon)}


def _run_loop(plant: dict, pi: dict, sp: np.ndarray, band: float) -> tuple[np.ndarray, np.ndarray]:
    """PI in AUTO from rest at OUT 50; valve with deadband ``band``; returns (out, pv)."""
    model = gen28.make_plant(plant)
    pid = PID(PidTuning(pi["kc"], pi["ti_s"]), gen28.DT_S, OutputLimits(*gen28.OUT_LIMITS),
              direct=pi["direct"])
    pid.update(gen28.PV_START, gen28.PV_START, "MAN", gen28.OUT_BIAS)
    out, pv = np.empty(len(sp)), np.empty(len(sp))
    deviation, valve = 0.0, gen28.OUT_BIAS
    for i in range(len(sp)):
        pv[i] = gen28.PV_START + deviation
        out[i] = pid.update(pv[i], sp[i], "AUTO")
        valve = gen28.valve_step(valve, out[i], band)
        deviation = model.update(valve - gen28.OUT_BIAS)
    return out, pv


def looks_integrating(record: gen28.Record) -> dict:
    """Warnings of the shipped payload on the whole record, loop marked self_regulating, MAN."""
    columns = {"pv": record.pv, "out": record.out, "sp": np.full(len(record.t_s), gen28.PV_START),
               "mode": np.full(len(record.t_s), MANUAL_MODE)}
    request = TuningRequest(start_s=float(record.t_s[0]), end_s=float(record.t_s[-1]),
                            robustness=ROBUSTNESS)
    payload = tuning_payload(LOOP, record.t_s, columns, request)
    hits = [w for w in payload["warnings"] if w.get("code") == "looks_integrating"]
    return {"fires": bool(hits), "reason": hits[0]["reason"] if hits else None,
            "fopdt_blocked_code": payload.get("blocked_code")}


def require_round2_api() -> None:
    """Fail fast when the library lacks the round 2 dead-time interval of ``IpdtFit``."""
    names = {f.name for f in dataclasses.fields(IpdtFit)}
    missing = [n for n in INTERVAL_FIELDS if n not in names]
    if missing:
        raise RuntimeError(f"round 2 needs IpdtFit.{', IpdtFit.'.join(missing)} (crosscut_loops."
                           "identification_ipdt); the library change is not in place")


def interval_summary(fit, plant: dict) -> dict:
    """Round 2: the profile interval of the dead time and whether it holds the true theta (J2)."""
    lower, upper = (float(getattr(fit, name)) for name in INTERVAL_FIELDS)
    theta_true = plant["delay_s"]
    return {"theta_lower": lower, "theta_upper": upper,
            "theta_covered": bool(lower <= theta_true <= upper)}


def payload_model_keys(model: dict | None) -> dict:
    """The round 2 keys of the payload ``model`` object; RuntimeError naming any missing key."""
    missing = [k for k in PAYLOAD_MODEL_KEYS if model is None or k not in model]
    if missing:
        raise RuntimeError(f"tuning payload model lacks {missing} (crosscut_loops."
                           "tuning_payload_ipdt); the library change is not in place")
    return {k: model[k] for k in PAYLOAD_MODEL_KEYS}


def product_pi(record: gen28.Record, fit) -> dict:
    """Round 2: the PI the shipped payload proposes for the loop marked integrating, MAN window.

    Returns the payload model keys and ``pi`` (settings or the blocked code). The payload fits the
    same samples as the harness; another verdict or delay means the window differs (harness bug).
    """
    columns = {"pv": record.pv, "out": record.out, "sp": np.full(len(record.t_s), gen28.PV_START),
               "mode": np.full(len(record.t_s), MANUAL_MODE)}
    request = TuningRequest(start_s=float(record.t_s[0]), end_s=float(record.t_s[-1]),
                            robustness=ROBUSTNESS)
    payload = tuning_payload(LOOP_INTEGRATING, record.t_s, columns, request)
    keys = payload_model_keys(payload["model"])
    model = payload["model"]
    if (model["verdict"], model["delay_s"]) != (fit.verdict, fit.model.delay_s):
        raise RuntimeError(f"payload fit differs from identify_ipdt on the record: {model}")
    return {"payload_model": keys, "pi": _payload_settings(payload, keys["delay_used_s"])}


def _payload_settings(payload: dict, delay_used_s: float) -> dict:
    """PI of the payload in the harness form, or the payload's blocked code and reasons."""
    settings = payload.get("settings")
    if settings is None:
        return {"error": f"payload blocked: {payload['blocked_code']} {payload['blocked_reasons']}"}
    return {"kc": settings["simc"]["kc"], "ti_s": settings["simc"]["ti_s"],
            "tau_c_s": payload["tau_c_s"], "direct": bool(payload["invert_control"]),
            "delay_used_s": delay_used_s}


def run_one(kind: str, spec: object, seed: int, round_no: int = 1) -> dict:
    """Identify, tune and judge one record; returns the JSON row."""
    started = time.perf_counter()
    record = make_record(kind, spec, seed)
    fit = identify_ipdt(record.t_s, record.out, record.pv)
    row = {"kind": kind, "seed": seed, "cell": record.meta["cell"], "meta": record.meta,
           "plant": record.plant, "n_samples": len(record.t_s), **fit_summary(fit, record.plant)}
    row["accepted"] = fit.verdict in ACCEPTED
    if round_no == 1:
        row["pi"] = (proposed_pi(fit.model.slope_per_s, fit.model.delay_s)
                     if row["accepted"] else None)
    else:
        product = product_pi(record, fit)
        row |= interval_summary(fit, record.plant)
        row["payload_model"] = product["payload_model"]
        row["pi"] = product["pi"] if row["accepted"] else None
    row["loop"] = None
    if row["pi"] is not None and "error" not in row["pi"]:
        band = gen28.DEADBAND if kind == "valve" else 0.0
        row["loop"] = closed_loop(record.plant, row["pi"], band)
    row["looks_integrating"] = (looks_integrating(record)
                                if kind in LOOKS_INTEGRATING_KINDS else None)
    row["runtime_s"] = time.perf_counter() - started
    return row


def share(rows: list[dict], test) -> float | None:
    """Share of rows passing ``test``; None for no rows."""
    return sum(1 for r in rows if test(r)) / len(rows) if rows else None


def _verdict(passed: bool | None) -> str:
    """PASS / MISS / NOT EXERCISED."""
    return "NOT EXERCISED" if passed is None else ("PASS" if passed else "MISS")


def criterion_i1(rows: list[dict]) -> dict:
    """Accepted share of good runs and the accurate share among accepted."""
    good = [r for r in rows if r["kind"] == "good"]
    accepted = [r for r in good if r["accepted"]]
    acc_share = share(good, lambda r: r["accepted"])
    ok_share = share(accepted, lambda r: r["accurate"])
    passed = None if not good else (acc_share >= I1_ACCEPT and (ok_share or 0.0) >= I1_ACCURATE)
    return {"accepted_share": acc_share, "accurate_share_of_accepted": ok_share,
            "n_good": len(good), "n_accepted": len(accepted), "verdict": _verdict(passed)}


def criterion_i2(rows: list[dict]) -> dict:
    """Blocked share per bad kind and the verdict-ok share over all bad runs."""
    bad = [r for r in rows if r["kind"] in gen28.BAD_KINDS]
    blocked = {k: share([r for r in bad if r["kind"] == k], lambda r: r["verdict"] == "blocked")
               for k in gen28.BAD_KINDS}
    ok_share = share(bad, lambda r: r["verdict"] == "ok")
    passed = None if not bad else (all(v is not None and v >= I2_BLOCKED for v in blocked.values())
                                   and ok_share <= I2_OK)
    return {"blocked_share": blocked, "ok_share_all_bad": ok_share, "n_bad": len(bad),
            "verdict": _verdict(passed)}


def criterion_i3(rows: list[dict]) -> dict:
    """Every accepted good-cell fit must give a settled, non-oscillating PI on the true plant."""
    judged = [r for r in rows if r["kind"] == "good" and r["accepted"]]
    unsafe = [f"{r['cell']} seed {r['seed']}" for r in judged
              if r["loop"] is None or not r["loop"]["safe"]]
    passed = None if not judged else not unsafe
    return {"n_judged": len(judged), "unsafe": unsafe, "verdict": _verdict(passed)}


def criterion_i4(rows: list[dict]) -> dict:
    """looks_integrating fire share on good runs; false-warning share on B1+B2 (pooled)."""
    good = [r for r in rows if r["kind"] == "good"]
    fopdt = [r for r in rows if r["kind"] in ("B1", "B2")]
    fires = share(good, lambda r: r["looks_integrating"]["fires"])
    false = share(fopdt, lambda r: r["looks_integrating"]["fires"])
    per_kind = {k: share([r for r in fopdt if r["kind"] == k],
                         lambda r: r["looks_integrating"]["fires"]) for k in ("B1", "B2")}
    passed = None if not good or not fopdt else (fires >= I4_FIRE and false <= I4_FALSE)
    return {"fire_share_good": fires, "false_share_b1_b2": false, "false_share_per_kind": per_kind,
            "verdict": _verdict(passed)}


def criteria(rows: list[dict]) -> dict:
    """I1..I4 values and verdicts."""
    return {"I1": criterion_i1(rows), "I2": criterion_i2(rows), "I3": criterion_i3(rows),
            "I4": criterion_i4(rows)}


def criterion_j2(rows: list[dict]) -> dict:
    """Share of accepted good runs whose true theta lies in [delay_lower_s, delay_upper_s]."""
    accepted = [r for r in rows if r["kind"] == "good" and r["accepted"]]
    covered = share(accepted, lambda r: r["theta_covered"])
    missed = [f"{r['cell']} seed {r['seed']}" for r in accepted if not r["theta_covered"]]
    passed = None if covered is None else covered >= J2_COVER
    return {"covered_share": covered, "n_accepted": len(accepted), "missed": missed,
            "verdict": _verdict(passed)}


def criterion_j3(rows: list[dict]) -> dict:
    """Blocked share per bad kind (as I2) and the accepted share of good runs."""
    i1, i2 = criterion_i1(rows), criterion_i2(rows)
    blocked, accepted = i2["blocked_share"], i1["accepted_share"]
    passed = None if not i2["n_bad"] or accepted is None else (
        all(v is not None and v >= J3_BLOCKED for v in blocked.values()) and accepted >= J3_ACCEPT)
    return {"blocked_share": blocked, "accepted_share": accepted, "n_good": i1["n_good"],
            "n_accepted": i1["n_accepted"], "verdict": _verdict(passed)}


def criterion_j4(rows: list[dict]) -> dict:
    """Median overshoot of the proposed PI over the judged good runs."""
    over = [r["loop"]["overshoot"] for r in rows if r["kind"] == "good" and r["loop"]]
    median = _median(over)
    passed = None if median is None else median <= J4_OVERSHOOT
    return {"median_overshoot": median, "n_judged": len(over), "verdict": _verdict(passed)}


def criteria_round2(rows: list[dict]) -> dict:
    """J1..J4 values and verdicts (J1 is judged exactly as I3, on the product PI)."""
    return {"J1": criterion_i3(rows), "J2": criterion_j2(rows), "J3": criterion_j3(rows),
            "J4": criterion_j4(rows)}


def run(seeds: str, out_dir: Path, round_no: int = 1) -> dict:
    """Run every planned record, write <seeds><suffix>_runs.json and .md, return the payload."""
    if round_no == 2:
        require_round2_api()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{seeds}{ROUNDS[round_no].suffix}"
    json_path, md_path = out_dir / f"{stem}_runs.json", out_dir / f"{stem}.md"
    for path in (json_path, md_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite {path}")
    started = time.perf_counter()
    rows = run_rows(plan(seeds, round_no), round_no)
    crit = criteria(rows) if round_no == 1 else criteria_round2(rows)
    payload = {"seeds": seeds, "round": round_no, "criteria": crit, "runs": rows,
               "runtime_s": time.perf_counter() - started}
    json_path.write_text(json.dumps(payload, indent=1, default=_json_default), encoding="utf-8")
    md_path.write_text(render(payload), encoding="utf-8")
    return payload


def run_rows(runs: list[tuple[str, object, int]], round_no: int = 1) -> list[dict]:
    """run_one over the plan with progress on stderr."""
    rows = []
    for i, (kind, spec, seed) in enumerate(runs):
        rows.append(run_one(kind, spec, seed, round_no))
        if i % 12 == 0:
            print(f"[exp28] {i + 1}/{len(runs)} {kind} seed {seed}", file=sys.stderr)
    return rows


def _json_default(value: object) -> object:
    """JSON encoder for numpy scalars and infinities left in rows."""
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"not JSON serialisable: {type(value)}")


def _fmt(value: float | None, digits: int = 3) -> str:
    """Table cell of a number or a dash."""
    return "-" if value is None else f"{value:.{digits}f}"


def _median(values: list[float]) -> float | None:
    """Median or None for an empty list."""
    return float(np.median(values)) if values else None


def cell_table(rows: list[dict], kind: str) -> list[str]:
    """Per-cell markdown table for good or valve runs."""
    lines = ["| cell | runs | ok | low_conf | blocked | median rel k err | median theta err [s] "
             "| accurate | PI safe / judged | max overshoot | looks_integrating |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["kind"] == kind:
            groups[r["cell"]].append(r)
    for cell, group in groups.items():
        lines.append(_cell_line(cell, group))
    return lines


def _cell_line(cell: str, group: list[dict]) -> str:
    """One row of the per-cell table."""
    verdicts = Counter(r["verdict"] for r in group)
    accepted = [r for r in group if r["accepted"]]
    judged = [r for r in accepted if r["loop"] is not None]
    over = max((r["loop"]["overshoot"] for r in judged), default=None)
    fires = [r for r in group if r["looks_integrating"] and r["looks_integrating"]["fires"]]
    li = f"{len(fires)}/{len(group)}" if group[0]["looks_integrating"] is not None else "-"
    return (f"| {cell} | {len(group)} | {verdicts['ok']} | {verdicts['low_confidence']} | "
            f"{verdicts['blocked']} | {_fmt(_median([r['rel_k_err'] for r in accepted]))} | "
            f"{_fmt(_median([r['theta_err'] for r in accepted]), 1)} | "
            f"{sum(r['accurate'] for r in accepted)}/{len(accepted)} | "
            f"{sum(r['loop']['safe'] for r in judged)}/{len(judged)} | {_fmt(over)} | {li} |")


def bad_table(rows: list[dict]) -> list[str]:
    """Per bad kind: runs, verdict counts, false looks_integrating."""
    lines = ["| kind | runs | ok | low_conf | blocked | looks_integrating |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for kind in gen28.BAD_KINDS:
        group = [r for r in rows if r["kind"] == kind]
        if not group:
            continue
        v = Counter(r["verdict"] for r in group)
        fires = sum(1 for r in group if r["looks_integrating"] and r["looks_integrating"]["fires"])
        li = f"{fires}/{len(group)}" if group[0]["looks_integrating"] is not None else "-"
        lines.append(f"| {kind} | {len(group)} | {v['ok']} | {v['low_confidence']} | "
                     f"{v['blocked']} | {li} |")
    return lines


def reason_histogram(rows: list[dict]) -> list[str]:
    """Count of each reason code per run kind (refusal and low-confidence codes)."""
    lines = ["| kind | reason | runs |", "| --- | --- | ---: |"]
    for kind in ("good", "valve", *gen28.BAD_KINDS):
        counts = Counter(c for r in rows if r["kind"] == kind for c in r["reasons"])
        lines += [f"| {kind} | {code} | {n} |" for code, n in counts.most_common()]
    return lines


def criteria_lines(crit: dict) -> list[str]:
    """Markdown rows of the I1..I4 table."""
    i1, i2, i3, i4 = crit["I1"], crit["I2"], crit["I3"], crit["I4"]
    blocked = ", ".join(f"{k} {_fmt(v)}" for k, v in i2["blocked_share"].items())
    return [
        "| id | values | verdict |", "| --- | --- | --- |",
        f"| I1 | accepted {_fmt(i1['accepted_share'])} ({i1['n_accepted']}/{i1['n_good']}); "
        f"accurate among accepted {_fmt(i1['accurate_share_of_accepted'])} | {i1['verdict']} |",
        f"| I2 | blocked {blocked}; ok over all bad {_fmt(i2['ok_share_all_bad'])} "
        f"| {i2['verdict']} |",
        f"| I3 | judged {i3['n_judged']}, unsafe {len(i3['unsafe'])} | {i3['verdict']} |",
        f"| I4 | fires on good {_fmt(i4['fire_share_good'])}; false on B1+B2 "
        f"{_fmt(i4['false_share_b1_b2'])} | {i4['verdict']} |",
    ]


def summary_lines(rows: list[dict]) -> list[str]:
    """Reported-only figures: low_confidence share, overshoot, bad accepted fits on their plant."""
    good = [r for r in rows if r["kind"] == "good"]
    over = [r["loop"]["overshoot"] for r in good if r["loop"]]
    bad_acc = [r for r in rows if r["kind"] in gen28.BAD_KINDS and r["loop"]]
    low = share(good, lambda r: r["verdict"] == "low_confidence")
    lines = [f"- low_confidence share of good runs: {_fmt(low)}",
             f"- overshoot of the proposed PI (good, judged): median {_fmt(_median(over))}, "
             f"max {_fmt(max(over, default=None))}"]
    lines += [f"- bad accepted {r['kind']} {r['cell']} seed {r['seed']}: safe on its true plant "
              f"{r['loop']['safe']}" for r in bad_acc]
    return lines


def criteria_lines_round2(crit: dict) -> list[str]:
    """Markdown rows of the J1..J4 table."""
    j1, j2, j3, j4 = crit["J1"], crit["J2"], crit["J3"], crit["J4"]
    blocked = ", ".join(f"{k} {_fmt(v)}" for k, v in j3["blocked_share"].items())
    return [
        "| id | values | verdict |", "| --- | --- | --- |",
        f"| J1 | judged {j1['n_judged']}, unsafe {len(j1['unsafe'])} | {j1['verdict']} |",
        f"| J2 | true theta in [delay_lower_s, delay_upper_s]: {_fmt(j2['covered_share'])} "
        f"of {j2['n_accepted']} accepted good runs | {j2['verdict']} |",
        f"| J3 | blocked {blocked}; accepted good {_fmt(j3['accepted_share'])} "
        f"({j3['n_accepted']}/{j3['n_good']}) | {j3['verdict']} |",
        f"| J4 | median overshoot {_fmt(j4['median_overshoot'])} over {j4['n_judged']} judged "
        f"good runs | {j4['verdict']} |",
    ]


def interval_table(rows: list[dict]) -> list[str]:
    """Round 2, good cells: dead-time point estimate, interval, value used and coverage."""
    lines = ["| cell | accepted | covered | median theta_hat | median lower | median upper "
             "| median used |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["kind"] == "good" and r["accepted"]:
            groups[r["cell"]].append(r)
    for cell, g in groups.items():
        med = [_fmt(_median([r[key] for r in g]), 1)
               for key in ("theta_hat", "theta_lower", "theta_upper")]
        used = _fmt(_median([r["payload_model"]["delay_used_s"] for r in g]), 1)
        lines.append(f"| {cell} | {len(g)} | {sum(r['theta_covered'] for r in g)} | "
                     f"{' | '.join(med)} | {used} |")
    return lines


def _criteria_parts(payload: dict) -> list[str]:
    """Criteria section of the report for round 1 (I1..I4) or round 2 (J1..J4)."""
    crit = payload["criteria"]
    if payload.get("round", 1) == 1:
        unsafe = crit["I3"]["unsafe"] or ["none"]
        per_kind = crit["I4"]["false_share_per_kind"].items()
        return ["## Criteria\n", *criteria_lines(crit),
                "\nI4 false warnings are pooled over B1 and B2; per kind: "
                + ", ".join(f"{k} {_fmt(v)}" for k, v in per_kind),
                "\n### I3 unsafe runs\n", *[f"- {u}" for u in unsafe]]
    unsafe, missed = crit["J1"]["unsafe"] or ["none"], crit["J2"]["missed"] or ["none"]
    return ["## Criteria (round 2)\n", *criteria_lines_round2(crit),
            "\n### J1 unsafe runs\n", *[f"- {u}" for u in unsafe],
            "\n### J2 runs with the true theta outside the interval\n", *[f"- {m}" for m in missed],
            "\n## Dead-time interval (good cells, accepted)\n", *interval_table(payload["runs"])]


def render(payload: dict) -> str:
    """Markdown report of one seed set."""
    rows = payload["runs"]
    title = "" if payload.get("round", 1) == 1 else " (round 2)"
    parts = [f"# exp28 results: {payload['seeds']} seeds{title}\n",
             f"Runs: {len(rows)}; runtime {payload['runtime_s']:.0f} s. Dev seeds are a harness "
             "check only (one run per good cell); the frozen criteria apply to the test seeds.\n",
             *_criteria_parts(payload),
             "\n## Reported (no target)\n", *summary_lines(rows),
             "\n## Good cells\n", *cell_table(rows, "good"),
             "\n## Valve-deadband cells (report only; PI judged with the deadband)\n",
             *cell_table(rows, "valve"), "\n## Bad records\n", *bad_table(rows),
             "\n## Reason codes\n", *reason_histogram(rows)]
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI: --seeds dev|test --round 1|2 --out DIR (relative to this folder)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", choices=("dev", "test"), required=True)
    parser.add_argument("--round", type=int, choices=sorted(ROUNDS), default=1,
                        help="frozen protocol round (seeds, criteria, file names)")
    parser.add_argument("--out", default="results", help="output folder, relative to exp28")
    args = parser.parse_args(argv)
    out = Path(args.out) if Path(args.out).is_absolute() else HERE / args.out
    payload = run(args.seeds, out, args.round)
    print(render(payload).split("## Reported")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
