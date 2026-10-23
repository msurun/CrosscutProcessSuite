"""exp29 harness: PCA (T2 / SPE) anomaly detection on mill-circuit records with sensor faults.

Runs the FROZEN protocol of README.md: per seed fit on the 48 h training record, scan the quiet
(72 h) and fault (24 h) records with the frozen `AnomalyConfig` defaults, judge A1..A5 and the
reported items. Writes results/<seeds>_runs.json and results/<seeds>.md; never overwrites them.
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
from crosscut_anomaly.config import AnomalyConfig
from crosscut_anomaly.detect import ScanResult, scan
from crosscut_anomaly.pca_model import PcaModel, fit_pca

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen29  # noqa: E402

CONFIG = AnomalyConfig(schema_version="1.0.0", id="exp29", tags=gen29.TAGS, mode="advisory")
DEV_SEEDS = range(29001, 29061)  # each: training + quiet + fault record (harness check only)
TEST_QUIET_SEEDS = range(29201, 29261)  # each: training + quiet record
TEST_FAULT_SEEDS = range(29301, 29400)  # each: training + fault record
# Detection window after onset, min: A2 drift 180, A3 freeze 60; reported kinds: their 1 h window.
DETECT_WINDOW_MIN = {
    "drift": 180.0,
    "freeze": 60.0,
    "spike": 60.0,
    "bad_quality": 60.0,
    "dropout": 60.0,
}
A1_MEAN, A1_MAX = 1.0, 3.0  # false alarm events per 24 h
A2_SHARE, A3_SHARE, A4_SHARE = 0.80, 0.80, 0.70
TOP_N = 2  # A4: faulty tag among the top 2 contributors
SKIP_KINDS = ("bad_quality", "dropout")  # A5 records
DAY_S = 86400.0


def plan(seeds: str) -> list[tuple[int, bool, int | None]]:
    """(seed, has quiet record, fault index or None) for 'dev' or 'test'."""
    if seeds == "dev":
        return [(s, True, s - DEV_SEEDS.start) for s in DEV_SEEDS]
    return [(s, True, None) for s in TEST_QUIET_SEEDS] + [
        (s, False, s - TEST_FAULT_SEEDS.start) for s in TEST_FAULT_SEEDS
    ]


def fit(train: gen29.Record) -> PcaModel:
    """PCA model on the training rows with the frozen settings."""
    return fit_pca(train.x, CONFIG.tags, CONFIG.variance_fraction, CONFIG.alpha)


def run_scan(model: PcaModel, record: gen29.Record) -> ScanResult:
    """Scan a record with the frozen configuration."""
    return scan(model, record.t_s, record.x, record.quality, CONFIG)


def model_summary(model: PcaModel, train: gen29.Record) -> dict:
    """Rank, limits and the empirical exceedance of the limits on the training rows."""
    t2, spe = model.t2(train.x), model.spe(train.x)
    return {
        "k": model.k,
        "n_train": model.n_train,
        "t2_limit": model.t2_limit,
        "spe_limit": model.spe_limit,
        "train_exc_t2": float(np.mean(t2 > model.t2_limit)),
        "train_exc_spe": float(np.mean(spe > model.spe_limit)),
        "train_exc_any": float(np.mean((t2 > model.t2_limit) | (spe > model.spe_limit))),
        "train_sd": gen29.training_sd(train).tolist(),
    }


def event_dict(event) -> dict:
    """JSON form of an AnomalyEvent."""
    return {
        "start_s": event.start_s,
        "end_s": event.end_s,
        "closed": event.closed,
        "peak_t2": event.peak_t2,
        "peak_spe": event.peak_spe,
        "peak_index": event.peak_index,
        "start_index": event.start_index,
        "end_index": event.end_index,
        "top_spe": list(event.top_spe_tags),
        "top_t2": list(event.top_t2_tags),
        "exceeded": event.exceeded,
        "n_samples": event.n_samples,
    }


def scan_summary(result: ScanResult, record: gen29.Record) -> dict:
    """Events, valid share and skipped counts of one scan."""
    n = len(record.t_s)
    return {
        "n_rows": n,
        "n_valid": result.n_valid,
        "n_skipped": result.n_skipped,
        "skipped_reasons": dict(result.skipped_reasons),
        "valid_share": result.n_valid / n,
        "events": [event_dict(e) for e in result.events],
    }


def quiet_summary(model: PcaModel, record: gen29.Record) -> dict:
    """Quiet record: events and false alarm events per 24 h."""
    summary = scan_summary(run_scan(model, record), record)
    span_s = len(record.t_s) * gen29.ROW_PERIOD_S
    summary["events_per_24h"] = len(summary["events"]) * DAY_S / span_s
    return summary


def dominant(event: dict, model: PcaModel) -> str:
    """Statistic with the larger limit ratio at the event peak: 't2' or 'spe'."""
    return (
        "t2" if event["peak_t2"] / model.t2_limit >= event["peak_spe"] / model.spe_limit else "spe"
    )


def detection(events: list[dict], spec: dict, model: PcaModel) -> dict:
    """First event starting within the kind's window after onset, its delay and contributors."""
    onset, window_s = spec["onset_s"], DETECT_WINDOW_MIN[spec["kind"]] * 60.0
    # Start within the window after onset and overlap with the fault window [onset, end_s).
    hits = [e for e in events if onset <= e["start_s"] <= onset + window_s
            and e["start_s"] <= spec["end_s"] and e["end_s"] >= onset]
    if not hits:
        keys = ("delay_min", "dominant", "top2_hit", "top2_spe_hit", "top2_t2_hit")
        return {"detected": False} | dict.fromkeys(keys)
    first, tag = hits[0], spec["tag"]
    stat = dominant(first, model)
    return {
        "detected": True,
        "delay_min": (first["start_s"] - onset) / 60.0,
        "dominant": stat,
        "top2_hit": tag in first[f"top_{stat}"][:TOP_N],
        "top2_spe_hit": tag in first["top_spe"][:TOP_N],
        "top2_t2_hit": tag in first["top_t2"][:TOP_N],
    }


