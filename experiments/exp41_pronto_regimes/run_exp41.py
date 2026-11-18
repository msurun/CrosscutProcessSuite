"""exp41: regime-aware anomaly engine and stuck exemptions on PRONTO process data (README.md).

Implements the frozen leave-one-day-out protocol (issue #102); data stays local. Without the data
it prints SKIP and exits 0. ``--check`` loads data, builds the splits and fits the models on the
TRAINING split only (no calibration or test scoring). Full mode writes the JSON result to ``--out``
(default: system temp folder) and prints the metrics table. Arm B = new engine, arm A = exp38
configuration trained on the pooled rows (reported only). Helpers come from exp40 / exp38 / exp36.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pyarrow.csv as pacsv

HERE = Path(__file__).resolve().parent.parent
for sub in ("exp40_anomaly_regimes_public", "exp38_pronto_public"):
    sys.path.insert(0, str(HERE / sub))
from crosscut_anomaly.pca_model import fit_from_config, fit_regimes  # noqa: E402
from run_exp38 import BLOCKS, CUT_S, FILES, TARGETS, block_rows  # noqa: E402
from run_exp40 import (  # noqa: E402
    fmt,
    make_cfg,
    pool,
    regime_counts,
    scan_rows,
    score_rows,
    strip_exemptions,
)

DEFAULT_OUT = Path(tempfile.gettempdir()) / "exp41_result.json"
N_MEAS = 19  # measurement columns 1..19 of the csv (column 0 is the timestamp)
# Set-point columns of the csv (0 = TIMESTAMP), fixed from the header names: the air-flow loops
# FIC302 / FIC301 and the water-flow loops FIC102 / FIC101 (which loop is active changes by block).
SP_COLUMNS = {"sp_air_fic302": 21, "sp_air_fic301": 24,
              "sp_water_fic102": 27, "sp_water_fic101": 30}
SP_QUANTUM = {"sp_air_fic302": 10.0, "sp_air_fic301": 10.0,
              "sp_water_fic102": 0.1, "sp_water_fic101": 0.1}
MIN_ROWS = 120


def read_day(path: Path) -> tuple[np.ndarray, int]:
    """19 measurements + 4 set points by rows (exp38 read_day plus set points), start s."""
    opts = pacsv.ParseOptions(invalid_row_handler=lambda _row: "skip")
    t = pacsv.read_csv(path, read_options=pacsv.ReadOptions(skip_rows=2), parse_options=opts)
    idx = list(range(1, N_MEAS + 1)) + list(SP_COLUMNS.values())
    cols = [t.column(k).to_numpy(zero_copy_only=False).astype(float) for k in idx]
    hh, mm = t.column(0)[0].as_py().split()[1].split(":")
    return np.column_stack(cols), int(hh) * 3600 + int(mm) * 60


def day_segments(rows: list[tuple]) -> tuple[list[tuple[int, int]], tuple[int, int] | None]:
    """N blocks after the first CUT_S s as (lo, hi), and the last N block by time (calibration)."""
    seg = [(i + CUT_S, j) for kind, _n, i, j, _a, _w in rows if kind == "N" and j > i + CUT_S]
    return seg, (max(seg) if seg else None)


def prepare_days(data: Path) -> dict[str, dict]:
    """Read the three days: matrix, block rows, N segments and calibration segment."""
    days = {}
    for day, rel in FILES.items():
        x, start_s = read_day(data / rel)
        rows = block_rows(BLOCKS[day], start_s, len(x))
        seg, cal = day_segments(rows)
        days[day] = {"x": x, "rows": rows, "seg": seg, "cal": cal}
    return days


def train_matrix(days: dict[str, dict], test_day: str) -> np.ndarray:
    """N blocks of the other two days without each day's calibration (last N) block."""
    parts = []
    for day, d in days.items():
        if day == test_day:
            continue
        parts += [d["x"][a:b] for a, b in d["seg"] if (a, b) != d["cal"]]
    return np.vstack(parts)


