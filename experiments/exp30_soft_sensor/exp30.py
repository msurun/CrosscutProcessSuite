"""exp30 harness: PLS soft sensor for a lab quality variable on 21-day mill-circuit records.

Runs the FROZEN protocol of README.md: per seed one record (scenario cycled normal, regime,
drift), fit on the lab results available before day 14, run the module causally over the record,
judge S1..S4 and the reported items. Writes results/<seeds>_runs.json and results/<seeds>.md;
never overwrites them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from crosscut_softsensor import pls
from crosscut_softsensor.bias import BiasTracker
from crosscut_softsensor.config import load_config
from crosscut_softsensor.features import build_lagged, lag_samples
from crosscut_softsensor.runner import (
    LabResults,
    carry_forward_baseline,
    evaluate_rmse,
    run_softsensor,
)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen30  # noqa: E402

CONFIG = load_config({
    "schema_version": "1.0.0", "id": "exp30", "target_tag": "exp30.quality",
    "input_tags": list(gen30.INPUT_TAGS), "lags_s": [0, 300, 900, 1800],
    "lab_delay_s": gen30.LAB_DELAY_S, "sample_period_s": gen30.ROW_PERIOD_S,
    "max_components": 8, "cv_blocks": 5, "mode": "advisory",
})
# Drift rule: EWMA weight 0.3, 3 consecutive; k_sigma 3.0 since development round 1 (README).
BIAS_WEIGHT, BIAS_K_SIGMA, BIAS_CONSECUTIVE = 0.3, 3.0, 3
DEV_SEEDS = range(29401, 29441)  # harness check only
TEST_SEEDS = range(29501, 29601)  # run once
S1_GAIN, S1_SHARE = 0.20, 0.80
S2_FLAGGED, S2_OK = 0.90, 0.90
S3_DETECT, S3_FALSE = 0.80, 0.10
S3_LEAD_S, S3_WINDOW_S = 3 * gen30.DAY_S, 24 * gen30.HOUR_S
FLAGS = ("out_of_range", "extrapolation")
VALIDITY = ("ok", "missing_input", "out_of_range", "extrapolation")


def plan(seeds: str) -> list[tuple[int, str]]:
    """(seed, scenario) for 'dev' or 'test'; scenarios cycle over the position in the range."""
    rng = DEV_SEEDS if seeds == "dev" else TEST_SEEDS
    return [(s, gen30.scenario_of(s - rng.start)) for s in rng]


def lab_results(rec: gen30.Record) -> LabResults:
    """All lab results of the record, available lab_delay_s after their sample time."""
    return LabResults.with_delay(rec.lab_t_s, rec.lab_values, CONFIG.lab_delay_s)


def without_after(labs: LabResults, cut_s: float) -> LabResults:
    """The lab results available before the cut only (S4: later values removed)."""
    keep = labs.available_s < cut_s
    return LabResults(labs.t_s[keep], labs.values[keep], labs.available_s[keep])


def training_target(t_s: np.ndarray, labs: LabResults, cut_s: float) -> np.ndarray:
    """Target vector: the lab value at its sample row if available before the cut, else NaN."""
    y = np.full(len(t_s), np.nan)
    use = labs.available_s < cut_s
    rows = np.searchsorted(t_s, labs.t_s[use])
    if not np.array_equal(t_s[rows], labs.t_s[use]):
        raise ValueError("lab sample times must be row times")
    y[rows] = labs.values[use]
    return y


def features(columns: dict[str, np.ndarray]) -> np.ndarray:
    """Lagged module inputs (P80 is not among them)."""
    x, _ = build_lagged(columns, CONFIG.input_tags, CONFIG.lags_s, CONFIG.sample_period_s)
    return x


def fit_recording_split(
    x: np.ndarray, y: np.ndarray, x_domain: np.ndarray
) -> tuple[pls.PlsModel, dict]:
    """fit_pls with the module's cv_split wrapped to record its gap and folds.

    ``x_domain``: every lagged-feature row of the training window (labelled or not); the module
    drops rows with NaN and derives its validity limits from the rest.
    """
    seen: dict = {}
    original = pls.cv_split

    def spy(idx: np.ndarray, n_blocks: int, gap: int) -> list:
        seen.update(idx=idx, gap=gap, splits=original(idx, n_blocks, gap))
        return seen["splits"]

    pls.cv_split = spy
    try:
        model = pls.fit_pls(x, y, CONFIG, x_domain=x_domain)
    finally:
        pls.cv_split = original
    return model, seen


def gap_check(model: pls.PlsModel, seen: dict) -> dict:
    """CV gap passed to cv_split equals the longest lag in samples, and the folds honour it."""
    longest = max(lag_samples(model.lag_s, model.sample_period_s))
    idx, distances = seen["idx"], []
    for train, val in seen["splits"]:
        lo, hi = idx[val[0]], idx[val[-1]]
        tr = idx[train]
        distances.append(int(np.min(np.where(tr < lo, lo - tr, tr - hi))))
    return {"gap": int(seen["gap"]), "longest_lag_samples": int(longest),
            "min_train_distance": min(distances),
            "ok": int(seen["gap"]) == longest and min(distances) > longest}


def same_coefficients(a: pls.PlsModel, b: pls.PlsModel) -> bool:
    """Bit-identical coefficients, intercept and component count."""
    return (np.array_equal(a.beta, b.beta) and a.intercept == b.intercept
            and a.n_components == b.n_components)


def s4_check(rec: gen30.Record, labs: LabResults, cut_s: float, model: pls.PlsModel) -> dict:
    """Refit with the post-cut lab values removed (and, reported, with the record truncated)."""
    x = features(rec.columns())
    y_removed = training_target(rec.t_s, without_after(labs, cut_s), cut_s)
    head = rec.t_s < cut_s
    removed, _ = fit_recording_split(x, y_removed, x[head])
    trunc_cols = {k: v[head] for k, v in rec.columns().items()}
    x_trunc = features(trunc_cols)
    truncated, _ = fit_recording_split(x_trunc, y_removed[head], x_trunc)
    return {"identical": same_coefficients(model, removed),
            "identical_sha": model.sha256() == removed.sha256(),
            "identical_truncated": same_coefficients(model, truncated)}


def tracker(model: pls.PlsModel) -> BiasTracker:
    """Bias tracker with the frozen settings (EWMA 0.3, 2 CV sigma, 3 consecutive)."""
    return BiasTracker(model.cv_sigma, BIAS_WEIGHT, BIAS_K_SIGMA, BIAS_CONSECUTIVE)


def accuracy(rec: gen30.Record, run, baseline: np.ndarray, mask: np.ndarray) -> dict:
    """RMSE of estimate, corrected estimate and carry-forward against the truth; R2."""
    common = mask & np.isfinite(run.estimate) & np.isfinite(baseline)
    truth = rec.truth[common]
    rmse_est = evaluate_rmse(run.estimate, rec.truth, common)
    sst = float(np.mean((truth - truth.mean()) ** 2)) if common.any() else float("nan")
    return {"rmse": rmse_est, "rmse_corrected": evaluate_rmse(run.corrected, rec.truth, common),
            "rmse_baseline": evaluate_rmse(baseline, rec.truth, common),
            "r2": 1.0 - rmse_est**2 / sst, "n_rows": int(common.sum())}


def validity_summary(rec: gen30.Record, run, eval_rows: np.ndarray, cut_s: float) -> dict:
    """Validity counts on the evaluation rows; S2 counts against the training hardness range."""
    flags = np.asarray(run.validity)
    train_h = rec.hardness[rec.t_s < cut_s]
    outside = eval_rows & ((rec.hardness < train_h.min()) | (rec.hardness > train_h.max()))
    inside = eval_rows & ~outside
    return {
        "counts": {v: int(np.sum(flags[eval_rows] == v)) for v in VALIDITY},
        "n_outside": int(outside.sum()),
        "n_outside_flagged": int(np.isin(flags[outside], FLAGS).sum()),
        "n_inside": int(inside.sum()),
        "n_inside_ok": int(np.sum(flags[inside] == "ok")),
        "train_hardness": [float(train_h.min()), float(train_h.max())],
    }


def drift_summary(rec: gen30.Record, run, labs: LabResults, durations: gen30.Durations) -> dict:
    """First drift flag after the cut and after the drift onset; S3 deadline and verdict."""
    onset = durations.drift_start_d * gen30.DAY_S
    cut = durations.cut_d * gen30.DAY_S
    lead = labs.available_s[np.flatnonzero(labs.t_s >= onset + S3_LEAD_S)]
    deadline = float(lead[0]) + S3_WINDOW_S if len(lead) else float("nan")
    first_cut = _first(rec.t_s, run.drift & (rec.t_s >= cut))
    first_on = _first(rec.t_s, run.drift & (rec.t_s >= onset))
    return {
        "onset_s": onset, "deadline_s": deadline,
        "first_after_cut_s": first_cut, "first_after_onset_s": first_on,
        "delay_h": None if first_on is None else (first_on - onset) / gen30.HOUR_S,
        "detected": first_on is not None and first_on <= deadline,
        "raised_after_cut": first_cut is not None,
        "raised_before_onset": first_cut is not None and first_cut < onset,
    }


def _first(t_s: np.ndarray, mask: np.ndarray) -> float | None:
    """Time of the first True row, or None."""
    hits = np.flatnonzero(mask)
    return float(t_s[hits[0]]) if len(hits) else None


def regime_window(rec: gen30.Record) -> np.ndarray | None:
    """Rows of the hardness regime (regime records only)."""
    spec = rec.meta.get("regime")
    if spec is None:
        return None
    return (rec.t_s >= spec["start_s"]) & (rec.t_s < spec["end_s"])


def evaluate(rec: gen30.Record, model: pls.PlsModel, durations: gen30.Durations) -> dict:
    """Run the module causally over the record and summarise the evaluation period."""
    cut = durations.cut_d * gen30.DAY_S
    labs = lab_results(rec)
    tr = tracker(model)
    run = run_softsensor(model, CONFIG, rec.t_s, rec.columns(), labs, tr)
    baseline = carry_forward_baseline(rec.t_s, labs)
    eval_rows = rec.t_s >= cut
    out = {"accuracy": accuracy(rec, run, baseline, eval_rows),
           "validity": validity_summary(rec, run, eval_rows, cut),
           "drift": drift_summary(rec, run, labs, durations), "n_lab_used": run.n_lab_used}
    out["drift"]["threshold"] = tr.threshold  # the tracker's |EWMA bias| limit
    window = regime_window(rec)
    if window is not None:
        out["accuracy_regime_window"] = accuracy(rec, run, baseline, window)
    return out


def model_summary(model: pls.PlsModel, gap: dict) -> dict:
    """Component choice, CV RMSE, limits and the CV gap check."""
    return {"n_components": model.n_components, "chosen": model.chosen_components,
            "cv_rmse": list(model.cv_rmse), "cv_sigma": model.cv_sigma, "n_train": model.n_train,
            "t2_limit": model.t2_limit, "spe_limit": model.spe_limit, "gap": gap,
            "sha256": model.sha256()}


def run_one(seed: int, scenario: str, durations: gen30.Durations = gen30.PROTOCOL) -> dict:
    """Generate, fit, check S4 and evaluate one seed; the JSON row."""
    started = time.perf_counter()
    rec = gen30.record(seed, scenario, durations)
    cut = durations.cut_d * gen30.DAY_S
    labs = lab_results(rec)
    x = features(rec.columns())
    model, seen = fit_recording_split(x, training_target(rec.t_s, labs, cut), x[rec.t_s < cut])
    row = {"seed": seed, "scenario": scenario, "meta": rec.meta,
           "model": model_summary(model, gap_check(model, seen)),
           "s4": s4_check(rec, labs, cut, model)}
    row.update(evaluate(rec, model, durations))
    row["runtime_s"] = time.perf_counter() - started
    return row


def _run_job(job: tuple) -> dict:
    """Process-pool entry: unpack one planned run."""
    return run_one(*job)


def run_rows(jobs: list[tuple], workers: int) -> list[dict]:
    """run_one over the plan (in a process pool when workers > 1), rows in plan order."""
    if workers <= 1:
        return [_run_job(job) for job in jobs]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, row in enumerate(pool.map(_run_job, jobs)):
            rows.append(row)
            print(f"[exp30] {i + 1}/{len(jobs)} seed {row['seed']}", file=sys.stderr)
    return rows


def _verdict(passed: bool | None) -> str:
    """PASS / MISS / NOT EXERCISED."""
    return "NOT EXERCISED" if passed is None else ("PASS" if passed else "MISS")


def _share(values: list[bool]) -> float | None:
    """Share of True; None for no values."""
    return sum(values) / len(values) if values else None


def _ratio(num: int, den: int) -> float | None:
    """num / den or None for den 0."""
    return num / den if den else None


def of(rows: list[dict], scenario: str) -> list[dict]:
    """Rows of one scenario."""
    return [r for r in rows if r["scenario"] == scenario]


def criterion_s1(rows: list[dict]) -> dict:
    """Normal records with an RMSE at least 20 % below the carry-forward baseline."""
    acc = [r["accuracy"] for r in of(rows, "normal")]
    hits = [a["rmse"] <= (1.0 - S1_GAIN) * a["rmse_baseline"] for a in acc]
    value = _share(hits)
    return {"n": len(hits), "hits": sum(hits), "share": value,
            "verdict": _verdict(None if value is None else value >= S1_SHARE)}


def criterion_s2(rows: list[dict]) -> dict:
    """Pooled flagged share outside the hardness range (regime) and ok share inside (normal)."""
    reg = [r["validity"] for r in of(rows, "regime")]
    nor = [r["validity"] for r in of(rows, "normal")]
    flagged = _ratio(sum(v["n_outside_flagged"] for v in reg), sum(v["n_outside"] for v in reg))
    ok = _ratio(sum(v["n_inside_ok"] for v in nor), sum(v["n_inside"] for v in nor))
    passed = None if flagged is None or ok is None else flagged >= S2_FLAGGED and ok >= S2_OK
    return {"outside_rows": sum(v["n_outside"] for v in reg), "flagged_share": flagged,
            "inside_rows": sum(v["n_inside"] for v in nor), "ok_share": ok,
            "verdict": _verdict(passed)}


def criterion_s3(rows: list[dict]) -> dict:
    """Drift detected by the deadline on drift records; any flag after the cut on normal ones."""
    det = [r["drift"]["detected"] for r in of(rows, "drift")]
    false = [r["drift"]["raised_after_cut"] for r in of(rows, "normal")]
    d, f = _share(det), _share(false)
    passed = None if d is None or f is None else d >= S3_DETECT and f <= S3_FALSE
    return {"n_drift": len(det), "detected": sum(det), "detect_share": d,
            "n_normal": len(false), "false": sum(false), "false_share": f,
            "verdict": _verdict(passed)}


def criterion_s4(rows: list[dict]) -> dict:
    """Identical coefficients without the post-cut labs and the CV gap check, every record."""
    same = [r["s4"]["identical"] for r in rows]
    gap = [r["model"]["gap"]["ok"] for r in rows]
    return {"n": len(rows), "identical": sum(same), "gap_ok": sum(gap),
            "identical_truncated": sum(r["s4"]["identical_truncated"] for r in rows),
            "verdict": _verdict(all(same) and all(gap) if rows else None)}


def criteria(rows: list[dict]) -> dict:
    """S1..S4 values and verdicts."""
    return {"S1": criterion_s1(rows), "S2": criterion_s2(rows),
            "S3": criterion_s3(rows), "S4": criterion_s4(rows)}


def _mean(values: list) -> float | None:
    """Mean of the non-None values or None."""
    vals = [v for v in values if v is not None]
    return float(np.mean(vals)) if vals else None


def scenario_report(rows: list[dict]) -> dict:
    """RMSE, R2, baseline, validity shares and components of one scenario's rows."""
    acc = [r["accuracy"] for r in rows]
    counts = {v: sum(r["validity"]["counts"][v] for r in rows) for v in VALIDITY}
    total = sum(counts.values())
    return {
        "n": len(rows),
        "rmse": _mean([a["rmse"] for a in acc]),
        "rmse_corrected": _mean([a["rmse_corrected"] for a in acc]),
        "rmse_baseline": _mean([a["rmse_baseline"] for a in acc]),
        "r2": _mean([a["r2"] for a in acc]),
        "beats_baseline": sum(a["rmse"] < a["rmse_baseline"] for a in acc),
        "validity_share": {v: _ratio(c, total) for v, c in counts.items()},
        "components": sorted({r["model"]["n_components"] for r in rows}),
    }


