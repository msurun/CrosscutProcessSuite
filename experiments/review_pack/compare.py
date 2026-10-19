"""Compare the blind reviewer's answers with the automatic worklist of the loops package.

Usage: ``python compare.py answers.csv [--pack-dir out]``. Runs ``analyze_dataset`` on the
pack's CSVs, prints Kendall tau (tau-b) between the reviewer rank and ``priority_rank`` and a
table: tag | reviewer category | automatic next_action code | author's key action.
No pass/fail verdict is given; the numbers are for the owner to read.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np
from crosscut_loops.overview import LoopTags, analyze_dataset
from crosscut_sim.core import AUTO, MAN

DEFAULT_PACK = Path(__file__).resolve().parent / "out"


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read a CSV file into a list of dicts (header = keys)."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def load_loop(
    pack: Path, meta: dict[str, str]
) -> tuple[np.ndarray, dict[str, np.ndarray], LoopTags]:
    """Load ``<TAG>.csv`` and build the loop's own column names and ``LoopTags``."""
    tag = meta["tag"]
    rows = read_rows(pack / f"{tag}.csv")
    data = {key: np.array([float(r[key]) for r in rows]) for key in rows[0]}
    names = {k: f"{tag}.{k}" for k in ("pv", "sp", "op", "mode")}
    if not set(np.unique(data["mode"])) <= {float(MAN), float(AUTO)}:
        raise ValueError(f"{tag}: mode column holds codes other than MAN/AUTO")
    columns = {names[k]: data[k] for k in names}
    tags = LoopTags(
        name=tag,
        pv=names["pv"],
        sp=names["sp"],
        out=names["op"],
        mode=names["mode"],
        unit=meta["unit"],
        eng_min=float(meta["eng_min"]),
        eng_max=float(meta["eng_max"]),
        process_kind=meta["process_kind"],
    )
    return data["t_s"], columns, tags


def run_automatic_joint(pack: Path) -> dict[str, dict]:
    """Run ``analyze_dataset`` once on all loops (so cross-loop hints such as shared period work).

    All loops share the same time base (dt = 10 s, 2160 samples), so one call is possible.
    """
    t_all, columns, loops = None, {}, []
    for meta in read_rows(pack / "loops_meta.csv"):
        t_s, cols, tags = load_loop(pack, meta)
        t_all = t_s if t_all is None else t_all
        columns.update(cols)
        loops.append(tags)
    rows = analyze_dataset(t_all, columns, loops)
    return {row["name"]: row for row in rows}


def kendall_tau_b(x: list[float], y: list[float]) -> float:
    """Kendall rank correlation tau-b of two equally long lists (NaN if undefined)."""
    conc = disc = tie_x = tie_y = 0
    for i in range(len(x)):
        for j in range(i + 1, len(x)):
            dx, dy = x[i] - x[j], y[i] - y[j]
            if dx == 0 and dy == 0:
                continue
            tie_x += dx == 0
            tie_y += dy == 0
            conc += dx * dy > 0
            disc += dx * dy < 0
    denom = math.sqrt((conc + disc + tie_x) * (conc + disc + tie_y))
    return (conc - disc) / denom if denom else float("nan")


def print_table(rows: list[list[str]], header: list[str]) -> None:
    """Print a left-aligned plain-text table."""
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    for line in [header, ["-" * w for w in widths], *rows]:
        print(" | ".join(str(c).ljust(w) for c, w in zip(line, widths, strict=True)))


def build_table(
    answers: list[dict[str, str]], auto: dict[str, dict], key: dict[str, str]
) -> list[list[str]]:
    """One table row per reviewed loop, ordered by the reviewer's rank."""
    rows = []
    for ans in sorted(answers, key=lambda a: int(a["rank"])):
        tag = ans["tag"]
        row = auto[tag]
        rows.append(
            [
                ans["rank"],
                str(row["priority_rank"]),
                tag,
                ans["category"],
                str(row["next_action"]["code"]),
                key.get(tag, "?"),
            ]
        )
    return rows


def main() -> None:
    """Parse arguments, run the automatic analysis and print tau and the table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("answers", type=Path, help="reviewer CSV: tag,rank,category,...")
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    args = parser.parse_args()
    answers = [a for a in read_rows(args.answers) if a["rank"].strip()]
    auto = run_automatic_joint(args.pack_dir)
    key = {r["tag"]: r["expected_action"] for r in read_rows(args.pack_dir / "answer_key.csv")}
    rev = [float(a["rank"]) for a in answers]
    aut = [float(auto[a["tag"]]["priority_rank"]) for a in answers]
    print(
        f"Loops compared: {len(answers)}; Kendall tau-b (reviewer vs automatic): "
        f"{kendall_tau_b(rev, aut):.3f}"
    )
    header = ["rev", "auto", "tag", "reviewer category", "automatic next_action", "author key"]
    print_table(build_table(answers, auto, key), header)


if __name__ == "__main__":
    main()
