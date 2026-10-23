"""exp29 harness: PCA (T2 / SPE) anomaly detection on mill-circuit records with sensor faults.

Runs a FROZEN protocol of README.md: per seed fit on the 48 h training record, scan the quiet
(72 h) and fault (24 h) records, judge the criteria and the reported items. ``--round 1`` (default)
is the round 1 protocol (A1..A5); ``--round 2`` changes only the seeds, the configuration (dynamic
PCA, stuck-sensor rule, min_consecutive 10), the criteria (B1..B6) and the output names;
``--round 3`` is round 2 with alpha 0.999, min_consecutive 15, new test seeds and no dev seeds.
Writes results/<seeds>[2|3]_runs.json and results/<seeds>[2|3].md; never overwrites them.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
from crosscut_anomaly.config import AnomalyConfig
from crosscut_anomaly.detect import ScanResult, scan
from crosscut_anomaly.pca_model import PcaModel, augment_lags, fit_from_config

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen29  # noqa: E402

CONFIG = AnomalyConfig(schema_version="1.0.0", id="exp29", tags=gen29.TAGS, mode="advisory")
# Round 2 (README "Round 2 protocol"): dynamic PCA lags 2, stuck rule 15, min_consecutive 10.
CONFIG2 = dataclasses.replace(
    CONFIG, id="exp29r2", variance_fraction=0.90, alpha=0.99, min_consecutive=10,
    close_after=10, dynamic_lags=2, stuck_samples=15,
)
# Round 3 (README "Round 3 protocol"): round 2 with alpha 0.999 and min_consecutive 15.
CONFIG3 = dataclasses.replace(CONFIG2, id="exp29r3", alpha=0.999, min_consecutive=15)
DEV_SEEDS = range(29001, 29061)  # each: training + quiet + fault record (harness check only)
TEST_QUIET_SEEDS = range(29201, 29261)  # each: training + quiet record
TEST_FAULT_SEEDS = range(29301, 29400)  # each: training + fault record
# Detection window after onset, min: A2/B2 drift 180, A3/B3 freeze 60; reported kinds: 1 h window.
DETECT_WINDOW_MIN = {
    "drift": 180.0,
    "freeze": 60.0,
    "spike": 60.0,
    "bad_quality": 60.0,
    "dropout": 60.0,
}
A1_MEAN, A1_MAX = 1.0, 3.0  # false alarm events per 24 h (round 2: B1, same values)
A2_SHARE, A3_SHARE, A4_SHARE = 0.80, 0.80, 0.70  # round 2: B2, B3, B4, same values
B6_MEAN = 0.1  # stuck events per 24 h on the quiet records
TOP_N = 2  # A4 / B4: faulty tag among the top 2 contributors
SKIP_KINDS = ("bad_quality", "dropout")  # A5 / B5 records
RULES = ("pca", "stuck")  # event kinds of the module
DAY_S = 86400.0


@dataclass(frozen=True)
class Round:
    """Seed ranges, configuration and output-name suffix of one frozen protocol round."""

    number: int
    config: AnomalyConfig
    dev_seeds: range
    quiet_seeds: range
    fault_seeds: range
    suffix: str


ROUNDS = {
    1: Round(1, CONFIG, DEV_SEEDS, TEST_QUIET_SEEDS, TEST_FAULT_SEEDS, ""),
    2: Round(2, CONFIG2, range(29601, 29661), range(29701, 29761), range(29801, 29900), "2"),
    # No round 3 development seeds: only the scratch seeds 990021/990022 in the smoke tests.
    3: Round(3, CONFIG3, range(0), range(33001, 33061), range(33101, 33200), "3"),
}


def plan(seeds: str, round_no: int = 1) -> list[tuple[int, bool, int | None]]:
    """(seed, has quiet record, fault index or None) for 'dev' or 'test' of one round.

    Raises SystemExit for 'dev' in a round without development seeds (round 3).
    """
    rnd = ROUNDS[round_no]
    if seeds == "dev" and not rnd.dev_seeds:
        raise SystemExit(
            f"round {round_no} has no development seeds (README 'Round {round_no} protocol'); "
            "only --seeds test is allowed, harness checks use the scratch seeds of the smoke tests"
        )
    if seeds == "dev":
        return [(s, True, s - rnd.dev_seeds.start) for s in rnd.dev_seeds]
    return [(s, True, None) for s in rnd.quiet_seeds] + [
        (s, False, s - rnd.fault_seeds.start) for s in rnd.fault_seeds
    ]


def fit(train: gen29.Record, config: AnomalyConfig = CONFIG) -> PcaModel:
    """PCA model on the training rows with the frozen settings of ``config``.

    ``fit_from_config`` passes dynamic_lags and stuck_samples, so a round 2 model stores the
    per-tag longest constant training run behind the per-tag stuck thresholds.
    """
    return fit_from_config(train.x, config)


def run_scan(model: PcaModel, record: gen29.Record, config: AnomalyConfig = CONFIG) -> ScanResult:
    """Scan a record with the frozen configuration."""
    return scan(model, record.t_s, record.x, record.quality, config)


def model_summary(model: PcaModel, train: gen29.Record) -> dict:
    """Rank, limits, SPE limit method and the empirical limit exceedance on the training rows.

    Exceedance is taken over the rows with a defined statistic (all rows for static PCA; the
    rows with full lag history for dynamic PCA).
    """
    aug = augment_lags(train.x, model.dynamic_lags)
    t2, spe = model.t2(aug), model.spe(aug)
    ok = np.isfinite(t2) & np.isfinite(spe)
    t2_exc, spe_exc = t2[ok] > model.t2_limit, spe[ok] > model.spe_limit
    return {
        "k": model.k,
        "n_train": model.n_train,
        "n_columns": len(model.tags),
        "t2_limit": model.t2_limit,
        "spe_limit": model.spe_limit,
        "spe_limit_method": model.spe_limit_method,
        "stuck_runs": list(model.stuck_runs),  # longest constant run per tag in training
        "train_exc_t2": float(np.mean(t2_exc)),
        "train_exc_spe": float(np.mean(spe_exc)),
        "train_exc_any": float(np.mean(t2_exc | spe_exc)),
        "train_sd": gen29.training_sd(train).tolist(),
    }


def event_dict(event) -> dict:
    """JSON form of an AnomalyEvent."""
    return {
        "kind": event.kind,
        "stuck_tag": event.stuck_tag,
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
    """Events, valid share, skipped counts and limit methods of one scan."""
    n = len(record.t_s)
    return {
        "n_rows": n,
        "n_valid": result.n_valid,
        "n_skipped": result.n_skipped,
        "skipped_reasons": dict(result.skipped_reasons),
        "valid_share": result.n_valid / n,
        "n_pca_events": result.n_pca_events,
        "n_stuck_events": result.n_stuck_events,
        "limit_methods": dict(result.limit_methods),
        "events": [event_dict(e) for e in result.events],
    }


def quiet_summary(model: PcaModel, record: gen29.Record, config: AnomalyConfig = CONFIG) -> dict:
    """Quiet record: events and false alarm events per 24 h (all, pca, stuck)."""
    summary = scan_summary(run_scan(model, record, config), record)
    span_s = len(record.t_s) * gen29.ROW_PERIOD_S  # round 1 arithmetic order, bit-exact
    summary["events_per_24h"] = len(summary["events"]) * DAY_S / span_s
    summary["pca_per_24h"] = summary["n_pca_events"] * DAY_S / span_s
    summary["stuck_per_24h"] = summary["n_stuck_events"] * DAY_S / span_s
    return summary


def dominant(event: dict, model: PcaModel) -> str:
    """Statistic with the larger limit ratio at the event peak: 't2' or 'spe' ('stuck' rule)."""
    if event.get("kind") == "stuck":
        return "stuck"
    return (
        "t2" if event["peak_t2"] / model.t2_limit >= event["peak_spe"] / model.spe_limit else "spe"
    )


def _hits(events: list[dict], spec: dict, kinds: tuple[str, ...] = RULES) -> list[dict]:
    """Events of ``kinds`` starting within the kind's window after onset, overlapping the fault."""
    onset, window_s = spec["onset_s"], DETECT_WINDOW_MIN[spec["kind"]] * 60.0
    return [e for e in events if e["kind"] in kinds and onset <= e["start_s"] <= onset + window_s
            and e["start_s"] <= spec["end_s"] and e["end_s"] >= onset]


