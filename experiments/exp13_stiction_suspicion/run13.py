"""Run exp13: calibrate Horch on synthetic loops, score the SACAC loops, check the frozen targets.

Usage: ../../.venv/Scripts/python run13.py <unzipped SACAC folder>
Prints the ranked suspicion table, R1, R1p, R2, the sanity checks and the per-test AUCs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exp12_stiction_scoreboard"))
import suspicion as su  # noqa: E402
import synth  # noqa: E402
from scoreboard import Loop, load_loops  # noqa: E402

MIN_AUC, MIN_HELD_AUC, MAX_P = 0.80, 0.70, 0.05
LEVEL_TEST_VALVE = 0.5
N_CAL, N_PERM, N_RANDOM = 40, 2000, 200


def calibrate() -> tuple[float, float]:
    """Median Horch oddness of synthetic non-sticking and sticking F loops (seeded)."""
    rng = np.random.default_rng(11)
    med = {}
    for sticking in (False, True):
        vals = []
        for _ in range(N_CAL):
            sp, pv, op, _label = synth.simulate(rng, "F", sticking)
            w = su.find_window(sp, pv)
            if w is not None:
                vals.append(su.horch_oddness(op[w.start : w.stop], pv[w.start : w.stop], w.period))
        med[sticking] = float(np.median(vals))
    return med[False], med[True]


def read_spo(root: Path, stem: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """SP, PV and OP of one repository file by header name."""
    path = next(root.rglob(f"{stem}.csv"))
    lines = [r for r in path.read_text(encoding="latin-1").replace("\r", "\n").split("\n") if r]
    header = [h.strip().lower() for h in lines[0].split(";")]
    rows = [r.split(";") for r in lines[1:]]
    cols = [[float(r[header.index(c)].replace(",", ".")) for r in rows] for c in ("sp", "pv", "op")]
    return tuple(np.array(c) for c in cols)  # type: ignore[return-value]


def loop_result(root: Path, loop: Loop, cal: tuple[float, float]) -> dict[str, float] | None:
    """Median of each score over the loop's files that have an oscillation window."""
    rows = [su.file_score(*read_spo(root, s), loop.dt_s, loop.kind, cal) for s in loop.stems]
    rows = [r for r in rows if r is not None]
    if not rows:
        return None
    return {
        k: float(np.nanmedian([r[k] for r in rows])) if k != "n" else len(rows) for k in rows[0]
    }


def auc(pos: list[float], neg: list[float]) -> float:
    """Probability that a sticking loop scores above a non-sticking one (ties count half)."""
    return float(np.mean([(a > b) + 0.5 * (a == b) for a in pos for b in neg]))


def perm_p(scores: np.ndarray, y: np.ndarray, observed: float) -> float:
    """One-sided permutation p-value of the AUC under shuffled labels."""
    rng = np.random.default_rng(5)
    hits = 0
    for _ in range(N_PERM):
        yy = rng.permutation(y)
        hits += auc(list(scores[yy == 1]), list(scores[yy == 0])) >= observed
    return (hits + 1) / (N_PERM + 1)


def report(ranked: list[tuple[Loop, dict[str, float]]], n_stick: int) -> None:
    """Print R1, R1p, R2 and the per-test AUCs for the ranked loops."""
    sc = np.array([r["score"] for _, r in ranked])
    y = np.array([lp.label == "stick" for lp, _ in ranked], dtype=int)
    held = np.array([lp.split == "held" for lp, _ in ranked])
    a = auc(list(sc[y == 1]), list(sc[y == 0]))
    ah = auc(list(sc[(y == 1) & held]), list(sc[(y == 0) & held]))
    ok = lambda b: "met" if b else "MISSED"  # noqa: E731
    print(
        f"R1 AUC {a:.2f} (n={y.sum()}+{(1 - y).sum()}), "
        f"held-out {ah:.2f} -> {ok(a >= MIN_AUC and ah >= MIN_HELD_AUC)}"
    )
    p = perm_p(sc, y, a)
    print(f"R1p permutation p {p:.3f} -> {ok(p <= MAX_P)}")
    flagged = sc >= LEVEL_TEST_VALVE
    tp, fp = int((flagged & (y == 1)).sum()), int((flagged & (y == 0)).sum())
    print(
        f"R2 test-the-valve: sticking {tp}/{n_stick}, "
        f"non-sticking ranked {fp} -> {ok(tp >= 4 and fp <= 2)}"
    )
    for key in ("he", "horch"):
        v = np.array([r[key] for _, r in ranked])
        m = ~np.isnan(v)
        if m.sum() and y[m].sum() and (1 - y[m]).sum():
            print(
                f"  per-test AUC {key}: "
                f"{auc(list(v[m & (y == 1)]), list(v[m & (y == 0)])):.2f} (n={m.sum()})"
            )


def sanity(sc_n: int, y: np.ndarray) -> None:
    """Random-score detector mean AUC (must be 0.5 +/- 0.1)."""
    rng = np.random.default_rng(9)
    aucs = [
        auc(list(s[y == 1]), list(s[y == 0])) for s in (rng.random(sc_n) for _ in range(N_RANDOM))
    ]
    print(
        f"S random detector mean AUC {np.mean(aucs):.2f} -> "
        f"{'ok' if abs(np.mean(aucs) - 0.5) <= 0.1 else 'BROKEN'}"
    )
    print("S always-abstain detector: no scores, 0 sticking loops flagged -> fails R2 as required")


def main(root: Path) -> None:
    """Score all counted loops and print the report."""
    cal = calibrate()
    print(f"Horch calibration (synthetic only): non-sticking {cal[0]:.2f}, sticking {cal[1]:.2f}")
    counted = [lp for lp in load_loops() if lp.confidence != "low"]
    n_stick = sum(lp.label == "stick" for lp in counted)
    results = [(lp, loop_result(root, lp, cal)) for lp in counted]
    for lp, r in sorted(results, key=lambda t: -(t[1]["score"] if t[1] else -1)):
        txt = (
            "no oscillation window"
            if r is None
            else f"score {r['score']:.2f} he {r['he']:.2f} "
            f"horch {r['horch']:.2f} period {r['period']:.0f} samples"
        )
        print(f"{lp.name:26s} {lp.label:5s} {lp.split:5s} {txt}")
    ranked = [(lp, r) for lp, r in results if r is not None]
    print(
        f"ranked {len(ranked)}/{len(counted)}; "
        f"sticking ranked {sum(lp.label == 'stick' for lp, _ in ranked)}/{n_stick}"
    )
    report(ranked, n_stick)
    sanity(len(ranked), np.array([lp.label == "stick" for lp, _ in ranked], dtype=int))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
