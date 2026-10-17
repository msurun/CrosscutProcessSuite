"""exp16 FINAL run (single use): C7a versus the shipped module on never-seen data.

Seeds are sha256(SALT:stream:i) with SALT the commit hash made after the finalist was frozen.
Data: G1/G2/G3 final records, exp01 healthy and sticking cells, noise-only records, the SACAC
veto and the sealed ISDB loops (counted set = independent, high confidence).
Usage: python final16.py <SACAC folder> <ISDB npz folder> <isdb_labels.csv> <private ISDB report>
Writes results/final16.md (no per-loop ISDB numbers) and refuses to run twice.
"""

from __future__ import annotations

import concurrent.futures
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for sub in ("exp01_stiction_validation", "exp12_stiction_scoreboard", "exp13_stiction_suspicion"):
    sys.path.insert(0, str(HERE.parent / sub))
sys.path.insert(0, str(HERE.parent / "exp14_stiction_classifier"))
sys.path.insert(0, str(HERE.parent / "exp15_stiction_robust"))
import acceptance  # noqa: E402
import cases  # noqa: E402
import run13  # noqa: E402
import synth14  # noqa: E402
import synth_shift  # noqa: E402
from calib_prominence import noise  # noqa: E402
from combiner import Combiner, features_c6  # noqa: E402
from crosscut_loops.stiction_suspicion import stiction_suspicion  # noqa: E402
from g3 import CASES as G3_CASES  # noqa: E402
from g3 import NOISES as G3_NOISES  # noqa: E402
from g3 import simulate_g3  # noqa: E402
from scoreboard import load_loops  # noqa: E402

SMOKE = bool(os.environ.get("EXP16_SMOKE"))  # smoke test: tiny sizes, no ISDB, other salt
SALT = "smoke" if SMOKE else "2bb08f93e76a59b760f2d8ae4d1cc71b8b9543fa"
OUT = HERE / "results" / ("final16_smoke.md" if SMOKE else "final16.md")
N_FAMILY = dict.fromkeys(("G1", "G2", "G3"), 2 if SMOKE else 100)
KINDS, CASES = "FL", ("stick", "sine", "square", "tuning")
NOISES = ("low", "mid", "high")
FAMILIES = ("G1", "G2", "G3")
Z, BOOT = 1.96, 2000
MODEL = json.loads((HERE / "c7_model.json").read_text())
MODELS = {k: Combiner.from_dict(v) for k, v in MODEL["models"].items()}
THR = float(MODEL["threshold"])


def seeds(stream: str, n: int) -> list[int]:
    """n seeds from sha256 of salt, stream name and index."""
    return [
        int(hashlib.sha256(f"{SALT}:{stream}:{i}".encode()).hexdigest()[:8], 16) for i in range(n)
    ]


def judge(sp, pv, op, dt_s: float, kind: str) -> dict[str, tuple[float, bool, bool]]:
    """(score with abstain = 0, ranked, flagged) of the shipped module and of C7a."""
    r = stiction_suspicion(sp, pv, op, dt_s, kind)
    f = features_c6(sp, pv, op, kind)
    p = None if f is None else float(MODELS[kind].predict(f[None, :])[0])
    return {
        "shipped": (
            0.0 if r.score is None else r.score,
            r.score is not None,
            r.advice == "test_valve",
        ),
        "C7a": (0.0 if p is None else p, p is not None, p is not None and p >= THR),
    }


def wilson(k: int, n: int) -> str:
    """95 % Wilson interval as text."""
    p = k / n
    c = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    h = Z * np.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    return f"{k}/{n} [{max(0, c - h):.0%}, {min(1, c + h):.0%}]"


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """P(pos > neg) with ties half, vectorised."""
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    s = np.sort(neg)
    below = np.searchsorted(s, pos, side="left") + 0.5 * (
        np.searchsorted(s, pos, side="right") - np.searchsorted(s, pos, side="left")
    )
    return float(np.mean(below) / len(neg))