def removed_rows_check(model: PcaModel, record: gen29.Record, full: ScanResult) -> dict:
    """A5 property: the scan without the invalid rows gives the same events (rows mapped back)."""
    keep = np.flatnonzero(~np.isnan(record.x).any(axis=1) & (record.quality == 0))
    reduced = scan(model, record.t_s[keep], record.x[keep], record.quality[keep], CONFIG)
    same = len(reduced.events) == len(full.events) and all(
        _same_event(a, b, keep) for a, b in zip(full.events, reduced.events, strict=False)
    )
    return {
        "ok": bool(same),
        "n_full": len(full.events),
        "n_removed": len(reduced.events),
        "rows_removed": int(len(record.t_s) - len(keep)),
    }


def _same_event(full_event, reduced_event, keep: np.ndarray) -> bool:
    """Equal times, closure and peak; reduced row indices mapped back through ``keep``."""
    mapped = tuple(
        int(keep[i])
        for i in (reduced_event.start_index, reduced_event.end_index, reduced_event.peak_index)
    )
    return (
        mapped == (full_event.start_index, full_event.end_index, full_event.peak_index)
        and full_event.start_s == reduced_event.start_s
        and full_event.end_s == reduced_event.end_s
        and full_event.closed == reduced_event.closed
        and full_event.n_samples == reduced_event.n_samples
    )


def fault_summary(
    seed: int, index: int, fitted: tuple[PcaModel, np.ndarray], durations: gen29.Durations
) -> dict:
    """Fault record: spec, scan, detection, A5 property, pre-onset events; fitted = (model, sd)."""
    model, sd = fitted
    spec = gen29.fault_spec(seed, index, sd, durations)
    record = gen29.fault_record(seed, spec, durations)
    result = run_scan(model, record)
    summary = scan_summary(result, record) | {"spec": spec}
    summary["detection"] = detection(summary["events"], spec, model)
    summary["a5"] = removed_rows_check(model, record, result)
    summary["pre_onset_events"] = sum(
        1 for e in summary["events"] if e["start_s"] < spec["onset_s"]
    )
    return summary


