"""exp40: regime-aware anomaly engine and stuck exemptions on SKAB and Petrobras 3W (README.md).

Implements the frozen protocol exactly (issue #102). Data stays local (never committed). Without
the data it prints SKIP and exits 0. ``--check`` only loads data, builds the splits and fits the
models on the TRAINING split; it never scans calibration or test data. Full mode writes a JSON
result to ``--out`` (default: the system temp folder, never the repo) and prints the metrics table.
Arm B = new engine (targets); arm A = exp36 configuration on the same splits (reported only).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.request
from dataclasses import replace
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "exp36_anomaly_public"))
from crosscut_anomaly.config import AnomalyConfig, load_config  # noqa: E402
from crosscut_anomaly.detect import scan, scan_regimes  # noqa: E402
from crosscut_anomaly.pca_model import (  # noqa: E402
    PcaModel,
    RegimeModelSet,
    fit_from_config,
    fit_regimes,
    regime_keys,
)
from run_exp36 import (  # noqa: E402
    BASE,
    BIN_3W,
    EVENT_CLASSES,
    SKAB_TAGS,
    TARGETS,
    ramp_stats,
    read_skab,
)

W3_COMMIT = "c86cc7c70063646910be7292de8a54a6fb2a8399"
W3_URL = f"https://raw.githubusercontent.com/petrobras/3W/{W3_COMMIT}/"
DRAW_SEED = 102
DRAW_COUNTS = {0: 24, 4: 10, 7: 6, 3: 6}  # class -> files drawn (protocol order)
REGIME_TAG, SP_LIKE_3W = "ABER-CKP", ["ABER-CKGL", "ABER-CKP"]
MIN_ROWS_3W, QUANTUM_3W = 360, 10.0
SPLIT_SKAB = (0.30, 0.50)  # quiet test [0, .3), calibration [.3, .5), train [.5, 1)
NON_TAGS = ("class", "state", "timestamp")
DEFAULT_OUT = Path(tempfile.gettempdir()) / "exp40_result.json"


# ---------------------------------------------------------------- engine wrappers
def make_cfg(name: str, tags: list[str], period_s: float, **extra) -> AnomalyConfig:
    """Frozen base configuration (as exp36) plus optional ``regimes`` / ``setpoint_like``."""
    return load_config({**BASE, "id": name, "tags": tags, "sample_period_s": period_s, **extra})


def strip_exemptions(model: PcaModel) -> PcaModel:
    """Arm A: remove the training evidence of the stuck exemptions (exp36 behaviour)."""
    return replace(model, stuck_runs=(), stuck_profiles=())


def scan_rows(model: PcaModel | RegimeModelSet, config: AnomalyConfig, x: np.ndarray):
    """Scan one record; return the ScanResult and a per-row mask of unscored rows."""
    t = np.arange(len(x)) * config.sample_period_s
    if isinstance(model, RegimeModelSet):
        result = scan_regimes(model, t, x, config=config)
        keys = regime_keys(x, config)
        return result, np.array([k not in model.models for k in keys], dtype=bool)
    return scan(model, t, x, config=config), np.zeros(len(x), dtype=bool)


def score_rows(result, unscored: np.ndarray, quiet: np.ndarray, onset: int | None) -> dict:
    """Per-record counts for F1, F2, D1, D2 and the unscored-row bookkeeping."""
    events = result.events
    inside = np.zeros(len(quiet), dtype=bool)
    for e in events:
        inside[e.start_index : e.end_index + 1] = True
    later = [e.start_index for e in events if onset is not None and e.start_index >= onset]
    return {
        "rows": len(quiet), "rows_unscored": int(unscored.sum()),
        "quiet_bins": int(quiet.sum()), "quiet_unscored": int((quiet & unscored).sum()),
        "alarm_quiet_bins": int((inside & quiet).sum()),
        "fa_events": sum(bool(quiet[e.start_index]) for e in events),
        "stuck_events": sum(e.kind == "stuck" for e in events),
        "pca_events": sum(e.kind == "pca" for e in events),
        "has_onset": onset is not None,
        "onset_unscored": bool(onset is not None and unscored[onset]),
        "event_rows": len(quiet) if onset is not None else 0,
        "event_rows_unscored": int(unscored.sum()) if onset is not None else 0,
        "delay_bins": (min(later) - onset) if later else None,
        "exemptions": dict(result.stuck_exemptions),
    }


def _share(num: int, den: int) -> float | None:
    """Ratio or None when the denominator is zero."""
    return num / den if den else None


def pool(rows: list[dict], period_s: float) -> dict:
    """Pooled F1, F2 (all and scored-only), D1, D2 and the reported-only unscored shares."""
    keys = [k for k, v in rows[0].items() if isinstance(v, int | bool)] if rows else []
    s = {k: sum(r[k] for r in rows) for k in keys}
    quiet = s.get("quiet_bins", 0)
    delays = [r["delay_bins"] for r in rows if r["delay_bins"] is not None]
    exempt: dict[str, int] = {}
    for r in rows:
        for reason, n in r["exemptions"].items():
            exempt[reason] = exempt.get(reason, 0) + n
    days = quiet * period_s / 86400.0
    scored_quiet = quiet - s.get("quiet_unscored", 0)
    return {
        "files": len(rows), "quiet_hours": quiet * period_s / 3600.0,
        "fa_events": s.get("fa_events", 0), "fa_per_day": _share(s.get("fa_events", 0), days),
        "alarm_share_quiet": _share(s.get("alarm_quiet_bins", 0), quiet),
        "alarm_share_quiet_scored_only": _share(s.get("alarm_quiet_bins", 0), scored_quiet),
        "stuck_events": s.get("stuck_events", 0), "pca_events": s.get("pca_events", 0),
        "stuck_exemptions": exempt,
        "event_files": s.get("has_onset", 0), "detected": len(delays),
        "onset_unscored": s.get("onset_unscored", 0),
        "detection_rate": _share(len(delays), s.get("has_onset", 0)),
        "median_delay_s": float(np.median(delays)) * period_s if delays else None,
        "rows_unscored_share": _share(s.get("rows_unscored", 0), s.get("rows", 0)),
        "quiet_unscored_share": _share(s.get("quiet_unscored", 0), quiet),
        "event_file_unscored_share": _share(
            s.get("event_rows_unscored", 0), s.get("event_rows", 0)),
    }


def regime_counts(x: np.ndarray, config: AnomalyConfig, model: RegimeModelSet) -> dict:
    """Training rows per regime key and which keys got a model (check output)."""
    counts: dict[str, int] = {}
    for key in regime_keys(x, config):
        if key is not None:
            counts[key] = counts.get(key, 0) + 1
    return {"rows": counts, "fitted": sorted(model.models),
            "under_trained": sorted(set(counts) - set(model.models))}


# ---------------------------------------------------------------- SKAB
def skab_splits(free: np.ndarray) -> dict[str, np.ndarray]:
    """Time-reversed split of anomaly-free.csv: quiet test, calibration, train (by rows)."""
    a, b = (int(f * len(free)) for f in SPLIT_SKAB)
    return {"quiet": free[:a], "calibration": free[a:b], "train": free[b:]}


def skab_arms(train: np.ndarray) -> dict[str, tuple[PcaModel, AnomalyConfig]]:
    """Arm B (stuck exemptions on, one regime) and arm A (exp36 configuration)."""
    config = make_cfg("skab_v1", SKAB_TAGS, 1.0)
    model = fit_from_config(train, config)
    return {"B": (model, config), "A": (strip_exemptions(model), config)}


def skab_files(data: Path) -> list[Path]:
    """The 34 SKAB files other than anomaly-free.csv, sorted."""
    return [p for p in sorted(data.glob("*/*.csv")) if p.parent.name != "anomaly-free"]


def run_skab(folder: Path, check: bool) -> dict:
    """SKAB: new split, both arms; in check mode only the split sizes and the fit."""
    data = folder / "skab" / "data"
    free, _ = read_skab(data / "anomaly-free" / "anomaly-free.csv")
    sp = skab_splits(free)
    arms = skab_arms(sp["train"])
    sizes = {k: len(v) for k, v in sp.items()}
    if check:
        return {"split_rows": sizes, "regimes": "none (single model)",
                "event_files": len(skab_files(data))}
    out: dict = {"split_rows": sizes}
    for arm, (model, config) in arms.items():
        quiet = [score_arm(model, config, sp["quiet"], np.ones(len(sp["quiet"]), bool), None)]
        calx = sp["calibration"]
        cal = [score_arm(model, config, calx, np.ones(len(calx), bool), None)]
        rows = quiet + [score_skab_file(model, config, p) for p in skab_files(data)]
        out[arm] = {**pool(rows, 1.0), "calibration": pool(cal, 1.0)}
    return out


def score_arm(model, config, x: np.ndarray, quiet: np.ndarray, onset: int | None) -> dict:
    """Scan ``x`` with one arm and score it."""
    result, unscored = scan_rows(model, config, x)
    return score_rows(result, unscored, quiet, onset)


def score_skab_file(model, config, path: Path) -> dict:
    """One SKAB event file: quiet before the first anomaly == 1, onset = that sample."""
    x, a = read_skab(path)
    onset = int(np.flatnonzero(a == 1)[0])
    return score_arm(model, config, x, np.arange(len(x)) < onset, onset)


# ---------------------------------------------------------------- 3W draw and loading
def read_list(path: Path) -> list[str]:
    """Non-empty stripped lines of a text file."""
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def class_of(rel: str) -> int:
    """3W class of a listing entry ``dataset/<class>/<file>``."""
    return int(rel.split("/")[1])


def draw_3w(folder: Path) -> dict[int, list[str]]:
    """Protocol draw: per class a fresh default_rng(102) over the sorted real-well pool."""
    listing = read_list(folder / "w3_files.txt")
    exp36 = {r for r in read_list(folder / "w3_sel.txt") if r.endswith(".parquet")}
    drawn = {}
    for cls, want in DRAW_COUNTS.items():
        pool_ = sorted(r for r in listing
                       if "/WELL-" in r and class_of(r) == cls and r not in exp36)
        take = min(want, len(pool_))
        idx = np.random.default_rng(DRAW_SEED).choice(len(pool_), size=take, replace=False)
        drawn[cls] = [pool_[i] for i in sorted(idx)]
    return drawn


def fetch(root: Path, rel: str, download: bool) -> Path:
    """Local path of a 3W file; download it from the pinned GitHub commit if missing."""
    path = root / rel
    if not path.is_file():
        if not download:
            raise FileNotFoundError(f"{path} missing and --no-download given")
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(W3_URL + rel, timeout=120) as resp:  # noqa: S310
            path.write_bytes(resp.read())
    return path


def load_3w(path: Path) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """10 s block means per column, class labels by bin x sample, bool 'state == 2 in every
    sample of the bin' (all True if the file has no state column). Copy of exp36 with state."""
    t = pq.read_table(path)
    n = t.num_rows // BIN_3W * BIN_3W
    cols = {}
    for c in (c for c in t.column_names if c not in NON_TAGS):
        v = t[c].to_numpy(zero_copy_only=False).astype(float)[:n].reshape(-1, BIN_3W)
        finite = np.isfinite(v)
        total = np.where(finite, v, 0.0).sum(axis=1)
        cols[c] = np.where(finite.any(axis=1), total / np.maximum(finite.sum(axis=1), 1), np.nan)
    cls = t["class"].to_numpy(zero_copy_only=False).astype(float)[:n].reshape(-1, BIN_3W)
    if "state" in t.column_names:
        st = t["state"].to_numpy(zero_copy_only=False).astype(float)[:n].reshape(-1, BIN_3W)
        # Real wells carry state 0 (or NaN) only, never 2; the state == 2 rule of the protocol
        # then cannot apply and the file falls back to class 0 only (as exp36). README note.
        ok = (st == 2).all(axis=1) if (st == 2).any() else np.ones(len(cls), bool)
    else:
        ok = np.ones(len(cls), bool)
    return cols, cls, ok