def fit_day(train: np.ndarray) -> dict | None:
    """PCA tags (finite, not constant in training), arm B regime set and arm A model."""
    meas = train[:, :N_MEAS]
    tags = [i for i in range(N_MEAS) if np.isfinite(meas[:, i]).all() and np.ptp(meas[:, i]) > 0]
    if len(tags) < 3:
        return None
    sp_names = list(SP_COLUMNS)
    sp_idx = [N_MEAS + k for k in range(len(sp_names))]
    names_b = [f"c{i}" for i in tags] + sp_names
    cfg_b = make_cfg("pronto_B", names_b, 1.0,
                     regimes={"by": sp_names, "min_rows": MIN_ROWS, "quantum": SP_QUANTUM},
                     setpoint_like=sp_names)
    cfg_a = make_cfg("pronto_A", [f"c{i}" for i in tags], 1.0)
    cols_b = tags + sp_idx
    set_b = fit_regimes(train[:, cols_b], cfg_b)
    model_a = strip_exemptions(fit_from_config(train[:, tags], cfg_a))
    return {"tags": tags, "B": (set_b, cfg_b, cols_b), "A": (model_a, cfg_a, tags),
            "info": regime_counts(train[:, cols_b], cfg_b, set_b)}


def score_block(res, unscored, rows: list[tuple]) -> dict:
    """Quiet (N after CUT_S), fault (F) and slugging (S) statistics of one scanned day."""
    ev = res.events
    starts = np.array([e.start_index for e in ev])
    inside = np.zeros(len(unscored), dtype=bool)
    for e in ev:
        inside[e.start_index : e.end_index + 1] = True
    quiet = np.zeros(len(unscored), dtype=bool)
    out = {"quiet": [], "F": [], "S": []}
    for kind, name, i, j, _a, _w in rows:
        if kind == "N":
            quiet[i + CUT_S : j] = True
            continue
        hit = starts[(starts >= i) & (starts < j)]
        out[kind].append({"name": name, "n": j - i, "inside": int(inside[i:j].sum()),
                          "unscored": int(unscored[i:j].sum()),
                          "start_unscored": bool(unscored[i]),
                          "delay_s": int(hit.min() - i) if len(hit) else None})
    out["quiet"] = score_rows(res, unscored, quiet, None)
    return out


def scan_day(arm: tuple, d: dict) -> tuple:
    """Scan the whole test day with one arm; return ScanResult and unscored mask."""
    model, config, cols = arm
    return scan_rows(model, config, d["x"][:, cols])


def scan_cal(arm: tuple, d: dict) -> dict:
    """Calibration block (not in training): quiet after CUT_S, reported only."""
    model, config, cols = arm
    a, b = d["cal"]
    x = d["x"][a:b][:, cols]
    res, unscored = scan_rows(model, config, x)
    return score_rows(res, unscored, np.ones(len(x), bool), None)


def block_pool(blocks: list[dict]) -> dict:
    """Detection rate, delay and inside share over F or S blocks of all days."""
    delays = [b["delay_s"] for b in blocks if b["delay_s"] is not None]
    n = sum(b["n"] for b in blocks)
    return {"blocks": len(blocks), "detected": len(delays),
            "start_unscored": sum(b["start_unscored"] for b in blocks),
            "detection_rate": len(delays) / len(blocks) if blocks else None,
            "median_delay_s": float(np.median(delays)) if delays else None,
            "inside_share": sum(b["inside"] for b in blocks) / n if n else None,
            "unscored_share": sum(b["unscored"] for b in blocks) / n if n else None}


def run_day(days: dict, day: str, check: bool) -> dict:
    """Fit on the other two days; in full mode also score the test day and calibration."""
    train = train_matrix(days, day)
    fit = fit_day(train)
    if fit is None:
        return {"skipped": "fewer than 3 PCA tags"}
    out = {"train_rows": len(train), "tags": len(fit["tags"]), "regimes": fit["info"]}
    if check:
        return out
    others = [days[k] for k in days if k != day]
    out["calibration"] = {a: pool([scan_cal(fit[a], d) for d in others], 1.0) for a in ("B", "A")}
    out["scored"] = {}
    for arm in ("B", "A"):
        res, unscored = scan_day(fit[arm], days[day])
        out["scored"][arm] = {**score_block(res, unscored, days[day]["rows"]),
                              "exemptions": dict(res.stuck_exemptions),
                              "stuck": res.n_stuck_events, "pca": res.n_pca_events}
    return out


