"""exp36: run the Crosscut anomaly engine on SKAB and a Petrobras 3W subset (protocol in README.md).

Reads local copies of the public data (never committed), applies the frozen protocol once and
prints a JSON result; without the data it prints SKIP and exits 0. Issue #87.
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
from crosscut_anomaly.config import AnomalyConfig, load_config
from crosscut_anomaly.detect import scan
from crosscut_anomaly.pca_model import PcaModel, fit_from_config
from crosscut_anomaly.ramp_detect import find_linear_ramps, unreliable_tags

BIN_3W = 10  # seconds per 3W bin (block mean of 1 s samples)
RAMP_MIN_BINS = 90  # ramp_min_hours 0.25 at 10 s bins
GAP_MIN_BINS = 90  # NaN or frozen stretch that counts as a real gap
COUNTER_SHARE = 0.9
SKAB_TAGS = ["Accelerometer1RMS", "Accelerometer2RMS", "Current", "Pressure", "Temperature",
             "Thermocouple", "Voltage", "Volume Flow RateRMS"]
EVENT_CLASSES = (3, 4, 7)
BASE = {"schema_version": "1.0.0", "mode": "advisory", "variance_fraction": 0.90, "alpha": 0.99,
        "min_consecutive": 5, "close_after": 10, "stuck_samples": 30}
TARGETS = {"F1": 3.0, "F2": 0.02, "D1": 0.70, "D2_3w_min": 15.0, "D2_skab_s": 60.0, "R1": 0.50}


def make_config(name: str, tags: list[str], period_s: float) -> AnomalyConfig:
    """Frozen detector configuration for one fit."""
    return load_config({**BASE, "id": name, "tags": tags, "sample_period_s": period_s})


def score_file(
    model: PcaModel, config: AnomalyConfig, x: np.ndarray, quiet: np.ndarray, onset: int | None
) -> dict:
    """Scan one record. ``quiet`` marks certified quiet bins; ``onset`` is the event start bin."""
    t = np.arange(len(x)) * config.sample_period_s
    events = scan(model, t, x, config=config).events
    false_events = [e for e in events if quiet[e.start_index]]
    inside = np.zeros(len(x), dtype=bool)  # union of events: PCA and stuck events may overlap
    for e in events:
        inside[e.start_index : e.end_index + 1] = True
    alarm = int((inside & quiet).sum())
    later = [e.start_index for e in events if onset is not None and e.start_index >= onset]
    return {"fa_events": len(false_events), "quiet_bins": int(quiet.sum()),
            "alarm_quiet_bins": alarm,
            "stuck_events": sum(e.kind == "stuck" for e in events),
            "delay_bins": (min(later) - onset) if later else None, "has_onset": onset is not None}


def pool(rows: list[dict], period_s: float) -> dict:
    """Pooled false alarms per day, alarm share, detection rate and median delay."""
    quiet = sum(r["quiet_bins"] for r in rows)
    days = quiet * period_s / 86400.0
    delays = [r["delay_bins"] for r in rows if r["delay_bins"] is not None]
    n_event = sum(r["has_onset"] for r in rows)
    fa = sum(r["fa_events"] for r in rows)
    return {
        "files": len(rows), "quiet_hours": quiet * period_s / 3600.0, "fa_events": fa,
        "fa_per_day": fa / days if quiet else None,
        "alarm_share_quiet": sum(r["alarm_quiet_bins"] for r in rows) / quiet if quiet else None,
        "stuck_events": sum(r["stuck_events"] for r in rows),
        "event_files": n_event, "detected": len(delays),
        "detection_rate": len(delays) / n_event if n_event else None,
        "median_delay_s": float(np.median(delays)) * period_s if delays else None,
    }


def read_skab(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    """SKAB csv (';' separated) as the 8 tags by rows and the anomaly column (None if absent)."""
    t = pacsv.read_csv(path, parse_options=pacsv.ParseOptions(delimiter=";"))
    x = np.column_stack([t[c].to_numpy() for c in SKAB_TAGS]).astype(float)
    return x, (t["anomaly"].to_numpy().astype(float) if "anomaly" in t.column_names else None)


def run_skab(folder: Path) -> dict:
    """SKAB: fit on 70 % of anomaly-free, quiet = rest of it and pre-onset parts of the others."""
    data = folder / "skab" / "data"
    free, _ = read_skab(data / "anomaly-free" / "anomaly-free.csv")
    cut = int(0.7 * len(free))
    config = make_config("skab_v1", SKAB_TAGS, 1.0)
    model = fit_from_config(free[:cut], config)
    rows = [score_file(model, config, free[cut:], np.ones(len(free) - cut, bool), None)]
    for path in sorted(data.glob("*/*.csv")):
        if path.parent.name == "anomaly-free":
            continue
        x, a = read_skab(path)
        onset = int(np.flatnonzero(a == 1)[0])
        rows.append(score_file(model, config, x, np.arange(len(x)) < onset, onset))
    return {"fit_rows": cut, **pool(rows, 1.0)}


def load_3w(path: Path) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Binned columns (10 s block means, NaN for an empty bin) and the labels as bins by samples."""
    t = pq.read_table(path)
    names = [c for c in t.column_names if c not in ("class", "state", "timestamp")]
    n = t.num_rows // BIN_3W * BIN_3W
    cols = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for c in names:
            v = t[c].to_numpy(zero_copy_only=False).astype(float)[:n]
            cols[c] = np.nanmean(v.reshape(-1, BIN_3W), axis=1)
    cls = t["class"].to_numpy(zero_copy_only=False).astype(float)[:n].reshape(-1, BIN_3W)
    return cols, cls


