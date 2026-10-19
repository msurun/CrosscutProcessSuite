"""exp23: biased-ACF detector with a peak gate, protocol frozen 2026-10-19.

Candidates A (baseline, shipped), I, J, M; the selection applies the L tolerance against A.
Dev phase evaluates them on synthetic short records and picks a winner by the frozen
targets; test phase confirms one candidate against A once.
Signals are synthetic (exp23 README), not ISDB. Writes results23_dev.md / results23_test.md and
refuses to overwrite them.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exp20_acf_short_records"))

import g20_signals  # noqa: E402
from crosscut_loops.oscillation_acf import (  # noqa: E402
    BAND_BARTLETT,
    AcfConfig,
    acf_regularity,
)

DT_S = 1.0  # sampling period of every synthetic error signal, seconds
SHORTEST_PERIOD_SAMPLES = 10  # records whose period is shorter are not meaningful tests
DEV_SEEDS = range(4000, 4100)
TEST_SEEDS = range(6000, 6100)
CYCLES = (3, 4, 5, 6, 8, 10, 20)
NS = (300, 1000, 3000)
SNRS = (2.0, 1.0, 0.5)
SHORT_CYCLES = frozenset({3, 4})  # "very short record" cells reported but not targeted
LONG_CYCLES = 20
STRONG_SNR = 1.0  # S and L targets only count records with SNR >= this
LOW_SNR = 0.5
F_CELL_MAX = 0.05
F_POOL_MAX = 0.02
S_MIN = 0.90
L_MIN = 0.98
SHIP_S_MARGIN = 0.10  # candidate S must exceed A's S by at least this (absolute)
SHIP_L_TOLERANCE = 0.02  # candidate L may fall at most this far below A's L
BASELINE = "A"
PROGRESS_EVERY_N_CELLS = 20
CANDIDATES = {
    "A": AcfConfig(BAND_BARTLETT, 7, 0.5, False, 0.0),
    "I": AcfConfig(BAND_BARTLETT, 5, 0.75, False, 3.0),
    "J": AcfConfig(BAND_BARTLETT, 5, 0.75, False, 2.5),
    "M": AcfConfig(BAND_BARTLETT, 5, 0.5, False, 3.0),
}
TEST_CHOICES = [name for name in CANDIDATES if name != BASELINE]

SignalFactory = Callable[[int], np.ndarray]


@dataclass(frozen=True)
class PositiveCell:
    """A positive record: one waveform, record length, cycles in record, SNR, noise kind."""

    waveform: str
    n: int
    cycles: int
    snr: float
    noise: str

    @property
    def name(self) -> str:
        return f"pos {self.waveform} n={self.n} c={self.cycles} snr={self.snr} {self.noise}"

    def is_target_s(self) -> bool:
        return self.cycles >= 5 and self.snr >= STRONG_SNR

    def is_target_l(self) -> bool:
        return self.cycles == LONG_CYCLES and self.snr >= STRONG_SNR

    def is_short_cycles(self) -> bool:
        return self.cycles in SHORT_CYCLES and self.snr >= STRONG_SNR

    def is_low_snr(self) -> bool:
        return self.snr == LOW_SNR


@dataclass(frozen=True)
class NegativeCell:
    """A negative record (no oscillation): a disturbance kind at a given record length."""

    kind: str
    n: int

    @property
    def name(self) -> str:
        return f"neg {self.kind} n={self.n}"


@dataclass(frozen=True)
class CellOutcome:
    """Detection count and reason counter for one candidate on one cell."""

    detected: int
    reason_counts: Counter[str]


def positive_cells() -> list[PositiveCell]:
    """Enumerate every positive cell, skipping periods shorter than the minimum."""
    cells: list[PositiveCell] = []
    for waveform in g20_signals.POSITIVE_WAVEFORMS:
        for noise in g20_signals.NOISE_KINDS:
            for n in NS:
                for cycles in CYCLES:
                    if n / cycles < SHORTEST_PERIOD_SAMPLES:
                        continue
                    for snr in SNRS:
                        cells.append(PositiveCell(waveform, n, cycles, snr, noise))
    return cells


def negative_cells() -> list[NegativeCell]:
    """Enumerate every negative cell: each disturbance kind at every record length."""
    return [NegativeCell(kind, n) for kind in g20_signals.NEGATIVE_KINDS for n in NS]


def positive_signal_factory(cell: PositiveCell) -> SignalFactory:
    """Return a seed -> error signal function for one positive cell."""

    def generate(seed: int) -> np.ndarray:
        return g20_signals.positive_case(
            cell.waveform, cell.n, cell.cycles, cell.snr, cell.noise, seed
        )

    return generate


def negative_signal_factory(cell: NegativeCell) -> SignalFactory:
    """Return a seed -> error signal function for one negative cell."""

    def generate(seed: int) -> np.ndarray:
        return g20_signals.negative_case(cell.kind, cell.n, seed)

    return generate


def evaluate_cell(
    signal_factory: SignalFactory,
    seeds: range,
    candidates: dict[str, AcfConfig],
) -> dict[str, CellOutcome]:
    """Run every candidate on each generated signal once; count detections and reasons."""
    detected = {name: 0 for name in candidates}
    reasons = {name: Counter() for name in candidates}
    for seed in seeds:
        signal = signal_factory(seed)
        for name, config in candidates.items():
            verdict = acf_regularity(signal, DT_S, config)
            if verdict.regular:
                detected[name] += 1
            reasons[name][verdict.reason] += 1
    return {name: CellOutcome(detected[name], reasons[name]) for name in candidates}


def _pooled_share(
    outcomes: dict[str, CellOutcome],
    cells: list,
    keep: Callable[[object], bool],
    seeds: range,
) -> float | None:
    """Detected count divided by total over the cells that satisfy `keep` (None if no cells)."""
    total = 0
    hits = 0
    for cell in cells:
        if keep(cell):
            total += len(seeds)
            hits += outcomes[cell.name].detected
    return hits / total if total else None


def pool_share(
    outcomes: dict[str, CellOutcome],
    cells: list,
    keep: Callable[[object], bool],
    seeds: range,
) -> float | None:
    """Public wrapper around `_pooled_share` returning a fraction in [0,1] or None."""
    return _pooled_share(outcomes, cells, keep, seeds)


def candidate_targets(
    neg_outcomes: dict[str, CellOutcome],
    neg_cells: list[NegativeCell],
    pos_outcomes: dict[str, CellOutcome],
    pos_cells: list[PositiveCell],
    seeds: range,
) -> dict:
    """Compute F, S, L and reported shares for one candidate (already evaluated)."""
    cell_shares = {
        cell.name: neg_outcomes[cell.name].detected / len(seeds) for cell in neg_cells
    }
    worst_cell = max(cell_shares, key=cell_shares.__getitem__)
    pooled_neg = sum(s * len(seeds) for s in cell_shares.values()) / (len(seeds) * len(neg_cells))
    f_pass = (
        all(share <= F_CELL_MAX for share in cell_shares.values()) and pooled_neg <= F_POOL_MAX
    )
    s_pool = _pooled_share(pos_outcomes, pos_cells, lambda c: c.is_target_s(), seeds)
    l_share = _pooled_share(pos_outcomes, pos_cells, lambda c: c.is_target_l(), seeds)
    short_share = _pooled_share(pos_outcomes, pos_cells, lambda c: c.is_short_cycles(), seeds)
    low_snr_share = _pooled_share(pos_outcomes, pos_cells, lambda c: c.is_low_snr(), seeds)
    return {
        "cell_shares": cell_shares,
        "worst_cell": worst_cell,
        "worst_share": cell_shares[worst_cell],
        "pooled_neg": pooled_neg,
        "f_pass": f_pass,
        "s_pool": s_pool or 0.0,
        "l_share": l_share or 0.0,
        "short_share": short_share or 0.0,
        "low_snr_share": low_snr_share or 0.0,
    }


def choose_winner(targets_by_candidate: dict[str, dict]) -> str:
    """Among non-A candidates meeting F and the L tolerance vs A, the highest S (ties: earlier)."""
    l_floor = targets_by_candidate[BASELINE]["l_share"] - SHIP_L_TOLERANCE
    eligible = [
        name
        for name, t in targets_by_candidate.items()
        if name != BASELINE and t["f_pass"] and t["l_share"] >= l_floor
    ]
    if not eligible:
        return "none"
    best = max(eligible, key=lambda name: targets_by_candidate[name]["s_pool"])
    return best


def _progress(index: int, total: int, label: str) -> None:
    """Print a one-line progress marker every PROGRESS_EVERY_N_CELLS cells."""
    if (index + 1) % PROGRESS_EVERY_N_CELLS == 0 or index + 1 == total:
        print(f"[exp23] {index + 1}/{total} cells ({label})", file=sys.stderr)


def _evaluate_all(
    cells: list,
    factories: list[SignalFactory],
    candidates: dict[str, AcfConfig],
    seeds: range,
    label: str,
) -> dict[str, dict[str, CellOutcome]]:
    """Evaluate every cell for `candidates`, returning cell name -> candidate -> outcome."""
    results: dict[str, dict[str, CellOutcome]] = {}
    for index, (cell, factory) in enumerate(zip(cells, factories, strict=True)):
        results[cell.name] = evaluate_cell(factory, seeds, candidates)
        _progress(index, len(cells), label)
    return results


def _positive_outcomes(
    pos_results: dict[str, dict[str, CellOutcome]], candidate: str
) -> dict[str, CellOutcome]:
    """Extract one candidate's outcomes from the nested positive results."""
    return {name: per[candidate] for name, per in pos_results.items()}


