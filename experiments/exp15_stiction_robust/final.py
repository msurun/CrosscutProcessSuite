"""exp15 FINAL run: finalist C4a versus the shipped module on never-seen seeds. Run ONCE.

Final data: exp01 seeds 21-40, synth14 seeds 500-599, shifted generator seeds 1000-1099,
a noise-only set with a new seed, and the SACAC veto. Writes results/final.md and
refuses to run twice.
Usage: python final.py <SACAC folder>
"""

from __future__ import annotations

import concurrent.futures
import os
import sys
from pathlib import Path

import cand15
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exp01_stiction_validation"))
sys.path.insert(0, str(HERE.parent / "exp12_stiction_scoreboard"))
sys.path.insert(0, str(HERE.parent / "exp13_stiction_suspicion"))
sys.path.insert(0, str(HERE.parent / "exp14_stiction_classifier"))
import acceptance  # noqa: E402
import cases  # noqa: E402
import run13  # noqa: E402
import synth14  # noqa: E402
import synth_shift  # noqa: E402
from calib_prominence import noise  # noqa: E402
from eval_synth import auc  # noqa: E402
from scoreboard import load_loops  # noqa: E402

SMOKE = bool(os.environ.get("EXP15_SMOKE"))  # smoke test on dev seeds, writes final_smoke.md
OUT = HERE / "results" / ("final_smoke.md" if SMOKE else "final.md")
if SMOKE:
    EXP01_SEEDS, S14_SEEDS, SHIFT_SEEDS = range(1, 3), range(100, 102), range(1, 3)
else:
    EXP01_SEEDS, S14_SEEDS, SHIFT_SEEDS = range(21, 41), range(500, 600), range(1000, 1100)
KINDS, CASES, NOISES = "FL", ("stick", "sine", "square", "tuning"), ("low", "mid", "high")
CANDIDATES = (("shipped", "base"), ("C4a", "c4a"))
SHORT_HALF = 18.0
Z = 1.96


def wilson(k: int, n: int) -> str:
    """95 % Wilson interval as text."""
    p = k / n
    c = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    h = Z * np.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    return f"{k}/{n} [{max(0, c - h):.0%}, {min(1, c + h):.0%}]"


def judge(sp, pv, op, kind: str) -> dict[str, tuple[float, bool, bool]]:
    """(score with abstain = 0, ranked, flagged) for every candidate."""
    out = {}
    for tag, variant in CANDIDATES:
        r = cand15.suspicion15(sp, pv, op, 1.0, kind, variant)
        out[tag] = (
            0.0 if r.score is None else r.score,
            r.score is not None,
            r.advice == "test_valve",
        )
    return out


def exp01_job(args: tuple[str, cases.Case, int]) -> tuple[str, int, dict]:
    """One exp01 record scored by both candidates (constant setpoint, as in the dev runs)."""
    name, case, seed = args
    pv, out, dt_s = cases.simulate_case(case, seed)
    pv, out = acceptance.settle(pv, out, dt_s)
    return name, seed, judge(np.zeros_like(pv), pv, out, "F")


def synth_job(args: tuple[str, str, str, str, int]) -> dict:
    """One synthetic final record scored by both candidates."""
    gen, kind, case, noise_lv, seed = args
    rng = np.random.default_rng(
        [seed, KINDS.index(kind), CASES.index(case), NOISES.index(noise_lv)]
    )
    if gen == "s14":
        sp, pv, op, label, _k = synth14.simulate14(rng, kind, case)
        half = synth_shift._half_cycle(op)
    else:
        r = synth_shift.simulate_shift(rng, kind, case, noise_lv)
        sp, pv, op, label, half = r.sp, r.pv, r.op, r.label, r.half_cycle_samples
    return dict(
        gen=gen,
        kind=kind,
        case=case,
        noise=noise_lv,
        label=float(label),
        half=half,
        res=judge(sp, pv, op, kind),
    )


def run_exp01(pool, lines: list[str]) -> None:
    """exp01 cells: flagged counts of 20 per candidate, with Wilson intervals."""
    named = {**acceptance.positive_cases(), **acceptance.negative_cases()}
    jobs = [(n, c, s) for n, c in named.items() for s in EXP01_SEEDS]
    flags: dict[tuple[str, str], int] = {}
    for name, _seed, res in pool.map(exp01_job, jobs):
        for tag, (_s, _r, flagged) in res.items():
            flags[(name, tag)] = flags.get((name, tag), 0) + int(flagged)
    lines += [
        "## exp01 mill simulation, final seeds 21-40 (test_valve counts)",
        "",
        "| class | " + " | ".join(t for t, _ in CANDIDATES) + " |",
        "|---|---|---|",
    ]
    for name in named:
        lines.append(
            f"| {name} | " + " | ".join(wilson(flags[(name, t)], 20) for t, _ in CANDIDATES) + " |"
        )
    lines.append("")
    targets = []
    for band in (4, 6, 8):
        targets.append(
            (
                f"T1 band {band} % low noise >= 18/20",
                flags.get((f"sticking band {band}% (low noise)", "C4a"), 0) >= 18,
            )
        )
    targets.append(
        ("T2 band 8 % full noise >= 14/20", flags[("sticking band 8% (full noise)", "C4a")] >= 14)
    )
    for name in named:
        if not name.startswith(("sticking", "square")):
            targets.append((f"T3 {name} <= 2/20", flags[(name, "C4a")] <= 2))
    lines += [f"- C4a {label}: {'met' if ok else 'MISSED'}" for label, ok in targets] + [""]