def detection(events: list[dict], spec: dict, model: PcaModel) -> dict:
    """First event of either rule in the window, its delay and contributors, plus per rule."""
    hits, tag = _hits(events, spec), spec["tag"]
    if not hits:
        keys = ("delay_min", "rule", "dominant", "top2_hit", "top2_spe_hit", "top2_t2_hit")
        return {"detected": False} | dict.fromkeys(keys) | _per_rule(events, spec)
    first = hits[0]
    stat = dominant(first, model)
    top = first["top_spe"] if stat == "stuck" else first[f"top_{stat}"]
    return {
        "detected": True,
        "delay_min": (first["start_s"] - spec["onset_s"]) / 60.0,
        "rule": first["kind"],
        "dominant": stat,
        "top2_hit": tag in top[:TOP_N],
        "top2_spe_hit": tag in first["top_spe"][:TOP_N],
        "top2_t2_hit": tag in first["top_t2"][:TOP_N],
    } | _per_rule(events, spec)


def _per_rule(events: list[dict], spec: dict) -> dict:
    """Detection and delay by each rule alone; whether a stuck hit names the faulty tag."""
    out: dict = {}
    for rule in RULES:
        hits = _hits(events, spec, (rule,))
        out[f"{rule}_detected"] = bool(hits)
        out[f"{rule}_delay_min"] = (hits[0]["start_s"] - spec["onset_s"]) / 60.0 if hits else None
    stuck = _hits(events, spec, ("stuck",))
    out["stuck_names_tag"] = any(e["stuck_tag"] == spec["tag"] for e in stuck)
    return out


