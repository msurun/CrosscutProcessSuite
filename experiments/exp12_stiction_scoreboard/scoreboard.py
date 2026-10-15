"""Score a stiction detector on the labelled SACAC loops (labels.csv) against the frozen targets.

Targets and rules are in README.md. Usage: python scoreboard.py <unzipped SACAC folder> [detector]
The detector name selects an entry of DETECTORS; each maps (pv, out, dt_s) to a verdict string.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from candidate_a import candidate_a, candidate_b, oscillates
from crosscut_loops.stiction import detect_stiction

Detector = Callable[[np.ndarray, np.ndarray, float, str], str]
LABELS = Path(__file__).resolve().parent / "labels.csv"
WILSON_Z = 1.96
MIN_HELD_DETECTED = 2
MIN_DETECTED = 4
MAX_FLAGGED = 1
MIN_ANSWERED = 11
PV_FOR_LEVEL = [False]  # set by main: True when the detector reads PV for level loops


def shipped(pv: np.ndarray, out: np.ndarray, dt_s: float, kind: str) -> str:
    """The detector as shipped: curve-fit index on OP (the kind is not used)."""
    del kind
    return detect_stiction(pv, out, dt_s).verdict


def a_detector(pv: np.ndarray, out: np.ndarray, dt_s: float, kind: str) -> str:
    """Candidate A: OP for every kind."""
    del kind
    return candidate_a(pv, out, dt_s)


DETECTORS: dict[str, Detector] = {
    "shipped": shipped,
    "candidate_a": a_detector,
    "candidate_b": candidate_b,
}


@dataclass(frozen=True)
class Loop:
    """One labelled loop: its files, sampling period, label, confidence and split."""

    name: str
    stems: list[str]
    dt_s: float
    kind: str
    label: str
    confidence: str
    split: str


def read_columns(root: Path, stem: str) -> tuple[np.ndarray, np.ndarray]:
    """PV and OP of one repository file, found by header name (column order differs per file)."""
    path = next(root.rglob(f"{stem}.csv"))
    lines = [r for r in path.read_text(encoding="latin-1").replace("\r", "\n").split("\n") if r]
    header = [h.strip().lower() for h in lines[0].split(";")]
    rows = [r.split(";") for r in lines[1:]]
    pick = [header.index("pv"), header.index("op")]
    cols = [[float(r[i].replace(",", ".")) for r in rows] for i in pick]
    return np.array(cols[0]), np.array(cols[1])


def load_loops() -> list[Loop]:
    """Read labels.csv."""
    with LABELS.open(encoding="utf-8", newline="") as f:
        return [
            Loop(
                r["loop"],
                r["stems"].split(";"),
                float(r["dt_s"]),
                r["kind"],
                r["label"],
                r["confidence"],
                r["split"],
            )
            for r in csv.DictReader(f)
        ]


def loop_verdict(root: Path, loop: Loop, detector: Detector) -> str:
    """Majority verdict over the loop's files; a tie is 'inconclusive'."""
    votes = Counter(detector(*read_columns(root, s), loop.dt_s, loop.kind) for s in loop.stems)
    (top, n), *rest = votes.most_common()
    return "inconclusive" if rest and rest[0][1] == n else top


def wilson(k: int, n: int) -> tuple[float, float]:
    """95 % Wilson interval of k out of n."""
    p, z = k / n, WILSON_Z
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return float(max(0.0, centre - half)), float(min(1.0, centre + half))


def summarise(results: list[tuple[Loop, str]]) -> list[str]:
    """Target lines T1-T3 (T4 is the exp01 acceptance run, checked separately)."""
    counted = [(loop, v) for loop, v in results if loop.confidence != "low"]
    pos = [(loop, v) for loop, v in counted if loop.label == "stick"]
    neg = [(loop, v) for loop, v in counted if loop.label == "no"]
    hit = [v == "stiction" for _, v in pos]
    held_hit = sum(h for (loop, _), h in zip(pos, hit, strict=True) if loop.split == "held")
    flag = [loop.split for loop, v in neg if v == "stiction"]
    answered = sum(v != "inconclusive" for _, v in counted)
    lo, hi = wilson(sum(hit), len(pos))
    ok = lambda b: "met" if b else "MISSED"  # noqa: E731
    return [
        f"T1 detected {sum(hit)}/{len(pos)} (held-out {held_hit}/3), 95% [{lo:.0%}, {hi:.0%}] -> "
        f"{ok(sum(hit) >= MIN_DETECTED and held_hit >= MIN_HELD_DETECTED)}",
        f"T2 false alarms {len(flag)}/{len(neg)} (held-out {flag.count('held')}) -> "
        f"{ok(len(flag) <= MAX_FLAGGED and flag.count('held') <= MAX_FLAGGED)}",
        f"T3 answered {answered}/{len(counted)} -> {ok(answered >= MIN_ANSWERED)}",
    ]


def oscillation_line(root: Path, results: list[tuple[Loop, str]]) -> str:
    """T3': share of oscillating counted loops (on the detector's signal) with a verdict."""
    rows = []
    for loop, verdict in results:
        pv, out = read_columns(root, loop.stems[0])
        signal = pv if loop.kind == "L" and PV_FOR_LEVEL[0] else out
        if loop.confidence != "low" and oscillates(signal):
            rows.append(verdict != "inconclusive")
    return f"T3' (information) answered {sum(rows)}/{len(rows)} of the oscillating counted loops"


def main(root: Path, name: str) -> None:
    """Print one line per loop and the target verdicts."""
    detector = DETECTORS[name]
    PV_FOR_LEVEL[0] = name == "candidate_b"
    results = [(loop, loop_verdict(root, loop, detector)) for loop in load_loops()]
    for loop, verdict in results:
        print(f"{loop.name:26s} {loop.label:5s} {loop.confidence:6s} {loop.split:5s} -> {verdict}")
    print("\n".join(summarise(results)))
    print(oscillation_line(root, results))


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "shipped")