def quiet_onset(cls: np.ndarray, ok: np.ndarray, event: int) -> tuple[np.ndarray, int | None]:
    """Quiet = every sample class 0 and state 2; onset = first bin with event or 100+event."""
    quiet = (cls == 0).all(axis=1) & ok
    hit = np.flatnonzero(np.isin(cls, (event, 100 + event)).any(axis=1)) if event else []
    return quiet, (int(hit[0]) if len(hit) else None)


def well_of(rel: str) -> str:
    """Well id (name prefix before the first underscore)."""
    return rel.split("/")[-1].split("_")[0]


# ---------------------------------------------------------------- 3W per-well plan
def pca_tags(loaded: list[dict], train_x: dict[str, np.ndarray]) -> list[str]:
    """Columns finite in >= 99 % of the bins of every file and not constant in training rows."""
    tags = []
    for c in sorted(loaded[0]["cols"]):
        if c == REGIME_TAG:
            continue
        ok = all(np.isfinite(f["cols"][c]).mean() >= 0.99 for f in loaded)
        v = train_x[c]
        if ok and np.isfinite(v).all() and np.ptp(v) > 0:
            tags.append(c)
    return tags


def plan_well(well: str, files: list[tuple[int, str, Path]]) -> tuple[dict | None, str | None]:
    """Split one well (None + reason if skipped). ``files`` = (class, rel, path)."""
    zeros = sorted((f for f in files if f[0] == 0), key=lambda f: f[1])
    if len(zeros) < 3:
        return None, f"{len(zeros)} class 0 files (< 3)"
    loaded = []
    for cls, rel, path in files:
        cols, labels, ok = load_3w(path)
        loaded.append({"cls": cls, "rel": rel, "cols": cols, "labels": labels, "ok": ok})
    by_rel = {f["rel"]: f for f in loaded}
    train_rel = [z[1] for z in zeros[:-2]]
    cal_rel, last_rel = zeros[-2][1], zeros[-1][1]
    mask = {r: (by_rel[r]["labels"] == 0).all(axis=1) & by_rel[r]["ok"] for r in train_rel}
    train_cols = {c: np.concatenate([by_rel[r]["cols"][c][mask[r]] for r in train_rel])
                  for c in by_rel[train_rel[0]]["cols"]}
    if len(next(iter(train_cols.values()))) < MIN_ROWS_3W:
        return None, "fewer than min_rows training bins (class 0 and state 2)"
    tags = pca_tags(loaded, train_cols)
    if len(tags) < 3:
        return None, f"only {len(tags)} usable PCA tags"
    return {"well": well, "tags": tags, "train_cols": train_cols, "files": by_rel,
            "cal": cal_rel, "last": last_rel, "train_files": train_rel}, None