def synth_job(args: tuple) -> dict:
    """One final synthetic record scored by both."""
    fam, kind, case, noise_lv, seed = args
    if fam == "G3":
        rng = np.random.default_rng(
            [seed, KINDS.index(kind), G3_CASES.index(case), G3_NOISES.index(noise_lv)]
        )
        r = simulate_g3(rng, kind, case, noise_lv)
        sp, pv, op, label, dt = r.sp, r.pv, r.op, r.label, r.dt_s
    else:
        rng = np.random.default_rng(
            [seed, KINDS.index(kind), CASES.index(case), NOISES.index(noise_lv)]
        )
        if fam == "G1":
            sp, pv, op, label, _k = synth14.simulate14(rng, kind, case)
        else:
            r = synth_shift.simulate_shift(rng, kind, case, noise_lv)
            sp, pv, op, label = r.sp, r.pv, r.op, r.label
        dt = 1.0
    return dict(
        fam=fam,
        kind=kind,
        case=case,
        noise=noise_lv,
        label=int(label),
        res=judge(sp, pv, op, dt, kind),
    )


def synth_jobs() -> list[tuple]:
    """All final synthetic jobs; every cell has its own salted seed list."""
    jobs = []
    for kind in KINDS:
        for case in CASES:
            jobs += [
                ("G1", kind, case, "mid", s) for s in seeds(f"G1-{kind}-{case}", N_FAMILY["G1"])
            ]
            for nz in NOISES:
                jobs += [
                    ("G2", kind, case, nz, s)
                    for s in seeds(f"G2-{kind}-{case}-{nz}", N_FAMILY["G2"])
                ]
        for case in G3_CASES:
            for nz in G3_NOISES:
                jobs += [
                    ("G3", kind, case, nz, s)
                    for s in seeds(f"G3-{kind}-{case}-{nz}", N_FAMILY["G3"])
                ]
    return jobs


def scores(rows: list[dict], tag: str) -> tuple[np.ndarray, np.ndarray]:
    """Score array and label array of ``rows`` for scorer ``tag``."""
    return np.array([r["res"][tag][0] for r in rows]), np.array([r["label"] for r in rows])


def bootstrap_worst(rows: list[dict], rng: np.random.Generator) -> tuple[float, float, float]:
    """Mean and 95 % interval of (worst-family AUC of C7a - worst-family AUC of shipped)."""
    fam = {f: [r for r in rows if r["fam"] == f] for f in FAMILIES}
    data = {f: {t: scores(fam[f], t) for t in ("shipped", "C7a")} for f in FAMILIES}
    diffs = []
    for _ in range(BOOT):
        worst = {"shipped": [], "C7a": []}
        for f in FAMILIES:
            idx = rng.integers(0, len(fam[f]), len(fam[f]))
            for t in worst:
                s, y = data[f][t][0][idx], data[f][t][1][idx]
                worst[t].append(auc(s[y == 1], s[y == 0]))
        diffs.append(min(worst["C7a"]) - min(worst["shipped"]))
    return float(np.mean(diffs)), float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))


