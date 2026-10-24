"""Run the FROZEN exp31 protocol: Courier analyser as soft-sensor input on flotation L1.

Reads the confidential wide analyser CSVs and the long-format lab composites from the paths
given on the command line, scores the four methods on a chronological TEST split, checks the
five pass criteria and prints only aggregate numbers as markdown tables. No data, tags or raw
rows are stored in this file.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Reuse the exploration tooling for wide-CSV reading, windowing, stamp parsing and lab loading,
# so this harness and the alignment study cannot drift apart.
TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import analyzer_vs_lab as reference  # noqa: E402 - path is set up just above
from crosscut_softsensor.long_format import TagSeries, load_long_csv  # noqa: E402

# Protocol constants (FROZEN 2026-10-24; never tuned after the numbers are seen).
WINDOW_END_OFFSET_H = 0.5  # the window ends this many hours before the lab stamp
WINDOW_LENGTH_H = 6.0  # length of the composite window
MIN_VALID_ANALYSER_VALUE = 0.0  # sentinel -9999 and its blend count as missing
TRAIN_FRACTION = 0.6  # first share of usable composites is TRAIN, rounded down
EWMA_WEIGHT = 0.3  # weight of the newest residual in the M3 bias EWMA
EWMA_START = 0.0  # bias before any lab is known
CROSS_VALIDATION_FOLDS = 5
R1_MAX_RMSE_RATIO_M2_OVER_M0 = 0.75
R2_MAX_RMSE_RATIO_M3_OVER_M2 = 1.05
R3_MAX_UNUSABLE_SHARE = 0.10
R5_MAX_RMSE_RATIO_TEST_OVER_CV = 1.25
SECONDS_PER_HOUR = 3600.0

METHOD_NAMES = ("M0", "M1", "M2", "M3")
CRITERIA_IDS = ("R1", "R2", "R3", "R4", "R5")


class ProtocolError(RuntimeError):
    """Raised when the frozen protocol cannot be applied or a leakage check fails."""


@dataclass(frozen=True)
class Target:
    """One target: a name, the analyser tag in the wide CSVs and the lab tag in the long CSV."""

    name: str
    analyser_tag: str
    lab_tag: str
    is_primary: bool


@dataclass(frozen=True)
class Composite:
    """One lab composite with its aligned Courier feature.

    `t_s` is the lab stamp in Unix seconds. `feature` is NaN when the window has too few valid
    minutes (the composite is then unusable). `lab` is the laboratory value.
    """

    t_s: float
    lab: float
    feature: float


@dataclass(frozen=True)
class Calibration:
    """Least-squares straight line lab ~ a + b*feature, frozen on TRAIN."""

    offset: float
    slope: float


@dataclass(frozen=True)
class Scores:
    """TEST-level error metrics of the four methods and the TRAIN cross-validated RMSE of M2."""

    rmse: dict[str, float]
    mae: dict[str, float]
    r2: dict[str, float]
    cv_rmse_m2: float


@dataclass(frozen=True)
class Criteria:
    """PASS/MISS per criterion R1..R5 plus the underlying ratios."""

    verdict: dict[str, str]
    rmse_ratio_m2_over_m0: float
    rmse_ratio_m3_over_m2: float
    unusable_share: float
    rmse_ratio_test_over_cv: float


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the CLI, run each target in turn and print one markdown table per target."""
    try:
        arguments = parse_arguments(argv)
        analyser = load_analyser(arguments.wide_paths, arguments.targets)
        lab_series = load_lab_series(arguments.lab_csv, arguments.targets)
    except (reference.AnalyzerLabError, ProtocolError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for target in arguments.targets:
        print_target_report(target, analyser[target.analyser_tag], lab_series[target.lab_tag])
    return 0


def parse_arguments(argv: Sequence[str] | None) -> Arguments:
    """Parse CLI arguments; the first two --target entries are the primary T1 and T2."""
    parser = build_parser()
    namespace = parser.parse_args(argv)
    targets = tuple(parse_target(text, index) for index, text in enumerate(namespace.target))
    if len(targets) < 2:
        raise ProtocolError("--target must be given at least twice (primary T1 and T2).")
    return Arguments(
        wide_paths=tuple(Path(path) for path in namespace.wide),
        lab_csv=Path(namespace.lab_csv),
        targets=targets,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with the frozen-protocol options only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wide", action="append", required=True, metavar="PATH")
    parser.add_argument("--lab-csv", required=True, metavar="PATH")
    parser.add_argument(
        "--target",
        action="append",
        required=True,
        metavar="NAME:ANALYSER_TAG:LAB_TAG",
        help="repeatable; the first two are primary (T1, T2), the rest secondary",
    )
    return parser


def parse_target(text: str, index: int) -> Target:
    """Split 'NAME:ANALYSER_TAG:LAB_TAG' into a Target; primary when index < 2."""
    parts = text.split(":")
    if len(parts) != 3 or any(not piece.strip() for piece in parts):
        raise ProtocolError(f"--target '{text}' must be 'NAME:ANALYSER_TAG:LAB_TAG'.")
    name, analyser_tag, lab_tag = (piece.strip() for piece in parts)
    return Target(name, analyser_tag, lab_tag, is_primary=index < 2)


def load_analyser(wide_paths: Sequence[Path], targets: Sequence[Target]) -> dict[str, TagSeries]:
    """Read and merge the wide CSVs for every distinct analyser tag, keyed by tag."""
    series_by_tag: dict[str, TagSeries] = {}
    for analyser_tag in sorted({target.analyser_tag for target in targets}):
        series_by_tag[analyser_tag] = reference.load_analyser(
            reference.Arguments(
                wide_paths=tuple(wide_paths),
                analyser_tag=analyser_tag,
                lab_csv=Path("unused"),
                lab_tag=analyser_tag,
                window_h=WINDOW_LENGTH_H,
                shifts_h=np.array([0.0]),
                min_valid=MIN_VALID_ANALYSER_VALUE,
                folds=CROSS_VALIDATION_FOLDS,
            )
        )
    return series_by_tag


def load_lab_series(lab_csv: Path, targets: Sequence[Target]) -> dict[str, TagSeries]:
    """Load every distinct lab tag from the long-format CSV, keyed by tag."""
    lab_tags = {target.lab_tag for target in targets}
    series_by_tag = load_long_csv(lab_csv, tags=lab_tags)
    missing = lab_tags - series_by_tag.keys()
    if missing:
        raise ProtocolError(f"{lab_csv}: lab tags without rows: {', '.join(sorted(missing))}.")
    return series_by_tag


def build_composites(analyser: TagSeries, lab: TagSeries) -> list[Composite]:
    """Feature each lab stamp: mean Courier in [t - 6.5 h, t - 0.5 h], NaN if <50% valid.

    The window is the composite window of length 6 h, ending WINDOW_END_OFFSET_H before the
    stamp; the feature always ends at or before t - 0.5 h (this is check R4b).
    """
    composites: list[Composite] = []
    for stamp_s, lab_value in zip(lab.t_s, lab.values, strict=True):
        window_end_s = stamp_s - WINDOW_END_OFFSET_H * SECONDS_PER_HOUR
        window_start_s = window_end_s - WINDOW_LENGTH_H * SECONDS_PER_HOUR
        if window_end_s > stamp_s:  # invariant of R4b, kept explicit
            raise ProtocolError("feature window must end at or before the lab stamp.")
        feature = reference.window_mean(
            analyser, window_start_s, window_end_s, MIN_VALID_ANALYSER_VALUE
        )
        composites.append(Composite(t_s=stamp_s, lab=float(lab_value), feature=feature))
    return sorted(composites, key=lambda composite: composite.t_s)


def split_train_test(composites: Sequence[Composite]) -> tuple[list[Composite], list[Composite]]:
    """Chronologically split usable composites at the fixed 60 % fraction (rounded down)."""
    usable = [composite for composite in composites if np.isfinite(composite.feature)]
    split_index = int(len(usable) * TRAIN_FRACTION)
    if split_index < 2 or split_index == len(usable):
        raise ProtocolError(f"cannot split {len(usable)} usable composites into TRAIN/TEST.")
    return usable[:split_index], usable[split_index:]


def fit_calibration(train: Sequence[Composite]) -> Calibration:
    """Least-squares lab ~ a + b*feature on TRAIN only."""
    features = np.array([composite.feature for composite in train], dtype=float)
    labs = np.array([composite.lab for composite in train], dtype=float)
    slope, offset = np.polyfit(features, labs, deg=1)
    return Calibration(offset=float(offset), slope=float(slope))


def blocked_cv_rmse(train: Sequence[Composite]) -> float:
    """Held-out RMSE of M2 from contiguous (blocked) folds of the TRAIN row order."""
    features = np.array([composite.feature for composite in train], dtype=float)
    labs = np.array([composite.lab for composite in train], dtype=float)
    predictions = reference.cross_validated_predictions(features, labs, CROSS_VALIDATION_FOLDS)
    return float(np.sqrt(np.mean((labs - predictions) ** 2)))


def known_before(all_composites: Sequence[Composite], composite: Composite) -> list[Composite]:
    """Composites whose lab is known before `composite`'s window ends (all labs, usable or not)."""
    cutoff_s = composite.t_s - WINDOW_END_OFFSET_H * SECONDS_PER_HOUR
    return [item for item in all_composites if item.t_s < cutoff_s]


def predict_m0(test: Sequence[Composite], all_composites: Sequence[Composite]) -> np.ndarray:
    """M0 carry-forward: the most recent lab known before each TEST composite's window ends."""
    predictions = np.empty(len(test), dtype=float)
    for row, composite in enumerate(test):
        earlier = known_before(all_composites, composite)
        if not earlier:
            raise ProtocolError("M0 needs at least one earlier lab before the first TEST row.")
        predictions[row] = earlier[-1].lab
    return predictions


def predict_m2(test: Sequence[Composite], calibration: Calibration) -> np.ndarray:
    """M2 calibrated Courier: a + b*feature."""
    return np.array(
        [calibration.offset + calibration.slope * composite.feature for composite in test],
        dtype=float,
    )


def ewma_bias(known: Sequence[Composite], calibration: Calibration) -> float:
    """EWMA (weight EWMA_WEIGHT, start EWMA_START) of lab - M2 over the usable known composites.

    bias_k = (1 - w) * bias_{k-1} + w * residual_k, in time order.
    """
    bias = EWMA_START
    for item in known:
        if not np.isfinite(item.feature):
            continue
        residual = item.lab - (calibration.offset + calibration.slope * item.feature)
        bias = (1.0 - EWMA_WEIGHT) * bias + EWMA_WEIGHT * residual
    return bias


def predict_m3(test: Sequence[Composite], all_composites: Sequence[Composite],
               calibration: Calibration) -> np.ndarray:
    """M3 = M2 plus the EWMA bias from labs known before each TEST composite's window ends.

    The bias keeps updating through TEST: each composite sees the residuals of every earlier
    composite (TRAIN and TEST), never its own or later labs.
    """
    calibrated = predict_m2(test, calibration)
    biases = [ewma_bias(known_before(all_composites, item), calibration) for item in test]
    return calibrated + np.array(biases, dtype=float)


def leakage_refit_matches(train: Sequence[Composite], calibration: Calibration) -> bool:
    """R4a: refit a, b on TRAIN (no TEST labs present) and check identical coefficients."""
    refit = fit_calibration(train)
    return bool(
        np.isclose(refit.slope, calibration.slope)
        and np.isclose(refit.offset, calibration.offset)
    )


def error_metrics(actual: np.ndarray, predicted: np.ndarray) -> tuple[float, float, float]:
    """Return (RMSE, MAE, R2) of predictions against lab values."""
    residual = actual - predicted
    rmse = float(np.sqrt(np.mean(residual**2)))
    mae = float(np.mean(np.abs(residual)))
    total = float(np.sum((actual - np.mean(actual)) ** 2))
    r2 = float("nan") if total == 0.0 else 1.0 - float(np.sum(residual**2)) / total
    return rmse, mae, r2


def score_methods(test: Sequence[Composite], predictions: dict[str, np.ndarray],
                  cv_rmse_m2: float) -> Scores:
    """Score M0..M3 on TEST and keep the TRAIN cross-validated RMSE of M2."""
    actual = np.array([composite.lab for composite in test], dtype=float)
    rmse: dict[str, float] = {}
    mae: dict[str, float] = {}
    r2: dict[str, float] = {}
    for name in METHOD_NAMES:
        rmse[name], mae[name], r2[name] = error_metrics(actual, predictions[name])
    return Scores(rmse=rmse, mae=mae, r2=r2, cv_rmse_m2=cv_rmse_m2)


def evaluate_target(target: Target, analyser: TagSeries, lab: TagSeries) -> dict[str, object]:
    """Run the whole frozen protocol on one target and return everything a report needs."""
    composites = build_composites(analyser, lab)
    train, test = split_train_test(composites)
    calibration = fit_calibration(train)
    predictions = {
        "M0": predict_m0(test, composites),
        "M1": np.array([composite.feature for composite in test], dtype=float),
        "M2": predict_m2(test, calibration),
        "M3": predict_m3(test, composites, calibration),
    }
    scores = score_methods(test, predictions, blocked_cv_rmse(train))
    unusable_share = circular_unusable_share(composites)
    criteria = check_criteria(scores, unusable_share, train, calibration)
    return {
        "target": target,
        "scores": scores,
        "calibration": calibration,
        "n_train": len(train),
        "n_test": len(test),
        "unusable_share": unusable_share,
        "criteria": criteria,
    }


def circular_unusable_share(composites: Sequence[Composite]) -> float:
    """R3: share of all composites (train and test) whose Courier coverage is below 50 %."""
    if not composites:
        return 1.0
    unusable = sum(1 for composite in composites if not np.isfinite(composite.feature))
    return unusable / len(composites)


def check_criteria(scores: Scores, unusable_share: float, train: Sequence[Composite],
                   calibration: Calibration) -> Criteria:
    """Evaluate R1..R5 (R4a and R4b raise rather than produce a verdict)."""
    ratio_m2_over_m0 = scores.rmse["M2"] / scores.rmse["M0"]
    ratio_m3_over_m2 = scores.rmse["M3"] / scores.rmse["M2"]
    ratio_test_over_cv = scores.rmse["M2"] / scores.cv_rmse_m2
    verdict = {
        "R1": pass_or_miss(ratio_m2_over_m0 <= R1_MAX_RMSE_RATIO_M2_OVER_M0),
        "R2": pass_or_miss(ratio_m3_over_m2 <= R2_MAX_RMSE_RATIO_M3_OVER_M2),
        "R3": pass_or_miss(unusable_share <= R3_MAX_UNUSABLE_SHARE),
        "R4": pass_or_miss(leakage_refit_matches(train, calibration)),
        "R5": pass_or_miss(ratio_test_over_cv <= R5_MAX_RMSE_RATIO_TEST_OVER_CV),
    }
    return Criteria(verdict, ratio_m2_over_m0, ratio_m3_over_m2, unusable_share,
                    ratio_test_over_cv)


def pass_or_miss(is_pass: bool) -> str:
    """Map a boolean to the report word PASS or MISS."""
    return "PASS" if is_pass else "MISS"


def print_target_report(target: Target, analyser: TagSeries, lab: TagSeries) -> None:
    """Print one markdown table for a target; criteria columns only on primary targets."""
    result = evaluate_target(target, analyser, lab)
    scores = result["scores"]
    calibration = result["calibration"]
    criteria = result["criteria"]
    kind = "primary" if target.is_primary else "secondary (reported, no criteria)"
    print(f"\n### {target.name} ({kind})\n")
    if target.is_primary:
        print_criteria_row(criteria)
    print_score_table(scores)
    print_summary_row(result, calibration)
    print(
        f"\nR1 M2/M0={criteria.rmse_ratio_m2_over_m0:.3f}  "
        f"R2 M3/M2={criteria.rmse_ratio_m3_over_m2:.3f}  "
        f"R3 unusable={criteria.unusable_share:.3f}  "
        f"R5 TEST/CV={criteria.rmse_ratio_test_over_cv:.3f}"
    )


def print_criteria_row(criteria: Criteria) -> None:
    """Print the PASS/MISS verdict row for R1..R5."""
    verdicts = " | ".join(criteria.verdict[criterion] for criterion in CRITERIA_IDS)
    headers = " | ".join(CRITERIA_IDS)
    print(f"| {headers} |")
    print("|" + "---|" * len(CRITERIA_IDS))
    print(f"| {verdicts} |\n")


def print_score_table(scores: Scores) -> None:
    """Print RMSE, MAE and R2 of M0..M3 on TEST."""
    print("| method | RMSE | MAE | R2 |")
    print("|---|---|---|---|")
    for name in METHOD_NAMES:
        print(f"| {name} | {scores.rmse[name]:.4f} | {scores.mae[name]:.4f} "
              f"| {scores.r2[name]:.4f} |")


def print_summary_row(result: dict[str, object], calibration: Calibration) -> None:
    """Print the TRAIN calibration, composite counts and unusable share."""
    print(
        f"\ntrain a={calibration.offset:.4f}  b={calibration.slope:.4f}  "
        f"n_train={result['n_train']}  n_test={result['n_test']}  "
        f"CV RMSE (M2)={result['scores'].cv_rmse_m2:.4f}  "
        f"unusable share={result['unusable_share']:.3f}"
    )


@dataclass(frozen=True)
class Arguments:
    """Parsed command-line arguments for the exp31 harness."""

    wide_paths: tuple[Path, ...]
    lab_csv: Path
    targets: tuple[Target, ...]


if __name__ == "__main__":
    raise SystemExit(main())