def stack(cols: dict[str, np.ndarray], names: list[str]) -> np.ndarray:
    """Columns by name as a samples-by-tags matrix."""
    return np.column_stack([cols[n] for n in names])


def fit_well(plan: dict) -> dict:
    """Fit arm B (regimes) and arm A on the training rows of a planned well."""
    tags = plan["tags"]
    cfg_b = make_cfg(
        f"w3_{plan['well']}_B", tags + [REGIME_TAG], float(BIN_3W),
        regimes={"by": [REGIME_TAG], "min_rows": MIN_ROWS_3W, "quantum": {REGIME_TAG: QUANTUM_3W}},
        setpoint_like=SP_LIKE_3W)
    cfg_a = make_cfg(f"w3_{plan['well']}_A", tags, float(BIN_3W))
    tr = plan["train_cols"]
    set_b = fit_regimes(stack(tr, tags + [REGIME_TAG]), cfg_b)
    model_a = strip_exemptions(fit_from_config(stack(tr, tags), cfg_a))
    info = regime_counts(stack(tr, tags + [REGIME_TAG]), cfg_b, set_b)
    return {"B": (set_b, cfg_b, tags + [REGIME_TAG]), "A": (model_a, cfg_a, tags), "info": info}


def score_well(plan: dict, fitted: dict) -> dict:
    """Score calibration, quiet-test and event files of a well, per arm."""
    out = {}
    test_rel = [plan["last"]] + [r for r, f in plan["files"].items() if f["cls"] in EVENT_CLASSES]
    for arm in ("B", "A"):
        model, config, names = fitted[arm]
        rows = [score_file_3w(model, config, names, plan["files"][r]) for r in test_rel]
        cal = [score_file_3w(model, config, names, plan["files"][plan["cal"]])]
        out[arm] = {"rows": rows, "cal": cal}
    return out