def _fmt_share(share: float | None) -> str:
    """Format a fraction as a percentage with one decimal, or 'n/a'."""
    return "n/a" if share is None else f"{100.0 * share:.1f}%"


def _per_cell_table(
    cells: list,
    candidates: list[str],
    results: dict[str, dict[str, CellOutcome]],
    seeds: range,
) -> list[str]:
    """Build a per-cell markdown table: rows are cells, columns are candidates (percent)."""
    header = "| cell | " + " | ".join(candidates) + " |"
    sep = "| --- | " + " | ".join("---" for _ in candidates) + " |"
    lines = [header, sep]
    for cell in cells:
        row = [f"{cell.name}"]
        for name in candidates:
            share = results[cell.name][name].detected / len(seeds)
            row.append(f"{100.0 * share:.0f}")
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _collapse_reason(reason: str) -> str:
    """Fold every 'irregular (r=...' reason into the single key 'irregular'."""
    return "irregular" if reason.startswith("irregular (r=") else reason


def _reason_table(
    cells: list,
    candidates: list[str],
    results: dict[str, dict[str, CellOutcome]],
) -> list[str]:
    """Build markdown blocks summarising reason counts per candidate over all cells."""
    lines: list[str] = []
    for name in candidates:
        totals: Counter[str] = Counter()
        for cell in cells:
            for reason, count in results[cell.name][name].reason_counts.items():
                totals[_collapse_reason(reason)] += count
        if not totals:
            lines.append(f"- {name}: (no data)")
            continue
        parts = ", ".join(f"{reason or 'regular'}: {count}" for reason, count in totals.items())
        lines.append(f"- {name}: {parts}")
    return lines