def class_info(cls: np.ndarray, event: int) -> tuple[np.ndarray, int | None]:
    """Quiet mask (every sample of the bin labelled 0) and onset bin (event or transient label)."""
    quiet = (cls == 0).all(axis=1)
    hit = np.flatnonzero(np.isin(cls, (event, 100 + event)).any(axis=1)) if event else []
    return quiet, (int(hit[0]) if len(hit) else None)


def well_files(root: Path) -> dict[str, list[tuple[int, Path]]]:
    """3W files present locally grouped by well (name prefix before the first underscore)."""
    wells: dict[str, list[tuple[int, Path]]] = {}
    for path in sorted(root.glob("*/WELL-*.parquet")):
        wells.setdefault(path.name.split("_")[0], []).append((int(path.parent.name), path))
    return wells


def well_tags(loaded: list[tuple[int, dict, np.ndarray]]) -> list[str]:
    """Columns finite in >= 99 % of bins of every file and not constant in the fit data."""
    fit_cols, fit_cls = loaded[0][1], loaded[0][2]
    fit_quiet = (fit_cls == 0).all(axis=1)
    tags = []
    for c in sorted(fit_cols):
        ok = all(np.isfinite(cols[c]).mean() >= 0.99 for _, cols, _ in loaded)
        v = fit_cols[c][fit_quiet]
        if ok and np.isfinite(v).all() and np.ptp(v) > 0:
            tags.append(c)
    return tags


def run_well(files: list[tuple[int, Path]]) -> tuple[list[dict], list[dict], str | None]:
    """Fit on the first class 0 file of a well; return quiet rows, event rows and a skip reason."""
    files = sorted(files, key=lambda f: (f[0] != 0, f[1].name))
    if files[0][0] != 0:
        return [], [], "no class 0 file to fit"
    loaded = [(c, *load_3w(p)) for c, p in files]
    tags = well_tags(loaded)
    if len(tags) < 3:
        return [], [], f"only {len(tags)} usable tags"
    config = make_config("w3_v1", tags, float(BIN_3W))
    fit_cols, fit_cls = loaded[0][1], loaded[0][2]
    fit_x = np.column_stack([fit_cols[t] for t in tags])[(fit_cls == 0).all(axis=1)]
    model = fit_from_config(fit_x, config)
    quiet_rows, event_rows = [], []
    for cls_id, cols, cls in loaded[1:]:
        quiet, onset = class_info(cls, cls_id if cls_id in EVENT_CLASSES else 0)
        row = score_file(model, config, np.column_stack([cols[t] for t in tags]), quiet, onset)
        (event_rows if onset is not None else quiet_rows).append(row)
        if onset is not None and quiet.any():
            quiet_rows.append({**row, "has_onset": False, "delay_bins": None})
    return quiet_rows, event_rows, None


