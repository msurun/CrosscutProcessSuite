"""exp24: one confirmation run of candidate I against the shipped ACF detector A.

Reuses the exp23 cell definitions and the exp20 generator; adds report-only AR(2) and drift cells.
Applies the frozen ship rule of the README once and refuses to overwrite results24.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exp23_acf_peak_gate_biased"))

import run23  # noqa: E402  (cells, factories, evaluate_cell; it also loads g20_signals)
from crosscut_loops.oscillation_acf import AcfConfig  # noqa: E402

NEG_SEEDS = range(8000, 8400)  # 400 per negative cell
POS_SEEDS = range(8000, 8100)  # 100 per positive cell
CANDIDATES = {"I": AcfConfig(min_crossings=5, max_lag_fraction=0.75, peak_z=3.0), "A": AcfConfig()}
F_CELL_MAX_COUNT = 12  # of 400: one-sided 95 % Clopper-Pearson upper bound about 5 %
F_POOL_MAX = 0.02
S_MARGIN = 0.10
L_TOLERANCE = 0.02
CELL_EXCESS_MAX = 2  # I may exceed A by at most this many detections in any negative cell
NS = (300, 1000, 3000)
RESULTS = HERE / "results24.md"


def _ar2(n: int, radius: float, seed: int) -> np.ndarray:
    """AR(2), poles radius * exp(+-i 2 pi / 20): a narrow-band resonance, not a limit cycle."""
    rng = np.random.default_rng(seed)
    a1, a2 = 2.0 * radius * np.cos(2.0 * np.pi / 20.0), -(radius**2)
    e, x = rng.standard_normal(n + 200), np.zeros(n + 200)
    for k in range(2, n + 200):
        x[k] = a1 * x[k - 1] + a2 * x[k - 2] + e[k]
    return x[200:]  # drop the start-up transient


def _drift(n: int, seed: int) -> np.ndarray:
    """Random walk with step std 0.05 plus white noise std 1."""
    rng = np.random.default_rng(seed)
    return np.cumsum(0.05 * rng.standard_normal(n)) + rng.standard_normal(n)


def report_only_cells() -> dict[str, object]:
    """Name -> seed -> signal factory for the cells that do not gate the decision."""
    cells: dict[str, object] = {}
    for n in NS:
        for radius in (0.9, 0.97):
            cells[f"ar2 r={radius} n={n}"] = lambda s, n=n, r=radius: _ar2(n, r, s)
        cells[f"drift n={n}"] = lambda s, n=n: _drift(n, s)
    return cells


def _counts(factories: dict[str, object], seeds: range) -> dict[str, dict[str, int]]:
    """Cell name -> candidate -> detections over the seeds."""
    out = {}
    for index, (name, factory) in enumerate(factories.items()):
        outcome = run23.evaluate_cell(factory, seeds, CANDIDATES)
        out[name] = {cand: outcome[cand].detected for cand in CANDIDATES}
        if (index + 1) % 20 == 0:
            print(f"[exp24] {index + 1}/{len(factories)} cells", file=sys.stderr)
    return out


def _pool(counts: dict[str, dict[str, int]], names: list[str], cand: str, per: int) -> float:
    """Detected share of one candidate pooled over the named cells."""
    return sum(counts[name][cand] for name in names) / (per * len(names)) if names else 0.0


def decide(neg: dict, pos: dict, pos_cells: list) -> tuple[dict[str, bool], dict[str, float]]:
    """Apply the four frozen ship conditions; return verdicts and the numbers behind them."""
    neg_names = list(neg)
    s_names = [c.name for c in pos_cells if c.is_target_s()]
    l_names = [c.name for c in pos_cells if c.is_target_l()]
    nums = {f"{key}_{cand}": value for cand in CANDIDATES for key, value in (
        ("pooled_neg", _pool(neg, neg_names, cand, len(NEG_SEEDS))),
        ("S", _pool(pos, s_names, cand, len(POS_SEEDS))),
        ("L", _pool(pos, l_names, cand, len(POS_SEEDS))),
    )}
    verdicts = {
        "F": max(neg[n]["I"] for n in neg_names) <= F_CELL_MAX_COUNT
        and nums["pooled_neg_I"] <= F_POOL_MAX,
        "S": nums["S_I"] >= nums["S_A"] + S_MARGIN,
        "L": nums["L_I"] >= nums["L_A"] - L_TOLERANCE,
        "no_cell_worse": all(neg[n]["I"] <= neg[n]["A"] + CELL_EXCESS_MAX for n in neg_names),
    }
    return verdicts, nums


def _table(counts: dict[str, dict[str, int]], per: int) -> list[str]:
    """Markdown rows: cell, I and A detections out of `per`."""
    rows = ["| cell | I | A |", "| --- | --- | --- |"]
    return rows + [f"| {name} | {c['I']}/{per} | {c['A']}/{per} |" for name, c in counts.items()]


def _report(verdicts: dict[str, bool], nums: dict[str, float], tables: list[str]) -> str:
    """The markdown report: verdicts, numbers, ship decision and the per-cell tables."""
    ship = all(verdicts.values())
    lines = ["# exp24 results: I vs A (single confirmation run)", ""]
    lines += [f"- {key}: {'PASS' if ok else 'MISS'}" for key, ok in verdicts.items()]
    lines += [f"- {key}: {100.0 * value:.1f} %" for key, value in nums.items()]
    lines += ["", f"**Ship I: {'yes' if ship else 'no'}**", ""] + tables
    return "\n".join(lines) + "\n"


def main() -> None:
    """Run every cell once for I and A, decide, write results24.md."""
    if RESULTS.exists():
        raise SystemExit(f"refusing to overwrite {RESULTS}")
    neg_cells, pos_cells = run23.negative_cells(), run23.positive_cells()
    neg = _counts({c.name: run23.negative_signal_factory(c) for c in neg_cells}, NEG_SEEDS)
    pos = _counts({c.name: run23.positive_signal_factory(c) for c in pos_cells}, POS_SEEDS)
    extra = _counts(report_only_cells(), NEG_SEEDS)
    verdicts, nums = decide(neg, pos, pos_cells)
    short = {n: v for n, v in pos.items() if "n=300 c=20 " in n and "snr=0.5" not in n}
    tables = ["## Negative cells (gate the decision)", ""] + _table(neg, len(NEG_SEEDS))
    tables += ["", "## Report only: AR(2) resonance and drift", ""] + _table(extra, len(NEG_SEEDS))
    tables += ["", "## Report only: n=300, c=20 (period 15), SNR >= 1", ""]
    tables += _table(short, len(POS_SEEDS))
    tables += ["", "## All positive cells", ""] + _table(pos, len(POS_SEEDS))
    text = _report(verdicts, nums, tables)
    RESULTS.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