def removed_rows_check(
    model: PcaModel, record: gen29.Record, full: ScanResult, config: AnomalyConfig = CONFIG
) -> dict:
    """A5 / B5 property: the scan without the invalid rows gives the same events (rows mapped)."""
    keep = np.flatnonzero(~np.isnan(record.x).any(axis=1) & (record.quality == 0))
    reduced = scan(model, record.t_s[keep], record.x[keep], record.quality[keep], config)
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
    """Equal rule, times, closure and peak; reduced row indices mapped back through ``keep``."""
    mapped = tuple(
        int(keep[i])
        for i in (reduced_event.start_index, reduced_event.end_index, reduced_event.peak_index)
    )
    return (
        mapped == (full_event.start_index, full_event.end_index, full_event.peak_index)
        and (full_event.kind, full_event.stuck_tag) == (reduced_event.kind, reduced_event.stuck_tag)
        and full_event.start_s == reduced_event.start_s
        and full_event.end_s == reduced_event.end_s
        and full_event.closed == reduced_event.closed
        and full_event.n_samples == reduced_event.n_samples
    )


def fault_summary(
    seed: int, index: int, fitted: tuple[PcaModel, np.ndarray], setup: tuple
) -> dict:
    """Fault record: spec, scan, detection, A5/B5 property, pre-onset events.

    ``fitted`` = (model, training sd); ``setup`` = (durations, config).
    """
    (model, sd), (durations, config) = fitted, setup
    spec = gen29.fault_spec(seed, index, sd, durations)
    record = gen29.fault_record(seed, spec, durations)
    result = run_scan(model, record, config)
    summary = scan_summary(result, record) | {"spec": spec}
    summary["detection"] = detection(summary["events"], spec, model)
    summary["a5"] = removed_rows_check(model, record, result, config)
    summary["pre_onset_events"] = sum(
        1 for e in summary["events"] if e["start_s"] < spec["onset_s"]
    )
    return summary


