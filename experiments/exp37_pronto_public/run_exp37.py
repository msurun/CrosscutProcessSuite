"""exp37: anomaly engine on PRONTO multiphase flow process data (protocol: README.md).

Reads local copies of the public data (never committed), applies the frozen protocol once and
prints a JSON result; without the data it prints SKIP and exits 0. Issue #87, sibling of exp36.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow.csv as pacsv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "exp36_anomaly_public"))
from crosscut_anomaly.detect import scan  # noqa: E402
from crosscut_anomaly.pca_model import fit_from_config  # noqa: E402
from run_exp36 import make_config  # noqa: E402

CUT_S = 120  # first seconds of a normal block that are not quiet
FIT_SHARE = 0.70
TARGETS = {"F1": 3.0, "F2": 0.02, "D1": 0.70, "D2_s": 120.0}

FILES = {
    "0907": "C1 Air Blockage/Test2/Process Data/0907Testday2.csv",
    "0911": "C2 Air Leakage/Test5/Process Data/0911Testday3.csv",
    "0912": "C0 Normal and Slugging conditions/Test10/Process Data/0912Testday4.csv",
}
# day -> [(kind, name, start, end, air, water)]; times are Excel day fractions of the operation log
BLOCKS = {
    "0907": [
        ("N", "T1_90", 0.5440, 0.5597, 120, 0.1),
        ("F", "T2_80", 0.5597, 0.5681, 120, 0.1), ("F", "T2_70", 0.5681, 0.5722, 120, 0.1),
        ("F", "T2_60", 0.5722, 0.5778, 120, 0.1), ("F", "T2_50", 0.5778, 0.5833, 120, 0.1),
        ("F", "T2_40", 0.5833, 0.5889, 120, 0.1), ("F", "T2_30", 0.5889, 0.5951, 120, 0.1),
        ("F", "T2_20", 0.5951, 0.6014, 120, 0.1), ("F", "T2_10", 0.6014, 0.6069, 120, 0.1),
        ("N", "T3_90", 0.6100, 0.6181, 150, 0.5),
        ("F", "T3_80", 0.6181, 0.6236, 150, 0.5), ("F", "T3_70", 0.6236, 0.6292, 150, 0.5),
        ("F", "T3_60", 0.6292, 0.6347, 150, 0.5), ("F", "T3_50", 0.6347, 0.6403, 150, 0.5),
        ("F", "T3_40", 0.6403, 0.6458, 150, 0.5), ("F", "T3_30", 0.6458, 0.6514, 150, 0.5),
        ("F", "T3_20", 0.6514, 0.6569, 150, 0.5), ("F", "T3_10", 0.6569, 0.6625, 150, 0.5),
        ("N", "T3_back90", 0.6625, 0.6667, 150, 0.5),
        ("F", "T4_10", 0.6667, 0.6736, 150, 0.5), ("F", "T4_20", 0.6736, 0.6771, 150, 0.5),
        ("F", "T4_30", 0.6771, 0.6819, 150, 0.5), ("F", "T4_15", 0.6819, 0.6861, 150, 0.5),
        ("F", "T4_25", 0.6861, 0.6896, 150, 0.5), ("F", "T4_40", 0.6896, 0.6931, 150, 0.5),
        ("F", "T4_90", 0.6931, 0.7000, 150, 0.5),
    ],
    "0911": [
        ("N", "T5_0", 0.4410, 0.4444, 120, 0.1),
        ("F", "T5_5", 0.4444, 0.4514, 120, 0.1), ("F", "T5_10", 0.4514, 0.4604, 120, 0.1),
        ("F", "T5_15", 0.4604, 0.4778, 120, 0.1),
        ("N", "T6_0", 0.4830, 0.4965, 150, 0.5),
        ("F", "T6_5", 0.4965, 0.5021, 150, 0.5), ("F", "T6_10", 0.5021, 0.5090, 150, 0.5),
        ("F", "T6_15", 0.5090, 0.5160, 150, 0.5), ("F", "T6_20", 0.5160, 0.5229, 150, 0.5),
        ("F", "T6_25", 0.5229, 0.5264, 150, 0.5),
        ("N", "T7_0", 0.5360, 0.5465, 120, 0.1),
        ("F", "T7_5", 0.5465, 0.5486, 120, 0.1), ("F", "T7_10", 0.5486, 0.5542, 120, 0.1),
        ("F", "T7_15", 0.5542, 0.5597, 120, 0.1), ("F", "T7_20", 0.5597, 0.5646, 120, 0.1),
        ("F", "T7_30", 0.5646, 0.5722, 120, 0.1), ("F", "T7_60", 0.6222, 0.6264, 120, 0.1),
        ("F", "T8_10", 0.6319, 0.6389, 150, 0.5), ("F", "T8_20", 0.6389, 0.6458, 150, 0.5),
        ("F", "T8_30", 0.6458, 0.6507, 150, 0.5), ("F", "T8_40", 0.6507, 0.6569, 150, 0.5),
        ("F", "T8_45", 0.6569, 0.6611, 150, 0.5), ("F", "T8_50", 0.6611, 0.6660, 150, 0.5),
        ("F", "T8_60", 0.6660, 0.6730, 150, 0.5),
    ],
    "0912": [
        ("S", "50/0.1", 0.4410, 0.4465, 50, 0.1), ("N", "100/0.1", 0.4465, 0.4514, 100, 0.1),
        ("N", "200/0.1", 0.4514, 0.4569, 200, 0.1), ("N", "200/0.5", 0.4569, 0.4639, 200, 0.5),
        ("N", "100/0.5", 0.4639, 0.4715, 100, 0.5), ("S", "50/0.5", 0.4715, 0.4813, 50, 0.5),
        ("N", "20/3.5", 0.4813, 0.4937, 20, 3.5), ("N", "100/1", 0.5090, 0.5190, 100, 1.0),
        ("S", "50/1", 0.5201, 0.5264, 50, 1.0), ("S", "20/0.5", 0.5264, 0.5340, 20, 0.5),
        ("N", "50/2", 0.5403, 0.5458, 50, 2.0), ("N", "100/2", 0.5458, 0.5542, 100, 2.0),
        ("N", "100/3.5", 0.5542, 0.5604, 100, 3.5), ("N", "50/3.5", 0.5604, 0.5674, 50, 3.5),
    ],
}


def read_day(path: Path) -> tuple[np.ndarray, int]:
    """19 measurement columns by rows and the start second of the file (first timestamp)."""
    opts = pacsv.ParseOptions(invalid_row_handler=lambda _row: "skip")
    t = pacsv.read_csv(path, read_options=pacsv.ReadOptions(skip_rows=2), parse_options=opts)
    cols = [t.column(k).to_numpy(zero_copy_only=False).astype(float) for k in range(1, 20)]
    hh, mm = t.column(0)[0].as_py().split()[1].split(":")
    return np.column_stack(cols), int(hh) * 3600 + int(mm) * 60


def block_rows(blocks: list, start_s: int, n: int) -> list[tuple]:
    """Blocks as (kind, name, first_row, end_row, air, water) clipped to the file."""
    out = []
    for kind, name, a, b, air, water in blocks:
        i, j = round(a * 86400) - start_s, round(b * 86400) - start_s
        if j > 0 and i < n:
            out.append((kind, name, max(i, 0), min(j, n), air, water))
    return out


def score_day(x: np.ndarray, start_s: int, blocks: list) -> dict:
    """Fit on 70 % of the first normal block, scan the day, score quiet, fault, slugging."""
    rows = block_rows(blocks, start_s, len(x))
    first = next(r for r in rows if r[0] == "N")
    n_fit = int(FIT_SHARE * (first[3] - first[2]))
    fit = x[first[2] : first[2] + n_fit]
    tags = [i for i in range(x.shape[1]) if np.isfinite(fit[:, i]).all() and np.ptp(fit[:, i]) > 0]
    config = make_config("pronto_v1", [f"c{i}" for i in tags], 1.0)
    model = fit_from_config(fit[:, tags], config)
    events = scan(model, np.arange(len(x), dtype=float), x[:, tags], config=config).events
    starts = np.array([e.start_index for e in events])
    inside = np.zeros(len(x), dtype=bool)
    for e in events:
        inside[e.start_index : e.end_index + 1] = True
    quiet, detail = [], []
    for kind, name, i, j, air, water in rows:
        if kind == "N":
            lo = first[2] + n_fit if name == first[1] else i + CUT_S
            quiet.append({"name": name, "same_sp": (air, water) == (first[4], first[5]),
                          "n": max(j - lo, 0), "alarm": int(inside[lo:j].sum()),
                          "fa": int(((starts >= lo) & (starts < j)).sum())})
        else:
            hit = starts[(starts >= i) & (starts < j)]
            detail.append({"kind": kind, "name": name, "n": j - i, "inside": int(inside[i:j].sum()),
                           "delay_s": int(hit.min() - i) if len(hit) else None})
    return {"tags": len(tags), "fit_rows": n_fit, "events": len(events),
            "stuck": sum(e.kind == "stuck" for e in events), "quiet": quiet, "blocks": detail}


def quiet_stats(sel: list[dict]) -> dict:
    """Pooled false alarms per extrapolated day and alarm share of quiet samples."""
    n = sum(b["n"] for b in sel)
    fa = sum(b["fa"] for b in sel)
    per_day = fa / (n / 86400.0) if n else None
    return {"quiet_hours": n / 3600.0, "fa_events": fa, "fa_per_day": per_day,
            "alarm_share": sum(b["alarm"] for b in sel) / n if n else None}


def block_stats(days: dict[str, dict], kind: str) -> dict:
    """Detection rate, median delay and inside share over the blocks of one kind."""
    bl = [b for d in days.values() for b in d["blocks"] if b["kind"] == kind]
    delays = [b["delay_s"] for b in bl if b["delay_s"] is not None]
    n = sum(b["n"] for b in bl)
    return {"blocks": len(bl), "detected": len(delays),
            "detection_rate": len(delays) / len(bl) if bl else None,
            "median_delay_s": float(np.median(delays)) if delays else None,
            "inside_share": sum(b["inside"] for b in bl) / n if n else None}


def summarize(days: dict[str, dict]) -> dict:
    """Pool quiet and block results over days: F1, F2, D1, D2 and the targets verdict."""
    q = [b for d in days.values() for b in d["quiet"]]
    res = {"quiet_all": quiet_stats(q),
           "quiet_same_sp": quiet_stats([b for b in q if b["same_sp"]]),
           "quiet_other_sp": quiet_stats([b for b in q if not b["same_sp"]]),
           "fault": block_stats(days, "F"), "slugging": block_stats(days, "S")}
    qa, f = res["quiet_all"], res["fault"]
    res["targets"] = {
        "F1": qa["fa_per_day"] is not None and qa["fa_per_day"] <= TARGETS["F1"],
        "F2": qa["alarm_share"] is not None and qa["alarm_share"] <= TARGETS["F2"],
        "D1": f["detection_rate"] is not None and f["detection_rate"] >= TARGETS["D1"],
        "D2": f["median_delay_s"] is not None and f["median_delay_s"] <= TARGETS["D2_s"],
    }
    return res


def main(argv: list[str] | None = None) -> int:
    """Run the protocol; SKIP (exit 0) when a data file is missing."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="PRONTO case-study tree")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if not all((args.data / f).is_file() for f in FILES.values()):
        print(f"SKIP exp37: PRONTO process-data files not found in {args.data}")
        return 0
    days = {}
    for day, rel in FILES.items():
        x, start_s = read_day(args.data / rel)
        days[day] = score_day(x, start_s, BLOCKS[day])
    res = {"protocol": "exp37_v1", "days": days, "summary": summarize(days)}
    text = json.dumps(res, indent=2, default=str)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