def score_file_3w(model, config, names: list[str], f: dict) -> dict:
    """Scan one 3W file; quiet = class 0 and state 2, onset only for event classes."""
    event = f["cls"] if f["cls"] in EVENT_CLASSES else 0
    quiet, onset = quiet_onset(f["labels"], f["ok"], event)
    return score_arm(model, config, stack(f["cols"], names), quiet, onset)


def run_3w(folder: Path, check: bool, download: bool) -> dict:
    """3W: draw, per-well splits and fits; in check mode stop after the fits."""
    root = folder / "w3"
    drawn = draw_3w(folder)
    by_well: dict[str, list[tuple[int, str, Path]]] = {}
    for cls, rels in drawn.items():
        for rel in rels:
            by_well.setdefault(well_of(rel), []).append((cls, rel, fetch(root, rel, download)))
    skipped, wells = {}, {}
    for well, files in sorted(by_well.items()):
        plan, why = plan_well(well, files)
        if plan is None:
            skipped[well] = why
            continue
        fitted = fit_well(plan)
        if not fitted["info"]["fitted"]:
            skipped[well] = f"no regime reached min_rows {MIN_ROWS_3W} ({REGIME_TAG} missing?)"
            continue
        wells[well] = {"train_files": len(plan["train_files"]), "tags": len(plan["tags"]),
                       "train_rows": int(len(next(iter(plan["train_cols"].values())))),
                       "regimes": fitted["info"], "plan": plan, "fitted": fitted}
    out = {"draw": drawn, "skipped_wells": skipped,
           "wells": {w: {k: v for k, v in d.items() if k not in ("plan", "fitted")}
                     for w, d in wells.items()}}
    if check:
        return out
    arms = {"B": [], "A": []}
    cal = {"B": [], "A": []}
    for w, d in wells.items():
        res = score_well(d["plan"], d["fitted"])
        for arm in arms:
            arms[arm] += res[arm]["rows"]
            cal[arm] += res[arm]["cal"]
        share = pool(res["B"]["rows"], BIN_3W)["rows_unscored_share"]
        out["wells"][w]["rows_unscored_share"] = share
    for arm in arms:
        out[arm] = {**pool(arms[arm], BIN_3W), "calibration": pool(cal[arm], BIN_3W)}
    out["ramp"] = ramp_total(root, drawn, download)
    return out