def run_one(
    seed: int, has_quiet: bool, fault_index: int | None,
    durations: gen29.Durations = gen29.PROTOCOL, round_no: int = 1,
) -> dict:
    """Training fit plus the quiet and/or fault record of one seed; the JSON row."""
    started, config = time.perf_counter(), ROUNDS[round_no].config
    train = gen29.training_record(seed, durations)
    model = fit(train, config)
    row = {"seed": seed, "model": model_summary(model, train), "quiet": None, "fault": None}
    if has_quiet:
        row["quiet"] = quiet_summary(model, gen29.quiet_record(seed, durations), config)
    if fault_index is not None:
        sd = np.asarray(row["model"]["train_sd"])
        row["fault"] = fault_summary(seed, fault_index, (model, sd), (durations, config))
    row["runtime_s"] = time.perf_counter() - started
    return row


def _run_job(job: tuple, round_no: int = 1) -> dict:
    """Process-pool entry: unpack one planned run."""
    return run_one(*job, round_no=round_no)


def run_rows(jobs: list[tuple], workers: int, round_no: int = 1) -> list[dict]:
    """run_one over the plan (in a process pool when workers > 1), rows in plan order."""
    job_fn = partial(_run_job, round_no=round_no)
    if workers <= 1:
        return [job_fn(job) for job in jobs]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, row in enumerate(pool.map(job_fn, jobs)):
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
    """False alarm events (any rule) per 24 h on the quiet records: mean and maximum."""
    rates = [r["quiet"]["events_per_24h"] for r in rows if r["quiet"]]
    if not rates:
        return {"n": 0, "mean": None, "max": None, "verdict": _verdict(None)}
    mean, worst = float(np.mean(rates)), float(np.max(rates))
    return {
        "n": len(rates),
        "mean": mean,
        "max": worst,
        "mean_pca": _mean([r["quiet"]["pca_per_24h"] for r in rows if r["quiet"]]),
        "verdict": _verdict(mean <= A1_MEAN and worst <= A1_MAX),
    }


def criterion_detect(rows: list[dict], kind: str, target: float) -> dict:
    """A2 / A3 (B2 / B3): detected share of the records of one fault kind, plus per rule."""
    det = [f["detection"] for f in fault_rows(rows, (kind,))]
    hits = [d["detected"] for d in det]
    value = _share(hits)
    return {
        "n": len(hits),
        "detected": sum(hits),
        "share": value,
        "by_pca": sum(bool(d.get("pca_detected")) for d in det),
        "by_stuck": sum(bool(d.get("stuck_detected")) for d in det),
        "verdict": _verdict(None if value is None else value >= target),
    }


def criterion_a4(rows: list[dict]) -> dict:
    """Faulty tag among the top 2 (dominant statistic; stuck names it) for detected drift/freeze."""
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
        "n_stuck_rule": sum(d.get("rule") == "stuck" for d in det),
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


def criterion_b6(rows: list[dict]) -> dict:
    """Stuck events per 24 h on the quiet records: mean (and maximum, reported)."""
    rates = [r["quiet"]["stuck_per_24h"] for r in rows if r["quiet"]]
    if not rates:
        return {"n": 0, "mean": None, "max": None, "verdict": _verdict(None)}
    mean = float(np.mean(rates))
    return {"n": len(rates), "mean": mean, "max": float(np.max(rates)),
            "records_with_stuck": sum(rate > 0 for rate in rates),
            "verdict": _verdict(mean <= B6_MEAN)}


def criteria(rows: list[dict], round_no: int = 1) -> dict:
    """A1..A5 (round 1) or B1..B6 (rounds 2 and 3) values and verdicts."""
    values = [
        criterion_a1(rows),
        criterion_detect(rows, "drift", A2_SHARE),
        criterion_detect(rows, "freeze", A3_SHARE),
        criterion_a4(rows),
        criterion_a5(rows),
    ]
    if round_no == 1:
        return dict(zip(("A1", "A2", "A3", "A4", "A5"), values, strict=True))
    return dict(zip(("B1", "B2", "B3", "B4", "B5"), values, strict=True)) | {
        "B6": criterion_b6(rows)
    }


def _mean(values: list[float]) -> float | None:
    """Mean or None for an empty list."""
    return float(np.mean(values)) if values else None


def _median(values: list[float]) -> float | None:
    """Median or None for an empty list."""
    return float(np.median(values)) if values else None