def summarize(res: dict) -> dict:
    """Pool the test days per arm and evaluate the frozen targets on arm B."""
    out = {}
    for arm in ("B", "A"):
        sc = [r["scored"][arm] for r in res.values() if "scored" in r]
        out[arm] = {"quiet": pool([s["quiet"] for s in sc], 1.0),
                    "fault": block_pool([b for s in sc for b in s["F"]]),
                    "slugging": block_pool([b for s in sc for b in s["S"]])}
    q, f = out["B"]["quiet"], out["B"]["fault"]
    out["targets"] = {
        "F1": None if q["fa_per_day"] is None else q["fa_per_day"] <= TARGETS["F1"],
        "F2": None if q["alarm_share_quiet"] is None else q["alarm_share_quiet"] <= TARGETS["F2"],
        "D1": None if f["detection_rate"] is None else f["detection_rate"] >= TARGETS["D1"],
        "D2": None if f["median_delay_s"] is None else f["median_delay_s"] <= TARGETS["D2_s"],
    }
    return out


def print_table(summary: dict) -> None:
    """Metrics of arm B and arm A against the frozen targets."""
    b, a, t = summary["B"], summary["A"], summary["targets"]
    rows = [("F1 fa/day", "<= 3", b["quiet"]["fa_per_day"], a["quiet"]["fa_per_day"], t["F1"]),
            ("F2 alarm share", "<= 0.02", b["quiet"]["alarm_share_quiet"],
             a["quiet"]["alarm_share_quiet"], t["F2"]),
            ("D1 detection", ">= 0.70", b["fault"]["detection_rate"],
             a["fault"]["detection_rate"], t["D1"]),
            ("D2 delay s", "<= 120", b["fault"]["median_delay_s"],
             a["fault"]["median_delay_s"], t["D2"])]
    print("metric            target     arm B    arm A    met(B)")
    for label, target, vb, va, ok in rows:
        print(f"{label:<16} {target:<9} {fmt(vb):>8} {fmt(va):>8}    {ok}")
    print("R1 not applicable (no NaN gaps)")


def print_check(res: dict) -> None:
    """Check-mode report: split sizes, regimes found and their training row counts."""
    for day, r in res.items():
        if "skipped" in r:
            print(f"{day}: skipped ({r['skipped']})")
            continue
        g = r["regimes"]
        print(f"{day}: train rows {r['train_rows']}, PCA tags {r['tags']}, "
              f"regimes fitted {len(g['fitted'])}, under-trained {len(g['under_trained'])}")
        for key, n in sorted(g["rows"].items()):
            tag = "(fitted)" if key in g["fitted"] else "(under-trained)"
            print(f"    key {key}: {n} rows {tag}")


def main(argv: list[str] | None = None) -> int:
    """Run the protocol (or only ``--check``); SKIP with exit 0 when a data file is missing."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, required=True, help="PRONTO case-study tree")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="result JSON (default: temp)")
    p.add_argument("--check", action="store_true", help="splits + training fits only, no scoring")
    a = p.parse_args(argv)
    if not all((a.data / f).is_file() for f in FILES.values()):
        print(f"SKIP exp41: PRONTO process-data files not found in {a.data}")
        return 0
    days = prepare_days(a.data)
    res = {day: run_day(days, day, a.check) for day in days}
    if a.check:
        print_check(res)
        return 0
    summary = summarize(res)
    a.out.write_text(json.dumps({"protocol": "exp41_v1", "days": res, "summary": summary},
                                indent=2, default=str), encoding="utf-8")
    print_table(summary)
    print(f"result JSON: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