def true_runs(flag: np.ndarray) -> list[tuple[int, int]]:
    """Half-open index ranges of the maximal True runs of a boolean array."""
    padded = np.concatenate(([False], flag, [False]))
    ch = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(a), int(b)) for a, b in zip(ch[0::2], ch[1::2], strict=True)]


def real_gaps(v: np.ndarray) -> list[tuple[int, int]]:
    """NaN runs and exactly constant runs of at least GAP_MIN_BINS bins, as half-open bin ranges."""
    nan_runs = true_runs(np.isnan(v))
    with np.errstate(invalid="ignore"):
        repeat = np.concatenate(([False], v[1:] == v[:-1]))
    frozen = [(a - 1, b) for a, b in true_runs(repeat)]
    return [(a, b) for a, b in nan_runs + frozen if b - a >= GAP_MIN_BINS]


def ramp_stats(cols: dict[str, np.ndarray]) -> dict:
    """Flagged ramp spans of one file, how many touch a real gap or frozen stretch, and the gaps."""
    live = {c: v for c, v in cols.items() if np.isfinite(v).any()}
    flagged = unreliable_tags(live, min_len=RAMP_MIN_BINS)
    spans = hit = gaps = 0
    for tag, v in live.items():
        real = real_gaps(v)
        gaps += len(real)
        if tag in flagged and flagged[tag] < COUNTER_SHARE:
            for s in find_linear_ramps(v, min_len=RAMP_MIN_BINS):
                spans += 1
                hit += any(s.start - 1 <= b and a <= s.end + 1 for a, b in real)
    return {"spans": spans, "hit": hit, "gaps": gaps}


def run_3w(folder: Path) -> dict:
    """3W: per-well fits, pooled quiet and event scores, ramp-warning precision on all files."""
    root = folder / "w3" / "dataset"
    wells = well_files(root)
    quiet_rows, event_rows, skipped, ramps = [], [], {}, []
    for well, files in wells.items():
        q, e, why = run_well(files)
        quiet_rows += q
        event_rows += e
        if why:
            skipped[well] = why
        ramps += [ramp_stats(load_3w(p)[0]) for _, p in files]
    r = {k: sum(x[k] for x in ramps) for k in ("spans", "hit", "gaps")}
    r["precision"] = r["hit"] / r["spans"] if r["spans"] else None
    return {"quiet": pool(quiet_rows, BIN_3W), "events": pool(event_rows, BIN_3W),
            "skipped_wells": skipped, "ramp": r, "files_total": sum(len(f) for f in wells.values())}


def verdict(res: dict) -> dict:
    """Frozen targets F1, F2, D1, D2, R1 evaluated on the results (None = not evaluable)."""
    s, q, e, r = res["skab"], res["w3"]["quiet"], res["w3"]["events"], res["w3"]["ramp"]

    def delay_ok(d: float | None, limit_s: float) -> bool:
        return d is not None and d <= limit_s

    return {
        "F1_skab": s["fa_per_day"] <= TARGETS["F1"], "F1_3w": q["fa_per_day"] <= TARGETS["F1"],
        "F2_skab": s["alarm_share_quiet"] <= TARGETS["F2"],
        "F2_3w": q["alarm_share_quiet"] <= TARGETS["F2"],
        "D1_skab": s["detection_rate"] >= TARGETS["D1"],
        "D1_3w": e["detection_rate"] >= TARGETS["D1"],
        "D2_skab": delay_ok(s["median_delay_s"], TARGETS["D2_skab_s"]),
        "D2_3w": delay_ok(e["median_delay_s"], TARGETS["D2_3w_min"] * 60.0),
        "R1": None if r["precision"] is None else r["precision"] >= TARGETS["R1"],
    }


def main(argv: list[str] | None = None) -> int:
    """Run the protocol; SKIP (exit 0) when either dataset folder is missing."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="folder holding skab/ and w3/")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if not (args.data / "skab" / "data").is_dir() or not (args.data / "w3" / "dataset").is_dir():
        print(f"SKIP exp36: skab/data and w3/dataset not found in {args.data}")
        return 0
    res = {"protocol": "exp36_v1", "skab": run_skab(args.data), "w3": run_3w(args.data)}
    res["targets"] = verdict(res)
    text = json.dumps(res, indent=2, default=str)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