def run_one(
    seed: int, has_quiet: bool, fault_index: int | None, durations: gen29.Durations = gen29.PROTOCOL
) -> dict:
    """Training fit plus the quiet and/or fault record of one seed; the JSON row."""
    started = time.perf_counter()
    train = gen29.training_record(seed, durations)
    model = fit(train)
    row = {"seed": seed, "model": model_summary(model, train), "quiet": None, "fault": None}
    if has_quiet:
        row["quiet"] = quiet_summary(model, gen29.quiet_record(seed, durations))
    if fault_index is not None:
        sd = np.asarray(row["model"]["train_sd"])
        row["fault"] = fault_summary(seed, fault_index, (model, sd), durations)
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
            print(f"[exp29] {i + 1}/{len(jobs)} seed {row['seed']}", file=sys.stderr)
    return rows


def _verdict(passed: bool | None) -> str:
    """PASS / MISS / NOT EXERCISED."""
    return "NOT EXERCISED" if passed is None else ("PASS" if passed else "MISS")


def _share(values: list[bool]) -> float | None:
    """Share of True; None for no values."""
    return sum(values) / len(values) if values else None


def fault_rows(rows: list[dict], kinds: tuple[str, ...]) -> list[dict]:
    """Fault summaries of the given kinds."""
    return [r["fault"] for r in rows if r["fault"] and r["fault"]["spec"]["kind"] in kinds]


def criterion_a1(rows: list[dict]) -> dict:
    """False alarm events per 24 h on the quiet records: mean and maximum."""
    rates = [r["quiet"]["events_per_24h"] for r in rows if r["quiet"]]
    if not rates:
        return {"n": 0, "mean": None, "max": None, "verdict": _verdict(None)}
    mean, worst = float(np.mean(rates)), float(np.max(rates))
    return {
        "n": len(rates),
        "mean": mean,
        "max": worst,
        "verdict": _verdict(mean <= A1_MEAN and worst <= A1_MAX),
    }


def criterion_detect(rows: list[dict], kind: str, target: float) -> dict:
    """A2 / A3: detected share of the records of one fault kind."""
    hits = [f["detection"]["detected"] for f in fault_rows(rows, (kind,))]
    value = _share(hits)
    return {
        "n": len(hits),
        "detected": sum(hits),
        "share": value,
        "verdict": _verdict(None if value is None else value >= target),
    }


def criterion_a4(rows: list[dict]) -> dict:
    """Faulty tag among the top 2 contributors (dominant statistic) for detected drift/freeze."""
    det = [
        f["detection"] for f in fault_rows(rows, ("drift", "freeze")) if f["detection"]["detected"]
    ]
    value = _share([d["top2_hit"] for d in det])
    return {
        "n": len(det),
        "share": value,
        "share_spe": _share([d["top2_spe_hit"] for d in det]),
        "share_t2": _share([d["top2_t2_hit"] for d in det]),
        "share_either": _share([d["top2_spe_hit"] or d["top2_t2_hit"] for d in det]),
        "verdict": _verdict(None if value is None else value >= A4_SHARE),
    }


def criterion_a5(rows: list[dict]) -> dict:
    """Removed-rows property on every bad_quality and dropout record (100 %)."""
    checks = [f["a5"]["ok"] for f in fault_rows(rows, SKIP_KINDS)]
    others = [f["a5"]["ok"] for f in fault_rows(rows, ("drift", "freeze", "spike"))]
    return {
        "n": len(checks),
        "ok": sum(checks),
        "ok_other_kinds": f"{sum(others)}/{len(others)}",
        "verdict": _verdict(all(checks) if checks else None),
    }