def _kind_report(det: list[dict]) -> dict:
    """Detection rate and median delay of one fault kind, overall and per rule."""
    out = {
        "n": len(det),
        "rate": _share([d["detected"] for d in det]),
        "median_delay_min": _median([d["delay_min"] for d in det if d["detected"]]),
    }
    for rule in RULES:
        hit = [d for d in det if d.get(f"{rule}_detected")]
        out[f"{rule}_rate"] = _share([bool(d.get(f"{rule}_detected")) for d in det])
        out[f"{rule}_median_delay_min"] = _median([d[f"{rule}_delay_min"] for d in hit])
    return out


def reported(rows: list[dict]) -> dict:
    """No-target figures: per-kind detection, exceedance, valid share, k, SPE limit method."""
    models = [r["model"] for r in rows]
    faults = [r["fault"] for r in rows if r["fault"]]
    quiets = [r["quiet"] for r in rows if r["quiet"]]
    return {
        "per_kind": {kind: _kind_report([f["detection"] for f in fault_rows(rows, (kind,))])
                     for kind in gen29.FAULT_KINDS},
        "train_exc_t2": _mean([m["train_exc_t2"] for m in models]),
        "train_exc_spe": _mean([m["train_exc_spe"] for m in models]),
        "valid_share_quiet": _mean([q["valid_share"] for q in quiets]),
        "valid_share_fault": _mean([f["valid_share"] for f in faults]),
        "lag_rows_lost": _lag_lost(quiets + faults),
        "quiet_pca_per_24h": _mean([q["pca_per_24h"] for q in quiets]),
        "quiet_stuck_per_24h": _mean([q["stuck_per_24h"] for q in quiets]),
        "pre_onset_events": sum(f["pre_onset_events"] for f in faults),
        "k_per_seed": {r["seed"]: r["model"]["k"] for r in rows},
        "spe_limit_method_per_seed": {r["seed"]: r["model"]["spe_limit_method"] for r in rows},
        "spe_limit_method_counts": dict(Counter(m["spe_limit_method"] for m in models)),
        "stuck_runs_max": _stuck_runs_max(models),
    }


def _stuck_runs_max(models: list[dict]) -> list[int]:
    """Per tag, the longest constant training run over all seeds (empty without the rule)."""
    runs = [m.get("stuck_runs") for m in models if m.get("stuck_runs")]
    return [int(v) for v in np.max(runs, axis=0)] if runs else []


def _lag_lost(scans: list[dict]) -> dict:
    """Valid rows lost to the lag history (skipped reason 'lag'): total, mean and max per record."""
    lost = [s["skipped_reasons"].get("lag", 0) for s in scans]
    return {"total": int(sum(lost)), "mean": _mean(lost), "max": int(max(lost, default=0))}


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


def _detect_cell(c: dict, kind: str) -> str:
    """B2 / B3 values cell: detected share plus the per-rule counts."""
    return (f"{kind} detected {c['detected']}/{c['n']} ({_fmt(c['share'])}); "
            f"by pca {c['by_pca']}, by stuck {c['by_stuck']}")


def criteria_lines2(crit: dict) -> list[str]:
    """Markdown rows of the B1..B6 table (rounds 2 and 3)."""
    b1, b2, b3, b4, b5, b6 = (crit[f"B{i}"] for i in range(1, 7))
    return [
        "| id | values | verdict |",
        "| --- | --- | --- |",
        f"| B1 | false alarm events (any rule) per 24 h on {b1['n']} quiet records: mean "
        f"{_fmt(b1['mean'])} (pca {_fmt(b1.get('mean_pca'))}), max {_fmt(b1['max'])} "
        f"| {b1['verdict']} |",
        f"| B2 | {_detect_cell(b2, 'drift')} | {b2['verdict']} |",
        f"| B3 | {_detect_cell(b3, 'freeze')} | {b3['verdict']} |",
        f"| B4 | faulty tag in top 2 (stuck: named) {_fmt(b4['share'])} of {b4['n']} detected "
        f"({b4['n_stuck_rule']} by the stuck rule); SPE {_fmt(b4['share_spe'])}, "
        f"T2 {_fmt(b4['share_t2'])} | {b4['verdict']} |",
        f"| B5 | removed-rows property {b5['ok']}/{b5['n']} bad_quality+dropout records "
        f"(other kinds {b5['ok_other_kinds']}) | {b5['verdict']} |",
        f"| B6 | stuck events per 24 h on {b6['n']} quiet records: mean {_fmt(b6['mean'])}, "
        f"max {_fmt(b6['max'])}, records with any {b6.get('records_with_stuck', 0)} "
        f"| {b6['verdict']} |",
    ]