def ramp_total(root: Path, drawn: dict[int, list[str]], download: bool) -> dict:
    """Ramp-warning precision over all drawn files (same rule as exp36)."""
    paths = [fetch(root, r, download) for rels in drawn.values() for r in rels]
    parts = [ramp_stats(load_3w(p)[0]) for p in paths]
    r = {k: sum(p[k] for p in parts) for k in ("spans", "hit", "gaps")}
    r["precision"] = r["hit"] / r["spans"] if r["spans"] else None
    return r


# ---------------------------------------------------------------- verdict and output
def verdict(skab: dict, w3: dict, ramp: dict) -> dict:
    """Frozen targets evaluated on arm B (None = not evaluable)."""
    def ok(v, test):
        return None if v is None else bool(test(v))
    s, w = skab["B"], w3["B"]
    return {
        "F1_skab": ok(s["fa_per_day"], lambda v: v <= TARGETS["F1"]),
        "F1_3w": ok(w["fa_per_day"], lambda v: v <= TARGETS["F1"]),
        "F2_skab": ok(s["alarm_share_quiet"], lambda v: v <= TARGETS["F2"]),
        "F2_3w": ok(w["alarm_share_quiet"], lambda v: v <= TARGETS["F2"]),
        "D1_skab": ok(s["detection_rate"], lambda v: v >= TARGETS["D1"]),
        "D1_3w": ok(w["detection_rate"], lambda v: v >= TARGETS["D1"]),
        "D2_skab": ok(s["median_delay_s"], lambda v: v <= TARGETS["D2_skab_s"]),
        "D2_3w": ok(w["median_delay_s"], lambda v: v <= TARGETS["D2_3w_min"] * 60.0),
        "R1": ok(ramp["precision"], lambda v: v >= TARGETS["R1"]),
    }