def criteria(rows: list[dict]) -> dict:
    """A1..A5 values and verdicts."""
    return {
        "A1": criterion_a1(rows),
        "A2": criterion_detect(rows, "drift", A2_SHARE),
        "A3": criterion_detect(rows, "freeze", A3_SHARE),
        "A4": criterion_a4(rows),
        "A5": criterion_a5(rows),
    }


def _mean(values: list[float]) -> float | None:
    """Mean or None for an empty list."""
    return float(np.mean(values)) if values else None


def reported(rows: list[dict]) -> dict:
    """No-target figures: per-kind detection, training exceedance, valid share, k per seed."""
    per_kind = {}
    for kind in gen29.FAULT_KINDS:
        det = [f["detection"] for f in fault_rows(rows, (kind,))]
        delays = [d["delay_min"] for d in det if d["detected"]]
        per_kind[kind] = {
            "n": len(det),
            "rate": _share([d["detected"] for d in det]),
            "median_delay_min": float(np.median(delays)) if delays else None,
        }
    models = [r["model"] for r in rows]
    faults = [r["fault"] for r in rows if r["fault"]]
    return {
        "per_kind": per_kind,
        "train_exc_t2": _mean([m["train_exc_t2"] for m in models]),
        "train_exc_spe": _mean([m["train_exc_spe"] for m in models]),
        "valid_share_quiet": _mean([r["quiet"]["valid_share"] for r in rows if r["quiet"]]),
        "valid_share_fault": _mean([f["valid_share"] for f in faults]),
        "pre_onset_events": sum(f["pre_onset_events"] for f in faults),
        "k_per_seed": {r["seed"]: r["model"]["k"] for r in rows},
    }


def _fmt(value: float | None, digits: int = 3) -> str:
    """Table cell of a number or a dash."""
    return "-" if value is None else f"{value:.{digits}f}"


def criteria_lines(crit: dict) -> list[str]:
    """Markdown rows of the A1..A5 table."""
    a1, a2, a3, a4, a5 = (crit[k] for k in ("A1", "A2", "A3", "A4", "A5"))
    return [
        "| id | values | verdict |",
        "| --- | --- | --- |",
        f"| A1 | false alarm events per 24 h on {a1['n']} quiet records: "
        f"mean {_fmt(a1['mean'])}, max {_fmt(a1['max'])} | {a1['verdict']} |",
        f"| A2 | drift detected {a2['detected']}/{a2['n']} ({_fmt(a2['share'])}) "
        f"| {a2['verdict']} |",
        f"| A3 | freeze detected {a3['detected']}/{a3['n']} ({_fmt(a3['share'])}) "
        f"| {a3['verdict']} |",
        f"| A4 | faulty tag in top 2 (dominant statistic) {_fmt(a4['share'])} of {a4['n']} "
        f"detected; SPE {_fmt(a4['share_spe'])}, T2 {_fmt(a4['share_t2'])}, "
        f"either {_fmt(a4['share_either'])} | {a4['verdict']} |",
        f"| A5 | removed-rows property {a5['ok']}/{a5['n']} bad_quality+dropout records "
        f"(other kinds {a5['ok_other_kinds']}) | {a5['verdict']} |",
    ]


def reported_lines(rep: dict) -> list[str]:
    """Markdown of the reported items."""
    lines = [
        "| kind | records | detection rate | median delay [min] |",
        "| --- | ---: | ---: | ---: |",
    ]
    for kind, v in rep["per_kind"].items():
        lines.append(
            f"| {kind} | {v['n']} | {_fmt(v['rate'])} | {_fmt(v['median_delay_min'], 1)} |"
        )
    ks = sorted(set(rep["k_per_seed"].values()))
    return lines + [
        f"\n- training-record exceedance (expected near 1 - alpha = {1 - CONFIG.alpha:.2f}): "
        f"T2 {_fmt(rep['train_exc_t2'], 4)}, SPE {_fmt(rep['train_exc_spe'], 4)} "
        "(mean over seeds)",
        f"- valid-row share: quiet {_fmt(rep['valid_share_quiet'], 4)}, "
        f"fault {_fmt(rep['valid_share_fault'], 4)}",
        f"- events starting before the fault onset on fault records: {rep['pre_onset_events']}",
        f"- model rank k values seen: {ks}",
    ]