def _build_dev_report(
    targets_by_candidate: dict[str, dict],
    winner: str,
    pos_cells: list[PositiveCell],
    neg_cells: list[NegativeCell],
    pos_results: dict[str, dict[str, CellOutcome]],
    neg_results: dict[str, dict[str, CellOutcome]],
    seeds: range,
) -> str:
    """Assemble the markdown report for the development phase."""
    candidates = list(CANDIDATES)
    lines = [
        "# exp23 dev report (synthetic short records)",
        "",
        f"Seeds: dev {DEV_SEEDS.start}..{DEV_SEEDS.stop - 1}",
        "",
        "## Summary",
        "",
        "| candidate | F pass | worst negative cell | pooled neg | S pool | L share "
        "| c3-4 share | snr0.5 share | chosen |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name in candidates:
        t = targets_by_candidate[name]
        chosen = "yes" if name == winner else ""
        lines.append(
            f"| {name} | {'yes' if t['f_pass'] else 'no'} | "
            f"{t['worst_cell']} ({_fmt_share(t['worst_share'])}) | "
            f"{_fmt_share(t['pooled_neg'])} | {_fmt_share(t['s_pool'])} | "
            f"{_fmt_share(t['l_share'])} | {_fmt_share(t['short_share'])} | "
            f"{_fmt_share(t['low_snr_share'])} | {chosen} |"
        )
    lines += ["", f"Winner: **{winner}**", ""]
    lines += ["## Reason counts (positives)", ""]
    lines += _reason_table(pos_cells, candidates, pos_results)
    lines += ["", "## Reason counts (negatives)", ""]
    lines += _reason_table(neg_cells, candidates, neg_results)
    lines += ["", "## Per-cell detection share, negatives (percent)", ""]
    lines += _per_cell_table(neg_cells, candidates, neg_results, seeds)
    lines += ["", "## Per-cell detection share, positives (percent)", ""]
    lines += _per_cell_table(pos_cells, candidates, pos_results, seeds)
    return "\n".join(lines) + "\n"


def _write_report(path: Path, text: str) -> None:
    """Write the report, refusing to overwrite an existing results file."""
    if path.exists():
        raise SystemExit(f"refusing to overwrite existing results file: {path}")
    path.write_text(text, encoding="utf-8")
    print(text)


def run_dev() -> None:
    """Development phase: evaluate all candidates, pick a winner, write results23_dev.md."""
    pos_cells = positive_cells()
    neg_cells = negative_cells()
    pos_results = _evaluate_all(
        pos_cells, [positive_signal_factory(c) for c in pos_cells], CANDIDATES, DEV_SEEDS,
        "positives",
    )
    neg_results = _evaluate_all(
        neg_cells, [negative_signal_factory(c) for c in neg_cells], CANDIDATES, DEV_SEEDS,
        "negatives",
    )
    targets_by_candidate = {}
    for name in CANDIDATES:
        pos_out = _positive_outcomes(pos_results, name)
        neg_out = {cell.name: neg_results[cell.name][name] for cell in neg_cells}
        targets_by_candidate[name] = candidate_targets(
            neg_out, neg_cells, pos_out, pos_cells, DEV_SEEDS
        )
    winner = choose_winner(targets_by_candidate)
    report = _build_dev_report(
        targets_by_candidate, winner, pos_cells, neg_cells, pos_results, neg_results, DEV_SEEDS
    )
    _write_report(HERE / "results23_dev.md", report)


def _verdict(met: bool) -> str:
    """Render a PASS/MISS tag for a target verdict."""
    return "PASS" if met else "MISS"


def ship_decision(cand: dict, base: dict) -> bool:
    """Ship rule: candidate meets F, S beats A by SHIP_S_MARGIN, L within SHIP_L_TOLERANCE of A."""
    return (
        cand["f_pass"]
        and cand["s_pool"] >= base["s_pool"] + SHIP_S_MARGIN
        and cand["l_share"] >= base["l_share"] - SHIP_L_TOLERANCE
    )


def _met(ok: bool) -> str:
    """Render a 'met' / 'not met' tag for an absolute goal."""
    return "met" if ok else "not met"


def _test_summary(candidate: str, targets: dict[str, dict], ship: bool) -> list[str]:
    """Build the verdict block of the test report for the candidate and the baseline A."""
    cand, base = targets[candidate], targets[BASELINE]
    return [
        f"# exp23 test report (synthetic short records): candidate {candidate} vs {BASELINE}",
        "",
        f"Seeds: test {TEST_SEEDS.start}..{TEST_SEEDS.stop - 1}",
        "",
        f"- F (false alarms, {candidate}): {_verdict(cand['f_pass'])} "
        f"(worst cell {cand['worst_cell']} {_fmt_share(cand['worst_share'])}, "
        f"pooled {_fmt_share(cand['pooled_neg'])})",
        f"- S (sensitivity): {candidate} {_fmt_share(cand['s_pool'])}, "
        f"{BASELINE} {_fmt_share(base['s_pool'])}",
        f"- L (long records): {candidate} {_fmt_share(cand['l_share'])}, "
        f"{BASELINE} {_fmt_share(base['l_share'])}",
        f"- Ship: {'yes' if ship else 'no'}",
        f"- S goal 90 % {_met(cand['s_pool'] >= S_MIN)}",
        f"- L goal 98 % {_met(cand['l_share'] >= L_MIN)}",
    ]


def _test_tables(
    pos_cells: list[PositiveCell],
    neg_cells: list[NegativeCell],
    names: list[str],
    pos_results: dict[str, dict[str, CellOutcome]],
    neg_results: dict[str, dict[str, CellOutcome]],
) -> list[str]:
    """Build the reason and per-cell tables of the test report, one column per name."""
    lines = ["", "## Reason counts (positives)", ""]
    lines += _reason_table(pos_cells, names, pos_results)
    lines += ["", "## Reason counts (negatives)", ""]
    lines += _reason_table(neg_cells, names, neg_results)
    lines += ["", "## Per-cell detection share, negatives (percent)", ""]
    lines += _per_cell_table(neg_cells, names, neg_results, TEST_SEEDS)
    lines += ["", "## Per-cell detection share, positives (percent)", ""]
    lines += _per_cell_table(pos_cells, names, pos_results, TEST_SEEDS)
    return lines


def run_test(candidate_name: str) -> None:
    """Test phase: run the candidate and A once on test seeds, apply the ship rule, write report."""
    if candidate_name not in TEST_CHOICES:
        raise SystemExit(f"candidate '{candidate_name}' not allowed in test; use {TEST_CHOICES}")
    names = [candidate_name, BASELINE]
    config = {name: CANDIDATES[name] for name in names}
    pos_cells = positive_cells()
    neg_cells = negative_cells()
    pos_results = _evaluate_all(
        pos_cells, [positive_signal_factory(c) for c in pos_cells], config, TEST_SEEDS,
        "positives",
    )
    neg_results = _evaluate_all(
        neg_cells, [negative_signal_factory(c) for c in neg_cells], config, TEST_SEEDS,
        "negatives",
    )
    targets = {
        name: candidate_targets(
            {cell.name: neg_results[cell.name][name] for cell in neg_cells},
            neg_cells,
            _positive_outcomes(pos_results, name),
            pos_cells,
            TEST_SEEDS,
        )
        for name in names
    }
    ship = ship_decision(targets[candidate_name], targets[BASELINE])
    lines = _test_summary(candidate_name, targets, ship)
    lines += _test_tables(pos_cells, neg_cells, names, pos_results, neg_results)
    _write_report(HERE / "results23_test.md", "\n".join(lines) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the CLI: `dev`, or `test --candidate X`."""
    parser = argparse.ArgumentParser(description="exp23 ACF peak-gate experiment")
    subparsers = parser.add_subparsers(dest="phase", required=True)
    subparsers.add_parser("dev", help="run the development phase")
    test_parser = subparsers.add_parser("test", help="confirm a candidate against A on test seeds")
    test_parser.add_argument("--candidate", required=True, choices=TEST_CHOICES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point: dispatch to dev or test phase."""
    args = parse_args(argv)
    if args.phase == "dev":
        run_dev()
    else:
        run_test(args.candidate)


if __name__ == "__main__":
    main()