def fmt(v) -> str:
    """Compact number or n/a."""
    return "n/a" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def print_table(res: dict) -> None:
    """Metrics of both arms against the frozen targets."""
    t = res["targets"]
    print("metric            target        skab B   skab A    3w B     3w A    verdict(B skab/3w)")
    spec = [("F1 fa/day", "fa_per_day", "<= 3", "F1"),
            ("F2 alarm share", "alarm_share_quiet", "<= 0.02", "F2"),
            ("D1 detection", "detection_rate", ">= 0.70", "D1"),
            ("D2 delay s", "median_delay_s", "<=60s/15min", "D2")]
    for label, key, target, tid in spec:
        cells = [fmt(res[d][a][key]) for d in ("skab", "w3") for a in ("B", "A")]
        print(f"{label:<16} {target:<12} {cells[0]:>8} {cells[1]:>8} {cells[2]:>8} {cells[3]:>8}"
              f"    {t[f'{tid}_skab']}/{t[f'{tid}_3w']}")
    print(f"R1 ramp precision >= 0.50: {fmt(res['w3']['ramp']['precision'])} -> {t['R1']}")


def print_check(res: dict) -> None:
    """Check-mode report: split sizes, regimes found and their training row counts."""
    s = res["skab"]
    print(f"SKAB split rows {s['split_rows']}, regimes: {s['regimes']}, "
          f"event files {s['event_files']}")
    w = res["w3"]
    print("3W drawn per class:", {c: len(v) for c, v in w["draw"].items()})
    for well, why in w["skipped_wells"].items():
        print(f"  skip {well}: {why}")
    for well, d in w["wells"].items():
        r = d["regimes"]
        print(f"  {well}: train files {d['train_files']}, train rows {d['train_rows']}, "
              f"PCA tags {d['tags']}, regimes fitted {len(r['fitted'])}, "
              f"under-trained {len(r['under_trained'])}")
        for key, n in sorted(r["rows"].items()):
            tag = "(fitted)" if key in r["fitted"] else "(under-trained)"
            print(f"      key {key}: {n} rows {tag}")


def main(argv: list[str] | None = None) -> int:
    """Run the protocol (or only ``--check``); SKIP with exit 0 when the data is missing."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, required=True, help="folder with skab/ and w3/")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="result JSON (default: temp)")
    p.add_argument("--check", action="store_true", help="splits + training fits only, no scoring")
    p.add_argument("--no-download", action="store_true", help="never fetch missing 3W files")
    a = p.parse_args(argv)
    need = [a.data / "skab" / "data", a.data / "w3" / "dataset", a.data / "w3_files.txt",
            a.data / "w3_sel.txt"]
    if not all(n.exists() for n in need):
        print(f"SKIP exp40: skab/data, w3/dataset, w3_files.txt, w3_sel.txt not all in {a.data}")
        return 0
    res = {"protocol": "exp40_v1", "skab": run_skab(a.data, a.check),
           "w3": run_3w(a.data, a.check, not a.no_download)}
    if a.check:
        print_check(res)
        return 0
    res["targets"] = verdict(res["skab"], res["w3"], res["w3"]["ramp"])
    a.out.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print_table(res)
    print(f"result JSON: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