def p_metrics(s: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """(sensitivity at 10 % healthy flags, approximate pAUC for FPR <= 0.1 normalised to 1)."""
    neg, pos = s[y == 0], s[y == 1]
    sens = float(np.mean(pos > np.quantile(neg, 0.9, method="higher")))
    grid = np.linspace(0, 0.1, 101)
    tpr = [float(np.mean(pos > np.quantile(neg, 1 - g, method="higher"))) for g in grid]
    return sens, float(np.trapezoid(tpr, grid) / 0.1)


def synth_section(rows: list[dict], lines: list[str]) -> dict[str, dict[str, float]]:
    """Per family and scorer: AUCs, coverage, sensitivity, pAUC, flag rates; returns the AUCs."""
    result: dict[str, dict[str, float]] = {t: {} for t in ("shipped", "C7a")}
    lines += ["## Synthetic families (final seeds)", ""]
    for tag in result:
        lines.append(f"### {tag}")
        for f in FAMILIES:
            sub = [r for r in rows if r["fam"] == f]
            s, y = scores(sub, tag)
            rk = np.array([r["res"][tag][1] for r in sub])
            a = auc(s[y == 1], s[y == 0])
            result[tag][f] = a
            sens, pa = p_metrics(s, y)
            fl = np.array([r["res"][tag][2] for r in sub])
            lines.append(
                f"- {f}: AUC {a:.3f}; ranked-only {auc(s[rk & (y == 1)], s[rk & (y == 0)]):.3f} "
                f"(coverage {rk.mean():.0%}); sens@10%FP {sens:.0%}; pAUC(FPR<=0.1) {pa:.2f}; "
                f"flagged: stick {fl[y == 1].mean():.0%}, healthy {fl[y == 0].mean():.0%}"
            )
        lines.append(f"- worst family AUC {min(result[tag].values()):.3f}")
    lines.append("")
    return result


def exp01_job(args: tuple) -> tuple[str, dict]:
    """One exp01 record (constant setpoint, as in the dev runs)."""
    name, case, seed = args
    pv, out, dt_s = cases.simulate_case(case, seed)
    pv, out = acceptance.settle(pv, out, dt_s)
    return name, judge(np.zeros_like(pv), pv, out, dt_s, "F")


def exp01_section(pool, lines: list[str]) -> bool:
    """exp01 cells; returns True when every healthy cell of C7a is <= 2/20."""
    named = {**acceptance.positive_cases(), **acceptance.negative_cases()}
    sd = seeds("exp01", 2 if SMOKE else 20)
    flags: dict[tuple[str, str], int] = {}
    for name, res in pool.map(exp01_job, [(n, c, s) for n, c in named.items() for s in sd]):
        for tag, (_s, _r, fl) in res.items():
            flags[(name, tag)] = flags.get((name, tag), 0) + int(fl)
    lines += ["## exp01 (test_valve counts of 20; exp01 has no setpoint forcing: unproven)", ""]
    for name in named:
        lines.append(
            f"- {name}: shipped {wilson(flags[(name, 'shipped')], 20)}, C7a {wilson(flags[(name, 'C7a')], 20)}"
        )
    healthy = [n for n in named if not n.startswith(("sticking", "square"))]
    ok = all(flags[(n, "C7a")] <= 2 for n in healthy)
    lines += [f"- C7a healthy cells <= 2/20: {'met' if ok else 'MISSED'}", ""]
    return ok


def noise_section(lines: list[str]) -> bool:
    """T7: share of noise-only records flagged by each scorer (100 records)."""
    rng = np.random.default_rng(seeds("t7", 1)[0])
    flagged = {"shipped": 0, "C7a": 0}
    for i in range(100):
        n, k = (3000, 6000, 14400)[i % 3], ("white", "ar-0.5", "ar-0.9", "ar-0.98", "walk")[i % 5]
        pv, op = noise(rng, k, n), noise(rng, k, n)
        for tag, (_s, _r, fl) in judge(np.zeros(n), pv, op, 1.0, "F").items():
            flagged[tag] += fl
    lines += ["## T7 noise-only (100 records, flagged)", ""]
    lines += [f"- {t}: {v}/100" for t, v in flagged.items()] + [""]
    return flagged["C7a"] <= 5


def sacac_section(root: Path, lines: list[str]) -> None:
    """Veto on the 17 counted SACAC loops (loop score = median over its files)."""
    lines += ["## SACAC veto (>= 5/6 sticking flagged, <= 2 non-sticking flagged)", ""]
    for tag in ("shipped", "C7a"):
        pos = neg = ranked_neg = 0
        for lp in (x for x in load_loops() if x.confidence != "low"):
            kind = "L" if lp.kind == "L" else "F"
            sc = [judge(*run13.read_spo(root, s), lp.dt_s, kind)[tag] for s in lp.stems]
            vals = [x[0] for x in sc if x[1]]
            if not vals:
                continue
            fl = float(np.median(vals)) >= (0.5 if tag == "shipped" else THR)
            if lp.label == "stick":
                pos += fl
            else:
                neg += fl
                ranked_neg += 1
        lines.append(
            f"- {tag}: sticking flagged {pos}/6, non-sticking flagged {neg}, ranked {ranked_neg}/11"
        )
    lines.append("")


def isdb_section(
    npz_dir: Path, labels: Path, private: Path, lines: list[str]
) -> tuple[int, int, int, int]:
    """ISDB counted set: counts only in the report; per-loop scores go to the private file."""
    rows = list(csv.DictReader(labels.open(encoding="utf-8")))
    out = {}
    for r in rows:
        with np.load(npz_dir / (r["loop"].replace("/", "_") + ".npz")) as z:
            sp, pv, op, dt = z["sp"], z["pv"], z["op"], float(z["dt_s"])
        out[r["loop"]] = judge(sp, pv, op, dt, r["kind"])
    private.write_text("\n".join(f"{k}\t{v}" for k, v in out.items()), encoding="utf-8")
    lines += ["## ISDB counted set (independent, high confidence; veto only, n is small)", ""]
    counts = {}
    for tag in ("shipped", "C7a"):
        for lab in ("stick", "other"):
            sel = [
                r
                for r in rows
                if r["overlap"] == "independent" and r["confidence"] == "high" and r["label"] == lab
            ]
            k = sum(out[r["loop"]][tag][2] for r in sel)
            counts[(tag, lab)] = k
            rk = sum(out[r["loop"]][tag][1] for r in sel)
            lines.append(f"- {tag} {lab}: flagged {wilson(k, len(sel))}, ranked {rk}/{len(sel)}")
        sel = [r for r in rows if r["overlap"] == "independent" and r["confidence"] == "high"]
        s = np.array([out[r["loop"]][tag][0] for r in sel])
        y = np.array([r["label"] == "stick" for r in sel])
        lines.append(f"- {tag} AUC (abstain=0) {auc(s[y], s[~y]):.3f}")
    lines.append("")
    return (
        counts[("shipped", "stick")],
        counts[("C7a", "stick")],
        counts[("shipped", "other")],
        counts[("C7a", "other")],
    )


def main(sacac: Path, npz_dir: Path, labels: Path, private: Path) -> None:
    """Run everything once, apply the README acceptance rule, write results/final16.md."""
    if OUT.exists() and not SMOKE:
        raise SystemExit("final16.md exists: the final run is single-use")
    lines = [f"# exp16 final run (single use), salt {SALT}", ""]
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(synth_job, synth_jobs(), chunksize=16))
        ok_exp01 = exp01_section(pool, lines)
    aucs = synth_section(rows, lines)
    mean, lo, hi = bootstrap_worst(rows, np.random.default_rng(seeds("boot", 1)[0]))
    worst_gain = min(aucs["C7a"].values()) - min(aucs["shipped"].values())
    ok_t7 = noise_section(lines)
    sacac_section(sacac, lines)
    if SMOKE:
        sp_s = sp_c = ot_s = ot_c = 0
    else:
        sp_s, sp_c, ot_s, ot_c = isdb_section(npz_dir, labels, private, lines)
    verdict = [
        ("worst-family AUC gain >= 0.03", worst_gain >= 0.03),
        ("paired bootstrap interval excludes 0", lo > 0),
        ("exp01 healthy cells <= 2/20", ok_exp01),
        ("T7 noise-only <= 5 %", ok_t7),
        ("ISDB sticking flagged >= shipped - 1", sp_c >= sp_s - 1),
        ("ISDB other flagged <= shipped + 1", ot_c <= ot_s + 1),
    ]
    lines += [
        f"## Acceptance: worst-family gain {worst_gain:+.3f}, bootstrap {mean:+.3f} [{lo:+.3f}, {hi:+.3f}]",
        "",
    ]
    lines += [f"- {name}: {'met' if ok else 'MISSED'}" for name, ok in verdict]
    lines += [f"- SHIP C7a: {'yes' if all(ok for _n, ok in verdict) else 'NO'}"]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