def reported(rows: list[dict]) -> dict:
    """No-target figures per scenario plus drift delays and the regime-window comparison."""
    per = {s: scenario_report(of(rows, s)) for s in gen30.SCENARIOS}
    windows = [r["accuracy_regime_window"] for r in of(rows, "regime")]
    delays = [r["drift"]["delay_h"] for r in of(rows, "drift") if r["drift"]["delay_h"] is not None]
    return {
        "per_scenario": per,
        "regime_window_rmse": _mean([w["rmse"] for w in windows]),
        "regime_window_rmse_baseline": _mean([w["rmse_baseline"] for w in windows]),
        "drift_delays_h": delays,
        "drift_pre_onset": sum(r["drift"]["raised_before_onset"] for r in of(rows, "drift")),
        "components_per_seed": {r["seed"]: r["model"]["n_components"] for r in rows},
        "s4_identical_sha": sum(r["s4"]["identical_sha"] for r in rows),
    }


def _fmt(value: float | None, digits: int = 3) -> str:
    """Table cell of a number or a dash."""
    return "-" if value is None else f"{value:.{digits}f}"


def criteria_lines(crit: dict) -> list[str]:
    """Markdown rows of the S1..S4 table."""
    s1, s2, s3, s4 = (crit[k] for k in ("S1", "S2", "S3", "S4"))
    return [
        "| id | values | verdict |", "| --- | --- | --- |",
        f"| S1 | normal records with RMSE >= 20 % below carry-forward: {s1['hits']}/{s1['n']} "
        f"({_fmt(s1['share'])}) | {s1['verdict']} |",
        f"| S2 | regime: {_fmt(s2['flagged_share'])} of {s2['outside_rows']} rows outside the "
        f"training hardness range flagged; normal: {_fmt(s2['ok_share'])} of "
        f"{s2['inside_rows']} rows inside the range ok | {s2['verdict']} |",
        f"| S3 | drift raised by the deadline {s3['detected']}/{s3['n_drift']} "
        f"({_fmt(s3['detect_share'])}); raised on normal records {s3['false']}/{s3['n_normal']} "
        f"({_fmt(s3['false_share'])}) | {s3['verdict']} |",
        f"| S4 | identical coefficients without post-cut labs {s4['identical']}/{s4['n']}; "
        f"CV gap = longest lag {s4['gap_ok']}/{s4['n']} (record truncated at the cut also "
        f"identical {s4['identical_truncated']}/{s4['n']}) | {s4['verdict']} |",
    ]


