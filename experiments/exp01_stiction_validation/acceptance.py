"""Acceptance experiment for crosscut_loops.stiction.detect_stiction.

Runs a grid of sticking (positive) and healthy (negative) valve cases over 20 seeds, splits the
seeds into a development and a held-out set, and reports per-class detection and false-alarm
rates with a Wilson upper bound. Writes a markdown report next to this file.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import math
from pathlib import Path

import cases
from crosscut_loops.stiction import detect_stiction

# ---- experiment grid -------------------------------------------------------------------------
SEEDS = tuple(range(1, 21))  # 1..20
DEVELOPMENT_SEEDS = SEEDS[:10]  # seeds 1..10
HELD_OUT_SEEDS = SEEDS[10:]  # seeds 11..20
STICKING_BANDS_PERCENT = (2.0, 4.0, 6.0, 8.0)  # valve sticking bands to test, percent
NOISES = ("low", "full")
SETTLING_TIME_S = 7200.0  # drop the first 2 h so transient behaviour never reaches the detector
MAX_WORKERS = 4
WILSON_Z = 1.96  # 95% two-sided normal quantile
RESULTS_PATH = Path(__file__).resolve().parent / "results" / "acceptance.md"
POSITIVE_SECOND_COLUMN = "detection rate"
NEGATIVE_SECOND_COLUMN = "false-alarm rate"


@dataclasses.dataclass(frozen=True)
class Row:
    """One report line: a class and noise level measured over a set of seeds."""

    class_name: str
    noise: str
    seed_set: str
    verdicts: tuple[str, ...]


def positive_cases() -> dict[str, cases.Case]:
    """Sticking-valve cases, keyed by the class name used in the report."""

    def build(band_percent: float, noise: str) -> cases.Case:
        """Build one sticking-valve case for a sticking band and a noise level."""
        return cases.Case(band_percent=band_percent, noise=noise)

    return {
        f"sticking band {band:g}% ({noise} noise)": build(band, noise)
        for band in STICKING_BANDS_PERCENT
        for noise in NOISES
    }


def negative_cases() -> dict[str, cases.Case]:
    """Healthy-valve cases that may oscillate for reasons other than stiction, keyed by name."""

    def build(noise: str, **kwargs: object) -> cases.Case:
        """Build one healthy-valve case; the keyword arguments set the tuning or forcing."""
        return cases.Case(band_percent=0.0, noise=noise, **kwargs)  # type: ignore[arg-type]

    classes = {
        "nominal wander": {},
        "aggressive tuning": {"tuning": "aggressive"},
        "sine forcing": {"forcing": "sine"},
        "square forcing (adversarial)": {"forcing": "square"},
    }
    return {
        f"{name} ({noise} noise)": build(noise, **kwargs)
        for name, kwargs in classes.items()
        for noise in NOISES
    }


def settle(pv, out, dt_s: float):
    """Trim the PV/OUT arrays to the settled window so the detector ignores the transient."""

    first = int(SETTLING_TIME_S / dt_s)
    return pv[first:], out[first:]


def classify(case: cases.Case, seed: int) -> str:
    """Run one case and return the detector verdict; module-level so it pickles for processes."""
    pv, out, dt_s = cases.simulate_case(case, seed)
    pv_settled, out_settled = settle(pv, out, dt_s)
    return detect_stiction(pv_settled, out_settled, dt_s).verdict


def run_class(case: cases.Case) -> dict[str, tuple[str, ...]]:
    """Classify every seed for one case; return verdicts per seed set (development, held-out)."""
    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future = {seed: pool.submit(classify, case, seed) for seed in SEEDS}
        verdicts = {seed: future[seed].result() for seed in SEEDS}
    return {
        "development": tuple(verdicts[seed] for seed in DEVELOPMENT_SEEDS),
        "held-out": tuple(verdicts[seed] for seed in HELD_OUT_SEEDS),
    }


def summarise(verdicts: list[str]) -> dict[str, int]:
    """Count verdicts by name; every verdict string in the detector's vocabulary is a key."""
    return {
        "n": len(verdicts),
        "stiction": verdicts.count("stiction"),
        "no_stiction": verdicts.count("no_stiction"),
        "inconclusive": verdicts.count("inconclusive"),
    }


