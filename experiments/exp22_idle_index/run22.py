"""Harness for experiment 22 (idle index on simulated PI loops): dev and test runs.

Runs the frozen protocol of the README: dev chooses the flag threshold from the grid,
test confirms the sensitivity (S1) and false-flag (F1) targets. Writes a markdown report
and refuses to overwrite previous results, so frozen decisions cannot be silently rerun.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import g22_loops  # noqa: E402
from idle_index_draft import idle_index  # noqa: E402

THETAS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)  # candidate flag thresholds [-]
FALSE_SHARE_POOLED_MAX = 0.10  # F1 target, pooled over good + aggressive [-]
FALSE_SHARE_CELL_MAX = 0.25  # dev condition, worst plant x disturbance cell [-]
SENSITIVITY_MIN = 0.80  # S1 target, sluggish flag share [-]
DEFAULT_THETA = 0.3  # breakdown threshold when no grid value meets the dev condition
CALM_TUNINGS = ("good", "aggressive")  # tunings that must not be flagged
PROGRESS_EVERY = 20  # cases between stderr progress lines [-]

RESULTS_DEV = "results22_dev.md"
RESULTS_TEST = "results22_test.md"


def evaluate(seeds) -> list[dict]:
    """Run every case for every seed; return one flat record per (case, seed)."""
    records = []
    cases = g22_loops.all_cases()
    for case_index, case in enumerate(cases):
        for seed in seeds:
            records.append(_evaluate_one(case, seed))
        if (case_index + 1) % PROGRESS_EVERY == 0:
            print(f"evaluated {case_index + 1}/{len(cases)} cases", file=sys.stderr)
    return records


def _evaluate_one(case: g22_loops.Case, seed: int) -> dict:
    """Simulate one loop and run the detector; return the record for the report."""
    run = g22_loops.simulate(case, seed)
    result = idle_index(run["pv"], run["sp"], run["out"], g22_loops.DT_S)
    return {
        "gain": case.gain,
        "tau_s": case.tau_s,
        "theta_s": case.theta_s,
        "tuning": case.tuning,
        "disturbance": case.disturbance,
        "noise_fraction": case.noise_fraction,
        "seed": seed,
        "value": result.value,
        "gain_sign": result.gain_sign,
        "true_gain_sign": run["true_gain_sign"],
        "reason": result.reason,
    }


def is_flagged(record: dict, theta: float) -> bool:
    """Flag rule: a None value never flags."""
    value = record["value"]
    return value is not None and value > theta


def share(records: list[dict], predicate) -> float:
    """Share of records satisfying predicate; 0.0 for an empty list."""
    if not records:
        return 0.0
    return sum(1 for record in records if predicate(record)) / len(records)


def false_share(records: list[dict], theta: float) -> float:
    """False-flag share over good + aggressive records."""
    calm = [record for record in records if record["tuning"] in CALM_TUNINGS]
    return share(calm, lambda record: is_flagged(record, theta))


def tuning_share(records: list[dict], tuning: str, theta: float) -> float:
    """Flag share within one tuning."""
    subset = [record for record in records if record["tuning"] == tuning]
    return share(subset, lambda record: is_flagged(record, theta))


def _plant_key(record: dict) -> tuple[float, float, float]:
    """Plant identity as (gain, tau_s, theta_s)."""
    return (record["gain"], record["tau_s"], record["theta_s"])


def _share_by(records: list[dict], key_function, theta: float) -> dict:
    """Flag share grouped by a key function; keys are returned with their group size."""
    groups: dict = {}
    for record in records:
        groups.setdefault(key_function(record), []).append(record)
    return {
        key: (share(group, lambda record: is_flagged(record, theta)), len(group))
        for key, group in groups.items()
    }


def worst_cell_share(records: list[dict], theta: float) -> tuple[float, str]:
    """Worst false-flag share over (plant, disturbance) cells; name of that cell."""
    calm = [record for record in records if record["tuning"] in CALM_TUNINGS]
    by_cell = _share_by(calm, lambda record: (_plant_key(record), record["disturbance"]), theta)
    if not by_cell:
        return 0.0, "no cells"
    cell, (cell_share, _) = max(by_cell.items(), key=lambda item: item[1][0])
    plant, disturbance = cell
    name = f"K={plant[0]:g} tau={plant[1]:g} theta={plant[2]:g} {disturbance}"
    return cell_share, name


def meets_dev_condition(records: list[dict], theta: float) -> bool:
    """Dev condition: pooled false share <= 0.10 and worst cell <= 0.25."""
    worst_share, _ = worst_cell_share(records, theta)
    return (
        false_share(records, theta) <= FALSE_SHARE_POOLED_MAX
        and worst_share <= FALSE_SHARE_CELL_MAX
    )


def choose_theta(records: list[dict]) -> float | None:
    """Smallest theta in the grid that meets the dev condition, or None."""
    for theta in THETAS:
        if meets_dev_condition(records, theta):
            return theta
    return None


def _format_float(value: float | None) -> str:
    """Format an optional float for a markdown table."""
    return "None" if value is None else f"{value:.3f}"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    """Render a markdown table from a header and rows of strings."""
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def theta_table(records: list[dict]) -> list[str]:
    """Table of every candidate theta: pooled false, worst cell, S1, mild, condition."""
    rows = []
    for theta in THETAS:
        worst_share, worst_name = worst_cell_share(records, theta)
        rows.append(
            [
                f"{theta:.1f}",
                _format_float(false_share(records, theta)),
                _format_float(worst_share),
                worst_name,
                _format_float(tuning_share(records, "sluggish", theta)),
                _format_float(tuning_share(records, "mild", theta)),
                "yes" if meets_dev_condition(records, theta) else "no",
            ]
        )
    header = ["theta", "false (pooled)", "worst cell", "worst cell name", "sluggish", "mild",
              "meets"]
    return _table(header, rows)


def _named_share_lines(records: list[dict], key_function, theta: float,
                       value_labels: bool = False) -> list[str]:
    """One line per group: flag share (or value stats) and count."""
    by_group = _share_by(records, key_function, theta)
    lines = []
    for key in sorted(by_group, key=str):
        group_share, count = by_group[key]
        lines.append(f"- `{key}`: flag share {group_share:.2f} (n={count})")
    return lines


def breakdown_lines(records: list[dict], theta: float) -> list[str]:
    """Flag shares by tuning x disturbance, tuning x noise and tuning x plant."""
    lines = ["### Flag share by tuning x disturbance", ""]
    groups = _share_by(records, lambda r: (r["tuning"], r["disturbance"]), theta)
    lines += _format_group_lines(groups)
    lines += ["", "### Flag share by tuning x noise fraction", ""]
    groups = _share_by(records, lambda r: (r["tuning"], r["noise_fraction"]), theta)
    lines += _format_group_lines(groups)
    lines += ["", "### Flag share by tuning x plant", ""]
    groups = _share_by(records, lambda r: (r["tuning"], _plant_key(r)), theta)
    lines += _format_group_lines(groups)
    return lines


def _format_group_lines(groups: dict) -> list[str]:
    """Render (share, count) group values as markdown bullet lines."""
    lines = []
    for key in sorted(groups, key=str):
        group_share, count = groups[key]
        lines.append(f"- `{key}`: {group_share:.2f} (n={count})")
    return lines


def none_and_gain_sign_lines(records: list[dict]) -> list[str]:
    """None share with reason counts per tuning; gain-sign accuracy per tuning and pooled."""
    lines = ["### None values per tuning (reasons)", ""]
    for tuning in g22_loops.TUNINGS:
        subset = [record for record in records if record["tuning"] == tuning]
        none_records = [record for record in subset if record["value"] is None]
        reasons = Counter(record["reason"] for record in none_records)
        reasons_text = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())) or "none"
        lines.append(
            f"- `{tuning}`: None share {share(none_records, lambda r: True):.2f} "
            f"(n={len(subset)}), reasons: {reasons_text}"
        )
    lines += ["", "### Gain-sign accuracy", ""]
    known = [record for record in records if record["gain_sign"] is not None]
    correct = [record for record in known if record["gain_sign"] == record["true_gain_sign"]]
    lines.append(f"- pooled: {len(correct)}/{len(known)}")
    for tuning in g22_loops.TUNINGS:
        subset = [record for record in known if record["tuning"] == tuning]
        hits = sum(1 for record in subset if record["gain_sign"] == record["true_gain_sign"])
        lines.append(f"- `{tuning}`: {hits}/{len(subset)}")
    return lines


def value_statistics_lines(records: list[dict]) -> list[str]:
    """Mean and quartiles of the idle index value per tuning (None values excluded)."""
    lines = ["### Idle index value per tuning (non-None)", ""]
    rows = []
    for tuning in g22_loops.TUNINGS:
        values = [r["value"] for r in records if r["tuning"] == tuning and r["value"] is not None]
        if not values:
            rows.append([tuning, "0", "-", "-", "-", "-"])
            continue
        array = np.array(values)
        quartiles = np.percentile(array, [25, 50, 75])
        rows.append(
            [tuning, str(len(values)), f"{array.mean():.3f}", f"{quartiles[0]:.3f}",
             f"{quartiles[1]:.3f}", f"{quartiles[2]:.3f}"]
        )
    return lines + _table(["tuning", "n", "mean", "q25", "median", "q75"], rows)


def write_report(path: Path, lines: list[str]) -> None:
    """Write the report, refusing to overwrite an existing file."""
    if path.exists():
        raise SystemExit(f"{path} already exists; move it away before rerunning")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_dev() -> int:
    """Development run: choose theta, report every candidate and the breakdowns."""
    records = evaluate(g22_loops.DEV_SEEDS)
    chosen = choose_theta(records)
    lines = ["# exp22 idle index: development run", ""]
    lines.append("## Candidate thetas")
    lines += theta_table(records)
    lines += ["", f"Chosen theta: `{chosen}`"]
    report_theta = chosen if chosen is not None else DEFAULT_THETA
    lines += ["", f"Breakdowns at theta = {report_theta:.1f} (for information)"]
    lines += [""]
    lines += breakdown_lines(records, report_theta)
    lines += [""]
    lines += none_and_gain_sign_lines(records)
    lines += [""]
    lines += value_statistics_lines(records)
    lines += ["", "## Dev S1"]
    sluggish_share = tuning_share(records, "sluggish", report_theta)
    verdict = "met" if sluggish_share >= SENSITIVITY_MIN else "not met"
    lines.append(f"- sluggish flag share {sluggish_share:.2f} (target >= {SENSITIVITY_MIN}) "
                 f"{verdict}")
    text = "\n".join(lines)
    write_report(HERE / RESULTS_DEV, lines)
    print(text)
    return 0


def run_test(theta: float) -> int:
    """Test run: confirm S1 and F1 at the given theta, report breakdowns."""
    records = evaluate(g22_loops.TEST_SEEDS)
    sluggish_share = tuning_share(records, "sluggish", theta)
    false_pooled = false_share(records, theta)
    s1_verdict = "PASS" if sluggish_share >= SENSITIVITY_MIN else "MISS"
    f1_verdict = "PASS" if false_pooled <= FALSE_SHARE_POOLED_MAX else "MISS"
    lines = [f"# exp22 idle index: test run at theta = {theta:.1f}", ""]
    lines.append(f"- S1 (sluggish share >= {SENSITIVITY_MIN}): {sluggish_share:.2f} {s1_verdict}")
    lines.append(f"- F1 (good+aggressive <= {FALSE_SHARE_POOLED_MAX}): {false_pooled:.2f} "
                 f"{f1_verdict}")
    lines += [""]
    lines += breakdown_lines(records, theta)
    lines += [""]
    lines += none_and_gain_sign_lines(records)
    lines += [""]
    lines += value_statistics_lines(records)
    text = "\n".join(lines)
    write_report(HERE / RESULTS_TEST, lines)
    print(text)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the command line: `dev` or `test --theta X`."""
    parser = argparse.ArgumentParser(description="exp22 idle index harness")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("dev", help="development run, chooses theta")
    test_parser = sub.add_parser("test", help="test run at a frozen theta")
    test_parser.add_argument("--theta", type=float, choices=THETAS, required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Entry point: dispatch to the dev or test run."""
    args = parse_args(argv)
    if args.command == "dev":
        return run_dev()
    return run_test(args.theta)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