def reported_lines(rep: dict) -> list[str]:
    """Markdown of the reported items."""
    lines = ["| scenario | records | RMSE | RMSE corrected | RMSE carry-forward | R2 | "
             "beats baseline | ok | out_of_range | extrapolation | components |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for name, s in rep["per_scenario"].items():
        v = s["validity_share"]
        lines.append(
            f"| {name} | {s['n']} | {_fmt(s['rmse'])} | {_fmt(s['rmse_corrected'])} | "
            f"{_fmt(s['rmse_baseline'])} | {_fmt(s['r2'])} | {s['beats_baseline']} | "
            f"{_fmt(v['ok'])} | {_fmt(v['out_of_range'])} | {_fmt(v['extrapolation'])} | "
            f"{s['components']} |")
    delays = [round(d, 1) for d in rep["drift_delays_h"]]
    return lines + [
        f"\n- regime window (24 h) RMSE: estimate {_fmt(rep['regime_window_rmse'])}, "
        f"carry-forward {_fmt(rep['regime_window_rmse_baseline'])} (mean over records)",
        f"- drift records: first drift flag after onset, delay [h]: {delays}",
        f"- drift records flagged between the cut and the onset: {rep['drift_pre_onset']}",
        f"- S4 refit model sha256 identical: {rep['s4_identical_sha']} records",
    ]


def seed_table(rows: list[dict]) -> list[str]:
    """Per-seed markdown table."""
    lines = ["| seed | scenario | A | cv sigma | RMSE | carry-fwd | R2 | ok share | "
             "outside flagged | drift first [d] | detected | S4 |",
             "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |"]
    for r in rows:
        a, v, d = r["accuracy"], r["validity"], r["drift"]
        total = sum(v["counts"].values())
        first = d["first_after_cut_s"]
        lines.append(
            f"| {r['seed']} | {r['scenario']} | {r['model']['n_components']} | "
            f"{_fmt(r['model']['cv_sigma'])} | {_fmt(a['rmse'])} | {_fmt(a['rmse_baseline'])} | "
            f"{_fmt(a['r2'])} | {_fmt(_ratio(v['counts']['ok'], total))} | "
            f"{v['n_outside_flagged']}/{v['n_outside']} | "
            f"{_fmt(None if first is None else first / gen30.DAY_S, 2)} | {d['detected']} | "
            f"{r['s4']['identical'] and r['model']['gap']['ok']} |")
    return lines


def render(payload: dict) -> str:
    """Markdown report of one seed set."""
    rows = payload["runs"]
    note = ("Dev seeds are a harness check only; the frozen criteria apply to the test seeds."
            if payload["seeds"] == "dev" else "Test seeds, run once.")
    parts = [
        f"# exp30 results: {payload['seeds']} seeds\n",
        f"Seeds: {len(rows)}; runtime {payload['runtime_s']:.0f} s. {note}\n",
        "## Criteria\n", *criteria_lines(payload["criteria"]),
        "\n## Reported (no target)\n", *reported_lines(payload["reported"]),
        "\n## Per seed\n", *seed_table(rows),
    ]
    return "\n".join(parts) + "\n"


def _json_default(value: object) -> object:
    """JSON encoder for numpy scalars."""
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"not JSON serialisable: {type(value)}")


