"""exp33 runner: Crosscut loop engines on the public two-tank closed-loop level data (issue #86).

Reads the extracted Zenodo dataset from a folder outside the repo, evaluates the targets frozen in
README.md (D1, S1, M1, I1, I2, A1, A2) and prints markdown tables. Missing data is a clean skip.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from crosscut_loops.history_tuning import tune_from_history
from crosscut_loops.identification_cl import identify_fopdt_closed_loop
from crosscut_loops.monitor import DELAY, OUT_RANGE, LoopSettings, analyze_loop
from crosscut_loops.tuning_review import DEFAULT_THRESHOLDS, WindowData, window_metrics
from crosscut_loops.tuning_rules import PiSettings, convert_pi

DT_S = 1.0
STEP_S = 1800
SAT_LIMIT = 0.2
BAND_FACTOR = 3.0
Q_DAHLIN = 1.0 - np.exp(-DT_S / 3.0)  # Dahlin lambda = 3 s (dataset README)
FORMS = ("gain_seconds", "gain_minutes", "proportional_band_minutes", "gain_repeats_per_minute")

Runs = dict[str, dict[str, np.ndarray]]


def load_runs(folder: Path) -> Runs:
    """Read every CSV under ``folder/Dataset`` into {run name: {column: array}}."""
    runs: Runs = {}
    for path in sorted((folder / "Dataset").glob("*/*.csv")):
        table = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8")
        runs[path.stem] = {
            n: np.asarray(table[n], dtype=float) for n in table.dtype.names if n != "Timestamp"
        }
    return runs


def step_kpis(sp: np.ndarray, pv: np.ndarray, start: int, length: int) -> dict[str, float]:
    """IAE, overshoot (fraction of the step) and 5 % settling time (s) of one setpoint step."""
    sp_old, sp_new = sp[start - 1], sp[start]
    size = sp_new - sp_old
    resp = pv[start : start + length] - sp_old
    err = np.abs(sp_new - pv[start : start + length])
    overshoot = max(0.0, float(np.max(resp * np.sign(size)) / abs(size) - 1.0))
    outside = np.nonzero(err > 0.05 * abs(size))[0]
    settle = float(outside[-1] + 1) * DT_S if outside.size else 0.0
    return {"iae": float(np.sum(err) * DT_S), "overshoot": overshoot, "settle_s": settle}


def check_s1a() -> tuple[bool, str]:
    """S1(a): KPI function on a synthetic first-order lag against the analytic values."""
    tau, amp = 100.0, 5.0
    t = np.arange(STEP_S)
    sp = np.full(STEP_S + 1, 10.0 + amp)
    sp[0] = 10.0
    pv = np.concatenate(([10.0], 10.0 + amp * (1.0 - np.exp(-t / tau))))
    k = step_kpis(sp, pv, 1, STEP_S)
    ok_iae = abs(k["iae"] / (amp * tau) - 1.0) <= 0.01
    ok_settle = abs(k["settle_s"] / (tau * np.log(20.0)) - 1.0) <= 0.01
    text = (f"IAE {k['iae']:.1f} (500), settle {k['settle_s']:.1f} s (299.6), "
            f"os {k['overshoot']:.3f}")
    return ok_iae and ok_settle and k["overshoot"] == 0.0, text


def independent_iae_per_h(sp: np.ndarray, pv: np.ndarray) -> float:
    """Reference: mean |SP-PV| over the n-1 forward intervals, scaled to one hour."""
    return float(np.sum(np.abs(sp - pv)[:-1]) / (len(sp) - 1) * 3600.0)


def saturated_share(out: np.ndarray) -> float:
    """Independent share of samples with the pump command at 0 or 100 %."""
    return float(np.mean((out <= 0.0) | (out >= 100.0)))


def dahlin_kp_agreement(run: dict[str, np.ndarray]) -> float:
    """D1: share of rows 3.. where logged Kp is within 1 % of -(a1 + 2 a2) Q / b1."""
    a1, a2, b1, kp = (run[n][2:] for n in ("a1", "a2", "b1", "Kp"))
    kp_ref = -(a1 + 2.0 * a2) * Q_DAHLIN / b1
    return float(np.mean(np.abs(kp - kp_ref) <= 0.01 * np.abs(kp_ref)))


def logged_tuning(run: dict[str, np.ndarray]) -> tuple[float, float]:
    """Median logged (Kc, Ti in s) over rows 3.. with Kp > 0 and Ki > 0."""
    kp, ki = run["Kp"][2:], run["Ki"][2:]
    good = (kp > 0) & (ki > 0)
    return float(np.median(kp[good])), float(np.median(kp[good] / ki[good]))


def series(run: dict[str, np.ndarray]) -> tuple[np.ndarray, ...]:
    """(t_s, pv, sp, out, mode) of a run; mode is AUTO everywhere."""
    out, pv, sp = run["Control_Signal_pct"], run["Level_pct"], run["Setpoint_pct"]
    return run["Time_s"], pv, sp, out, np.ones(len(out))


def engine_row(name: str, run: dict[str, np.ndarray], settings: LoopSettings) -> dict:
    """S1(b), M1 and step KPIs of one run."""
    t, pv, sp, out, mode = series(run)
    wm = window_metrics(WindowData(t, pv, sp, out, mode), DEFAULT_THRESHOLDS)
    rep = analyze_loop(t, pv, sp, out, mode, settings=settings)
    share = saturated_share(out)
    rel = wm.iae_per_h / independent_iae_per_h(sp, pv) - 1.0
    starts = [i for i in range(1, len(sp)) if sp[i] != sp[i - 1]]
    kpis = [step_kpis(sp, pv, i, STEP_S) for i in starts]
    sat_ok = abs(rep.saturation_fraction - share) <= 0.01
    class_ok = (rep.classification == "saturated") == (share > SAT_LIMIT)
    return {
        "run": name, "share": share, "mon_sat": rep.saturation_fraction,
        "cls": rep.classification, "iae_rel": rel, "s1b": abs(rel) <= 1e-3,
        "m1": sat_ok and class_ok, "steps": len(starts),
        "iae": float(np.median([k["iae"] for k in kpis])),
        "os": float(np.median([k["overshoot"] for k in kpis])),
        "settle": float(np.median([k["settle_s"] for k in kpis])),
    }


def eval_engine_checks(runs: Runs) -> list[dict]:
    """S1(b), M1 and step KPIs for every run."""
    settings = LoopSettings(
        delay_s=2.0, ultimate_period_s=600.0, amplitude_limit=1.0, scan_period_s=DT_S,
        process_kind="integrating", known=frozenset({OUT_RANGE, DELAY}),
    )
    return [engine_row(name, run, settings) for name, run in runs.items()]


def identification_row(name: str, run: dict[str, np.ndarray]) -> dict:
    """I1/I2: closed-loop FOPDT fit of one run; a ValueError is recorded, not hidden."""
    _, pv, sp, out, _ = series(run)
    try:
        m = identify_fopdt_closed_loop(out, pv, sp, DT_S, 20.0)
    except ValueError as exc:
        nan = float("nan")
        return {"run": name, "gain": nan, "tau": nan, "delay": nan, "k": nan, "err": str(exc)[:70]}
    return {"run": name, "gain": m.gain, "tau": m.time_constant_s, "delay": m.delay_s,
            "k": m.gain / m.time_constant_s, "err": ""}


def in_band(a: float, b: float) -> bool:
    """True when a and b differ by at most BAND_FACTOR in either direction."""
    return b / BAND_FACTOR <= a <= b * BAND_FACTOR


def forms_exact(kc: float, ti: float) -> bool:
    """A2: every vendor form of the logged tuning equals its hand formula (rtol 1e-9)."""
    f = {form: convert_pi(PiSettings(kc, ti), form) for form in FORMS}  # type: ignore[arg-type]
    pairs = [
        (f["gain_seconds"]["integral_time_s"], ti),
        (f["gain_minutes"]["integral_time_min"], ti / 60.0),
        (f["proportional_band_minutes"]["proportional_band_pct"], 100.0 / kc),
        (f["gain_repeats_per_minute"]["repeats_per_min"], 60.0 / ti),
    ]
    return all(np.isclose(a, b, rtol=1e-9) for a, b in pairs)


def assessment_row(name: str, run: dict[str, np.ndarray]) -> dict:
    """A1/A2: tune_from_history against the logged tuning, and the vendor-form mapping."""
    _, pv, sp, out, _ = series(run)
    kc, ti = logged_tuning(run)
    res = tune_from_history(name, sp, out, pv, DT_S)
    simc = res.report.simc if res.report else None
    nan = float("nan")
    return {
        "run": name, "status": res.status, "conf": res.confidence, "rec": res.recommendation,
        "used": res.windows_used, "found": res.windows_found, "kc": kc, "ti": ti,
        "simc_kc": simc.kc if simc else nan, "simc_ti": simc.ti_s if simc else nan,
        "band": bool(simc and in_band(kc, simc.kc) and in_band(ti, simc.ti_s)),
        "model": res.model, "a2": forms_exact(kc, ti),
    }


def verdicts(d1: dict, eng: list, ident: list, assess: list) -> list[tuple[str, str, str]]:
    """Per-target (name, MET / NOT MET / NOT EXERCISED, evidence) from the evaluated rows."""
    s1a_ok, s1a_txt = check_s1a()
    ks = np.array([r["k"] for r in ident if r["err"] == ""])
    med = float(np.median(ks)) if ks.size else float("nan")
    k_ok = int(np.sum(np.abs(ks / med - 1.0) <= 0.30)) if ks.size else 0
    d_ok = sum(1 for r in ident if 1.0 <= r["delay"] <= 3.0)
    assessed = [r for r in assess if r["status"] == "ok"]
    band_n = sum(r["band"] for r in assessed)
    if len(assessed) < 3:
        a1 = "NOT EXERCISED"
    else:
        a1 = "MET" if band_n >= 0.8 * len(assessed) else "NOT MET"

    def flag(ok: bool) -> str:
        return "MET" if ok else "NOT MET"

    worst = max(abs(r["iae_rel"]) for r in eng)
    return [
        ("D1", flag(all(v >= 0.9 for v in d1.values())), f"min share {min(d1.values()):.3f}"),
        ("S1a", flag(s1a_ok), s1a_txt),
        ("S1b", flag(all(r["s1b"] for r in eng)), f"max rel diff {worst:.2e}"),
        ("M1", flag(all(r["m1"] for r in eng)), f"{sum(r['m1'] for r in eng)}/{len(eng)} runs"),
        ("I1", flag(len(ks) >= 8 and k_ok >= 8),
         f"identified {len(ks)}/10, within 30% {k_ok}, median k {med:.3g}"),
        ("I2", flag(d_ok >= 8), f"{d_ok}/10 with delay in [1, 3] s"),
        ("A1", a1, f"assessed {len(assessed)}, in band {band_n}"),
        ("A2", flag(all(r["a2"] for r in assess)) if assess else "NOT EXERCISED",
         f"{sum(r['a2'] for r in assess)}/{len(assess)}"),
    ]


def print_tables(eng: list, ident: list, assess: list, verd: list) -> None:
    """Print the markdown used in results.md."""
    print("| target | outcome | evidence |\n|---|---|---|")
    for name, outcome, evidence in verd:
        print(f"| {name} | {outcome} | {evidence} |")
    print("\n| run | sat share | monitor sat | class | iae/h rel | steps | med IAE | med OS | "
          "med settle s |\n|---|---|---|---|---|---|---|---|---|")
    for r in eng:
        print(f"| {r['run']} | {r['share']:.3f} | {r['mon_sat']:.3f} | {r['cls']} | "
              f"{r['iae_rel']:.1e} | {r['steps']} | {r['iae']:.0f} | {r['os']:.3f} | "
              f"{r['settle']:.0f} |")
    print("\n| run | gain | tau s | delay s | k=gain/tau | note |\n|---|---|---|---|---|---|")
    for r in ident:
        print(f"| {r['run']} | {r['gain']:.4g} | {r['tau']:.4g} | {r['delay']:.1f} | "
              f"{r['k']:.3g} | {r['err']} |")
    print("\n| run | status | conf | rec | used/found | logged Kc | logged Ti | SIMC Kc | "
          "SIMC Ti | band | model |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for r in assess:
        print(f"| {r['run']} | {r['status']} | {r['conf']} | {r['rec']} | "
              f"{r['used']}/{r['found']} | {r['kc']:.3g} | {r['ti']:.3g} | {r['simc_kc']:.3g} | "
              f"{r['simc_ti']:.3g} | {r['band']} | {r['model']} |")


def main(argv: list[str]) -> int:
    """Entry point; a missing data folder is a clean skip."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args(argv)
    runs = load_runs(args.data)
    if len(runs) < 25:
        print(f"exp33: {len(runs)} of 25 runs under {args.data}/Dataset; skipped")
        return 0
    base = {k: v for k, v in runs.items() if k.startswith("Baseline")}
    d1 = {k: dahlin_kp_agreement(v) for k, v in base.items()}
    eng = eval_engine_checks(runs)
    ident = [identification_row(k, v) for k, v in base.items()]
    assess = [assessment_row(k, v) for k, v in base.items()] if min(d1.values()) >= 0.9 else []
    print_tables(eng, ident, assess, verdicts(d1, eng, ident, assess))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