def reported_lines(rep: dict, alpha: float = CONFIG.alpha) -> list[str]:
    """Markdown of the reported items (round 1)."""
    lines = [
        "| kind | records | detection rate | median delay [min] |",
        "| --- | ---: | ---: | ---: |",
    ]
    for kind, v in rep["per_kind"].items():
        lines.append(
            f"| {kind} | {v['n']} | {_fmt(v['rate'])} | {_fmt(v['median_delay_min'], 1)} |"
        )
    return lines + _common_lines(rep, alpha)


def _common_lines(rep: dict, alpha: float) -> list[str]:
    """Bullet lines shared by both rounds: exceedance, valid share, pre-onset events, k."""
    ks = sorted(set(rep["k_per_seed"].values()))
    return [
        f"\n- training-record exceedance (expected near 1 - alpha = {1 - alpha:g}): "
        f"T2 {_fmt(rep['train_exc_t2'], 4)}, SPE {_fmt(rep['train_exc_spe'], 4)} "
        "(mean over seeds)",
        f"- valid-row share: quiet {_fmt(rep['valid_share_quiet'], 4)}, "
        f"fault {_fmt(rep['valid_share_fault'], 4)}",
        f"- events starting before the fault onset on fault records: {rep['pre_onset_events']}",
        f"- model rank k values seen: {ks}",
    ]