def run(seeds: str, out_dir: Path, workers: int = 1, name: str | None = None) -> dict:
    """Run every planned seed, write <name>_runs.json and <name>.md (name defaults to seeds)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = name or seeds
    json_path, md_path = out_dir / f"{stem}_runs.json", out_dir / f"{stem}.md"
    for path in (json_path, md_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite {path}")
    started = time.perf_counter()
    rows = run_rows(plan(seeds), workers)
    payload = {"seeds": seeds, "criteria": criteria(rows), "reported": reported(rows),
               "runs": rows, "runtime_s": time.perf_counter() - started}
    json_path.write_text(json.dumps(payload, indent=1, default=_json_default), encoding="utf-8")
    md_path.write_text(render(payload), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    """CLI: --seeds dev|test --out DIR (relative to this folder) --jobs N [--name STEM]."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", choices=("dev", "test"), required=True)
    parser.add_argument("--out", default="results", help="output folder, relative to exp30")
    parser.add_argument("--name", default=None, help="result file stem (default: --seeds)")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                        help="worker processes (results do not depend on it)")
    args = parser.parse_args(argv)
    out = Path(args.out) if Path(args.out).is_absolute() else HERE / args.out
    payload = run(args.seeds, out, args.jobs, args.name)
    print(render(payload).split("## Per seed")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