def seed_table(rows: list[dict]) -> list[str]:
    """Per-seed markdown table."""
    lines = [
        "| seed | k | train exc T2/SPE | quiet ev/24h | kind | tag | onset [h] | detected | "
        "delay [min] | dominant | top2 hit | A5 | valid share |",
        "| ---: | ---: | --- | ---: | --- | --- | ---: | --- | ---: | --- | --- | --- | ---: |",
    ]
    for r in rows:
        m, q = r["model"], r["quiet"]
        quiet = _fmt(q["events_per_24h"], 2) if q else "-"
        exc = f"{_fmt(m['train_exc_t2'], 3)}/{_fmt(m['train_exc_spe'], 3)}"
        cells = _fault_cells(r["fault"])
        lines.append(f"| {r['seed']} | {m['k']} | {exc} | {quiet} | " + " | ".join(cells) + " |")
    return lines


def _fault_cells(f: dict | None) -> list[str]:
    """The nine fault-record cells of a per-seed table row (dashes without a fault record)."""
    if not f:
        return ["-"] * 9
    d, s = f["detection"], f["spec"]
    return [s["kind"], s["tag"].removeprefix("sim.mc."), _fmt(s["onset_s"] / 3600.0, 2),
            str(d["detected"]), _fmt(d["delay_min"], 1), str(d["dominant"] or "-"),
            str(d["top2_hit"] if d["top2_hit"] is not None else "-"), str(f["a5"]["ok"]),
            _fmt(f["valid_share"], 4)]


def render(payload: dict) -> str:
    """Markdown report of one seed set."""
    rows = payload["runs"]
    note = (
        "Dev seeds are a harness check only (each seed: training, quiet and fault record); "
        "the frozen criteria apply to the test seeds."
        if payload["seeds"] == "dev"
        else "Test seeds, run once."
    )
    parts = [
        f"# exp29 results: {payload['seeds']} seeds\n",
        f"Seeds: {len(rows)}; runtime {payload['runtime_s']:.0f} s. {note}\n",
        "## Criteria\n",
        *criteria_lines(payload["criteria"]),
        "\n## Reported (no target)\n",
        *reported_lines(payload["reported"]),
        "\n## Per seed\n",
        *seed_table(rows),
    ]
    return "\n".join(parts) + "\n"


def _json_default(value: object) -> object:
    """JSON encoder for numpy scalars."""
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"not JSON serialisable: {type(value)}")


def run(seeds: str, out_dir: Path, workers: int = 1) -> dict:
    """Run every planned seed, write <seeds>_runs.json and <seeds>.md, return the payload."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / f"{seeds}_runs.json", out_dir / f"{seeds}.md"
    for path in (json_path, md_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite {path}")
    started = time.perf_counter()
    rows = run_rows(plan(seeds), workers)
    payload = {
        "seeds": seeds,
        "criteria": criteria(rows),
        "reported": reported(rows),
        "runs": rows,
        "runtime_s": time.perf_counter() - started,
    }
    json_path.write_text(json.dumps(payload, indent=1, default=_json_default), encoding="utf-8")
    md_path.write_text(render(payload), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    """CLI: --seeds dev|test --out DIR (relative to this folder) --jobs N."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", choices=("dev", "test"), required=True)
    parser.add_argument("--out", default="results", help="output folder, relative to exp29")
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, (os.cpu_count() or 2) - 1),
        help="worker processes (results do not depend on it)",
    )
    args = parser.parse_args(argv)
    out = Path(args.out) if Path(args.out).is_absolute() else HERE / args.out
    payload = run(args.seeds, out, args.jobs)
    print(render(payload).split("## Per seed")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