def reported_lines2(rep: dict, alpha: float = CONFIG2.alpha) -> list[str]:
    """Markdown of the reported items (rounds 2, 3): per kind and rule, lag rows, SPE method."""
    lines = [
        "| kind | records | rate (any) | median delay [min] | pca rate | pca delay | "
        "stuck rate | stuck delay |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for kind, v in rep["per_kind"].items():
        lines.append(
            f"| {kind} | {v['n']} | {_fmt(v['rate'])} | {_fmt(v['median_delay_min'], 1)} | "
            f"{_fmt(v['pca_rate'])} | {_fmt(v['pca_median_delay_min'], 1)} | "
            f"{_fmt(v['stuck_rate'])} | {_fmt(v['stuck_median_delay_min'], 1)} |"
        )
    lag = rep["lag_rows_lost"]
    return lines + _common_lines(rep, alpha) + [
        f"- quiet records, events per 24 h by rule: pca {_fmt(rep['quiet_pca_per_24h'])}, "
        f"stuck {_fmt(rep['quiet_stuck_per_24h'])}",
        f"- valid rows lost to the lag history: total {lag['total']}, mean "
        f"{_fmt(lag['mean'], 2)} and max {lag['max']} per scanned record",
        f"- SPE limit method (seeds): {rep['spe_limit_method_counts']}",
        f"- longest constant training run per tag, max over seeds ({', '.join(gen29.TAG_NAMES)}): "
        f"{rep['stuck_runs_max']}",
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


def seed_table2(rows: list[dict]) -> list[str]:
    """Per-seed markdown table (rounds 2 and 3): SPE limit method and per-rule columns added."""
    lines = [
        "| seed | k | SPE limit | train exc T2/SPE | quiet ev/24h pca/stuck | kind | tag | "
        "onset [h] | detected | delay [min] | rule | top2 hit | pca/stuck hit | B5 | "
        "valid share |",
        "| ---: | ---: | --- | --- | --- | --- | --- | ---: | --- | ---: | --- | --- | --- "
        "| --- | ---: |",
    ]
    for r in rows:
        m, q = r["model"], r["quiet"]
        quiet = f"{_fmt(q['pca_per_24h'], 2)}/{_fmt(q['stuck_per_24h'], 2)}" if q else "-"
        exc = f"{_fmt(m['train_exc_t2'], 3)}/{_fmt(m['train_exc_spe'], 3)}"
        head = f"| {r['seed']} | {m['k']} | {m['spe_limit_method']} | {exc} | {quiet} | "
        lines.append(head + " | ".join(_fault_cells2(r["fault"])) + " |")
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


def _fault_cells2(f: dict | None) -> list[str]:
    """The ten fault-record cells of a round 2 per-seed row (dashes without a fault record)."""
    if not f:
        return ["-"] * 10
    d, s = f["detection"], f["spec"]
    return [s["kind"], s["tag"].removeprefix("sim.mc."), _fmt(s["onset_s"] / 3600.0, 2),
            str(d["detected"]), _fmt(d["delay_min"], 1), str(d["rule"] or "-"),
            str(d["top2_hit"] if d["top2_hit"] is not None else "-"),
            f"{d['pca_detected']}/{d['stuck_detected']}", str(f["a5"]["ok"]),
            _fmt(f["valid_share"], 4)]


def render(payload: dict) -> str:
    """Markdown report of one seed set of one round."""
    rows, round_no = payload["runs"], payload.get("round", 1)
    note = (
        "Dev seeds are a harness check only (each seed: training, quiet and fault record); "
        "the frozen criteria apply to the test seeds."
        if payload["seeds"] == "dev"
        else "Test seeds, run once."
    )
    title = "# exp29 results" + ("" if round_no == 1 else f" (round {round_no})")
    crit, rep, table = (
        (criteria_lines, reported_lines, seed_table)
        if round_no == 1 else (criteria_lines2, reported_lines2, seed_table2)
    )
    parts = [
        f"{title}: {payload['seeds']} seeds\n",
        f"Seeds: {len(rows)}; runtime {payload['runtime_s']:.0f} s. {note}\n",
        "## Criteria\n", *crit(payload["criteria"]),
        "\n## Reported (no target)\n", *rep(payload["reported"], payload["config"]["alpha"]),
        "\n## Per seed\n", *table(rows),
    ]
    return "\n".join(parts) + "\n"


def _json_default(value: object) -> object:
    """JSON encoder for numpy scalars."""
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"not JSON serialisable: {type(value)}")


def run(
    seeds: str, out_dir: Path, workers: int = 1, round_no: int = 1, name: str | None = None
) -> dict:
    """Run every planned seed, write <name>_runs.json and <name>.md, return the payload.

    ``name`` defaults to <seeds>[2] (round suffix).
    """
    jobs = plan(seeds, round_no)  # refuses 'dev' for a round without dev seeds, before any write
    out_dir.mkdir(parents=True, exist_ok=True)
    name = name or f"{seeds}{ROUNDS[round_no].suffix}"
    json_path, md_path = out_dir / f"{name}_runs.json", out_dir / f"{name}.md"
    for path in (json_path, md_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite {path}")
    started = time.perf_counter()
    rows = run_rows(jobs, workers, round_no)
    payload = {
        "seeds": seeds,
        "round": round_no,
        "config": dataclasses.asdict(ROUNDS[round_no].config),
        "criteria": criteria(rows, round_no),
        "reported": reported(rows),
        "runs": rows,
        "runtime_s": time.perf_counter() - started,
    }
    json_path.write_text(json.dumps(payload, indent=1, default=_json_default), encoding="utf-8")
    md_path.write_text(render(payload), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    """CLI: --round 1|2|3 --seeds dev|test --out DIR (relative to this folder) --name --jobs N."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", choices=("dev", "test"), required=True)
    parser.add_argument("--round", type=int, choices=tuple(ROUNDS), default=1, dest="round_no")
    parser.add_argument("--out", default="results", help="output folder, relative to exp29")
    parser.add_argument("--name", default=None, help="output base name (default <seeds>[2|3])")
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, (os.cpu_count() or 2) - 1),
        help="worker processes (results do not depend on it)",
    )
    args = parser.parse_args(argv)
    out = Path(args.out) if Path(args.out).is_absolute() else HERE / args.out
    payload = run(args.seeds, out, args.jobs, args.round_no, args.name)
    print(render(payload).split("## Per seed")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