def wilson_upper(successes: int, sample_count: int) -> float:
    """95% Wilson score upper bound for a proportion.

    p_hat + z^2/2n + z*sqrt(p_hat(1-p_hat)/n + z^2/4n^2), all over (1 + z^2/n).
    At n = 0 the bound is 1.0: no evidence of a low rate.
    """
    if sample_count == 0:
        return 1.0
    p_hat = successes / sample_count
    z_squared = WILSON_Z * WILSON_Z
    centre = p_hat + z_squared / (2.0 * sample_count)
    spread = WILSON_Z * math.sqrt(
        p_hat * (1.0 - p_hat) / sample_count + z_squared / (4.0 * sample_count * sample_count)
    )
    return min(1.0, (centre + spread) / (1.0 + z_squared / sample_count))


def _format_percent_rows(rows: list[Row], is_positive: bool) -> list[str]:
    """Render the markdown rows for one table, one seed set per row."""
    label = POSITIVE_SECOND_COLUMN if is_positive else NEGATIVE_SECOND_COLUMN
    lines = [
        f"| class | noise | seed set | n | stiction | no_stiction | inconclusive | {label} |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        counts = summarise(list(row.verdicts))
        if is_positive:
            value = _percent(counts["stiction"] / counts["n"]) if counts["n"] else "n/a"
        else:
            value = _upper_bound_text(counts["no_stiction"], counts["n"], row.verdicts)
        lines.append(
            f"| {row.class_name} | {row.noise} | {row.seed_set} | {counts['n']} | "
            f"{counts['stiction']} | {counts['no_stiction']} | {counts['inconclusive']} | {value} |"
        )
    return lines


def _percent(rate: float) -> str:
    """Format a proportion as a percentage with one decimal."""
    return f"{rate * 100:.1f}%"


def _upper_bound_text(successes: int, sample_count: int, verdicts: tuple[str, ...]) -> str:
    """False-alarm rate over the alarming verdicts, with its Wilson upper bound."""
    if sample_count == 0:
        return "n/a"
    false_alarms = verdicts.count("stiction")
    rate = _percent(false_alarms / sample_count)
    bound = _percent(wilson_upper(false_alarms, sample_count))
    return f"{rate} (95% UB {bound})"


def format_table(rows: list[Row]) -> str:
    """Render one markdown table; the column meaning differs for positives and negatives."""
    is_positive = rows[0].class_name.startswith("sticking band") if rows else True
    return "\n".join(_format_percent_rows(rows, is_positive))


def build_rows(
    title_class: str, named_cases: dict[str, cases.Case]
) -> tuple[list[Row], list[Row]]:
    """Evaluate every class and split the results into development and held-out rows."""
    development_rows: list[Row] = []
    held_out_rows: list[Row] = []
    for name, case in named_cases.items():
        verdicts_by_set = run_class(case)
        class_name = name if title_class == "positive" else name
        noise = case.noise
        development_rows.append(
            Row(class_name, noise, "development", verdicts_by_set["development"])
        )
        held_out_rows.append(Row(class_name, noise, "held-out", verdicts_by_set["held-out"]))
    return development_rows, held_out_rows


def render_report(positive: dict[str, cases.Case], negative: dict[str, cases.Case]) -> str:
    """Build the full markdown report: one table for positives, one for negatives."""
    positive_dev, positive_held = build_rows("positive", positive)
    negative_dev, negative_held = build_rows("negative", negative)
    sections = [
        "# Stiction detector acceptance report",
        "",
        "Seeds 1..10: development, seeds 11..20: held-out. "
        f"First {SETTLING_TIME_S / 3600.0:g} h dropped as settling time.",
        "",
        "## Positives (valve sticks)",
        "",
        format_table(positive_dev + positive_held),
        "",
        "## Negatives (healthy valve)",
        "",
        format_table(negative_dev + negative_held),
        "",
    ]
    return "\n".join(sections)


def main() -> None:
    """Run the whole acceptance experiment and write (and print) the markdown report."""
    report = render_report(positive_cases(), negative_cases())
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