def run_synth(pool, lines: list[str]) -> None:
    """Synthetic final sets: AUCs, flags per healthy class and noise level, short half-cycles."""
    jobs = [("s14", k, c, "mid", s) for k in KINDS for c in CASES for s in S14_SEEDS]
    jobs += [
        ("shift", k, c, n, s) for k in KINDS for c in CASES for n in NOISES for s in SHIFT_SEEDS
    ]
    rows = list(pool.map(synth_job, jobs, chunksize=8))
    rng = np.random.default_rng(4242)
    for tag, _ in CANDIDATES:
        lines += [f"## {tag}: synthetic final sets", ""]
        for gen in ("s14", "shift"):
            g = [r for r in rows if r["gen"] == gen]
            lines += synth_report(g, tag, gen, rng)
    lines.append("")


def synth_report(g: list[dict], tag: str, gen: str, rng: np.random.Generator) -> list[str]:
    """AUC and flag lines of one generator for one candidate."""

    def a0(sub, ranked_only=False):
        s = [r for r in sub if r["res"][tag][1] or not ranked_only]
        return auc(
            [r["res"][tag][0] for r in s if r["label"] == 1],
            [r["res"][tag][0] for r in s if r["label"] == 0],
        )

    short = [r for r in g if r["half"] < SHORT_HALF]
    out = [
        f"- {gen}: AUC abstain=0 overall {a0(g):.3f} "
        f"(ranked only {a0(g, True):.3f}); "
        f"F {a0([r for r in g if r['kind'] == 'F']):.3f}; "
        f"L {a0([r for r in g if r['kind'] == 'L']):.3f}; "
        f"half-cycle < {SHORT_HALF:.0f}: {a0(short):.3f} (n={len(short)})"
    ]
    rand = np.mean(
        [
            auc(
                list(rng.random(sum(r["label"] == 1 for r in g))),
                list(rng.random(sum(r["label"] == 0 for r in g))),
            )
            for _ in range(20)
        ]
    )
    out.append(f"  random-score sanity AUC {rand:.2f}")
    for case in ("sine", "square", "tuning"):
        for lv in sorted({r["noise"] for r in g}):
            sub = [r for r in g if r["case"] == case and r["noise"] == lv]
            n_flag = sum(r["res"][tag][2] for r in sub)
            out.append(f"  flagged {case} noise {lv}: {wilson(n_flag, len(sub))}")
    pos = [r for r in g if r["case"] == "stick"]
    out.append(f"  stiction flagged {wilson(sum(r['res'][tag][2] for r in pos), len(pos))}")
    return out


def run_noise(lines: list[str]) -> None:
    """T7: share of noise-only records ranked / flagged (100 records, new seed)."""
    rng = np.random.default_rng(31337)
    stats = {t: [0, 0] for t, _ in CANDIDATES}
    kinds = ("white", "ar-0.5", "ar-0.9", "ar-0.98", "walk")
    for i in range(100):
        n = (3000, 6000, 14400)[i % 3]
        pv, op = noise(rng, kinds[i % 5], n), noise(rng, kinds[i % 5], n)
        for tag, (_s, ranked, flagged) in judge(np.zeros(n), pv, op, "F").items():
            stats[tag][0] += ranked
            stats[tag][1] += flagged
    lines += ["## T7 noise-only records (100)", ""]
    lines += [
        f"- {t}: ranked {r}/100, flagged {f}/100 -> "
        f"{'met' if (r if t == 'shipped' else f) <= 5 else 'MISSED'}"
        for t, (r, f) in stats.items()
    ] + [""]


def run_sacac(root: Path, lines: list[str]) -> None:
    """T5 veto on the 17 counted SACAC loops: flagged sticking, flagged non-sticking,
    newly ranked."""
    for tag, variant in CANDIDATES:
        flagged_pos = flagged_neg = ranked_neg = 0
        for lp in (x for x in load_loops() if x.confidence != "low"):
            kind = "L" if lp.kind == "L" else "F"
            res = []
            for s in lp.stems:
                sp, pv, op = run13.read_spo(root, s)
                res.append(cand15.suspicion15(sp, pv, op, lp.dt_s, kind, variant))
            scores = [r.score for r in res if r.score is not None]
            if not scores:
                continue
            flag = float(np.median(scores)) >= 0.5
            if lp.label == "stick":
                flagged_pos += flag
            else:
                flagged_neg += flag
                ranked_neg += 1
        lines.append(
            f"- SACAC {tag}: sticking flagged {flagged_pos}/6, "
            f"non-sticking flagged {flagged_neg}, non-sticking ranked {ranked_neg}/11"
        )
    lines.append("")


def main(sacac_root: Path) -> None:
    """Run everything once and write results/final.md."""
    if OUT.exists() and not SMOKE:
        raise SystemExit("final.md exists: the final run is single-use")
    lines = ["# exp15 final run (single use)", ""]
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        run_exp01(pool, lines)
        run_synth(pool, lines)
    run_noise(lines)
    lines += ["## SACAC veto (T5: >= 5/6 flagged, <= 2 non-sticking flagged)", ""]
    run_sacac(sacac_root, lines)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
