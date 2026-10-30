"""Compare an online analyser with a lab composite tag and report their time alignment.

Interim tool from the plant-1 validation work; to be absorbed into the generic
virtual-sensor engine in Phase 4a of docs/PRODUCT.md.

Loads the 1-minute analyser series from one or more wide CSVs and the lab composite stamps
from a long-format historian export, slides a fixed-length window over the analyser to
match each lab stamp, prints Pearson r for each candidate shift, and fits a one-feature
linear calibration with blocked cross-validation for the best shift. Analysis only.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.csv as pa_csv
from crosscut_softsensor.long_format import TagSeries, load_long_csv

TIMESTAMP_COLUMN = "timestamp"
SECONDS_PER_HOUR = 3600.0
MIN_FINITE_FRACTION = 0.5
MIN_ROWS = 20
NAN = float("nan")


class AnalyzerLabError(RuntimeError):
    """Raised when the analysis cannot proceed (unknown tag, too few rows)."""


@dataclass(frozen=True)
class Arguments:
    """Parsed command-line arguments for the analyser-versus-lab comparison."""

    wide_paths: tuple[Path, ...]
    analyser_tag: str
    lab_csv: Path
    lab_tag: str
    window_h: float
    shifts_h: np.ndarray
    min_valid: float
    folds: int


@dataclass(frozen=True)
class ShiftResult:
    """Outcome of aligning lab stamps to the analyser window at one shift."""

    shift_h: float
    features: np.ndarray
    labs: np.ndarray
    correlation: float


@dataclass(frozen=True)
class Calibration:
    """Linear calibration lab ~ a + b*x with blocked cross-validation scores."""

    slope: float
    offset: float
    cv_r2: float
    cv_rmse: float
    lab_sd: float


def main(argv: Sequence[str] | None = None) -> int:
    """Run the analyser-vs-lab comparison and print a compact text report. Returns the exit code."""
    try:
        arguments = parse_arguments(argv)
        analyser = load_analyser(arguments)
        lab = load_lab(arguments.lab_csv, arguments.lab_tag)
        results = [score_shift(analyser, lab, arguments, shift) for shift in arguments.shifts_h]
        best = best_shift(results)
    except AnalyzerLabError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if len(best.features) < MIN_ROWS:
        print(
            f"error: only {len(best.features)} aligned rows, need at least {MIN_ROWS}.",
            file=sys.stderr,
        )
        return 2
    calibration = calibrate(best, arguments.folds)
    print_report(results, best, calibration)
    return 0


def parse_arguments(argv: Sequence[str] | None) -> Arguments:
    """Parse CLI arguments into an `Arguments` dataclass."""
    parser = _build_parser()
    namespace = parser.parse_args(argv)
    return Arguments(
        wide_paths=tuple(Path(path) for path in namespace.wide),
        analyser_tag=namespace.analyser,
        lab_csv=Path(namespace.lab_csv),
        lab_tag=namespace.lab_tag,
        window_h=namespace.window_h,
        shifts_h=parse_shifts(namespace.shifts_h),
        min_valid=namespace.min_valid,
        folds=namespace.folds,
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all documented options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wide", action="append", required=True, metavar="PATH")
    parser.add_argument("--analyser", required=True, metavar="TAG")
    parser.add_argument("--lab-csv", required=True, metavar="PATH")
    parser.add_argument("--lab-tag", required=True, metavar="NAME")
    parser.add_argument("--window-h", type=float, default=6.0, metavar="FLOAT")
    parser.add_argument("--shifts-h", default="-3,3,0.5", metavar="TEXT")
    parser.add_argument("--min-valid", type=float, default=0.0, metavar="FLOAT")
    parser.add_argument("--folds", type=int, default=5, metavar="INT")
    return parser


def parse_shifts(text: str) -> np.ndarray:
    """Parse "start,stop,step" into an inclusive ascending array of shifts in hours."""
    parts = [piece.strip() for piece in text.split(",")]
    if len(parts) != 3:
        raise AnalyzerLabError(f"--shifts-h must be 'start,stop,step', got '{text}'.")
    start, stop, step = (float(piece) for piece in parts)
    if step <= 0.0:
        raise AnalyzerLabError(f"--shifts-h step must be positive, got {step}.")
    return np.arange(start, stop + step / 2.0, step)


def load_analyser(arguments: Arguments) -> TagSeries:
    """Read the analyser column from every wide CSV and merge into one sorted series."""
    pieces = [read_wide_file(path, arguments.analyser_tag) for path in arguments.wide_paths]
    times = np.concatenate([piece.t_s for piece in pieces])
    values = np.concatenate([piece.values for piece in pieces])
    return build_series(arguments.analyser_tag, times, values)


def read_wide_file(path: Path, analyser_tag: str) -> TagSeries:
    """Read only the timestamp and analyser columns from one wide CSV into a `TagSeries`."""
    options = pa_csv.ConvertOptions(
        include_columns=[TIMESTAMP_COLUMN, analyser_tag],
        column_types={TIMESTAMP_COLUMN: pa.string()},
    )
    try:
        table = pa_csv.read_csv(path, convert_options=options)
    except (pyarrow_error(), OSError) as error:
        raise AnalyzerLabError(f"cannot read {path}: {error}") from error
    if analyser_tag not in table.column_names:
        raise AnalyzerLabError(f"{path}: no column '{analyser_tag}'.")
    stamps = table.column(TIMESTAMP_COLUMN).to_pylist()
    values = table.column(analyser_tag).to_numpy(zero_copy_only=False).astype(float)
    times = np.array([parse_wall_clock(stamp) for stamp in stamps], dtype=float)
    return build_series(analyser_tag, times, values)


def pyarrow_error() -> type[BaseException]:
    """Return the pyarrow CSV error type without importing it at module scope."""
    import pyarrow  # noqa: PLC0415 - kept local so a missing pyarrow raises a clear message

    return pyarrow.ArrowException


def parse_wall_clock(text: str) -> float:
    """Parse a 'YYYY-MM-DD HH:MM:SS' wall-clock stamp into Unix seconds (treated as UTC)."""
    from datetime import UTC, datetime  # noqa: PLC0415 - tiny helper, avoids a global import

    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp()
    except ValueError as error:
        message = f"bad timestamp '{text}', expected 'YYYY-MM-DD HH:MM:SS'."
        raise AnalyzerLabError(message) from error


def build_series(tag: str, times: np.ndarray, values: np.ndarray) -> TagSeries:
    """Mask values below the min-valid threshold later; drop duplicates and sort by time."""
    order = np.argsort(times, kind="stable")
    sorted_times = times[order]
    sorted_values = values[order]
    keep_first = np.concatenate(([True], np.diff(sorted_times) > 0.0))
    return TagSeries(tag=tag, t_s=sorted_times[keep_first], values=sorted_values[keep_first])


def load_lab(path: Path, tag: str) -> TagSeries:
    """Load the lab composite tag from a long-format CSV."""
    series_by_tag = load_long_csv(path, tags={tag})
    if tag not in series_by_tag:
        raise AnalyzerLabError(f"{path}: lab tag '{tag}' has no rows.")
    return series_by_tag[tag]


def score_shift(
    analyser: TagSeries, lab: TagSeries, arguments: Arguments, shift_h: float
) -> ShiftResult:
    """Align lab stamps to analyser windows at one shift and compute the feature correlation."""
    features, labs = align_shift(analyser, lab, arguments.window_h, shift_h, arguments)
    return ShiftResult(shift_h=shift_h, features=features, labs=labs,
                       correlation=pearson(features, labs))


def align_shift(
    analyser: TagSeries, lab: TagSeries, window_h: float, shift_h: float, arguments: Arguments
) -> tuple[np.ndarray, np.ndarray]:
    """Build aligned (feature, lab) arrays; rows without enough finite analyser samples drop out."""
    half_span_h = window_h + max(abs(arguments.shifts_h.min()), abs(arguments.shifts_h.max()))
    features: list[float] = []
    labs: list[float] = []
    for stamp_s, lab_value in zip(lab.t_s, lab.values, strict=True):
        if not analyser_records_cover(analyser, stamp_s, half_span_h):
            continue
        start_s = stamp_s + (shift_h - window_h) * SECONDS_PER_HOUR
        stop_s = stamp_s + shift_h * SECONDS_PER_HOUR
        feature = window_mean(analyser, start_s, stop_s, arguments.min_valid)
        if np.isfinite(feature):
            features.append(feature)
            labs.append(lab_value)
    return np.array(features, dtype=float), np.array(labs, dtype=float)


def analyser_records_cover(analyser: TagSeries, stamp_s: float, half_span_h: float) -> bool:
    """Return True if the analyser record fully covers stamp_s +/- half_span_h."""
    if len(analyser.t_s) == 0:
        return False
    span_s = half_span_h * SECONDS_PER_HOUR
    return analyser.t_s[0] <= stamp_s - span_s and stamp_s + span_s <= analyser.t_s[-1]


def window_mean(analyser: TagSeries, start_s: float, stop_s: float, min_valid: float) -> float:
    """Mean of finite analyser values in [start_s, stop_s]; NaN if too few are valid."""
    mask = (analyser.t_s >= start_s) & (analyser.t_s <= stop_s)
    values = analyser.values[mask]
    valid = values[np.isfinite(values) & (values >= min_valid)]
    if len(values) == 0 or len(valid) < MIN_FINITE_FRACTION * len(values):
        return NAN
    return float(np.mean(valid))


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    """Pearson correlation; NaN when either series is constant or too short."""
    if len(x) < 2 or np.std(x) == 0.0 or np.std(y) == 0.0:
        return NAN
    return float(np.corrcoef(x, y)[0, 1])


def best_shift(results: list[ShiftResult]) -> ShiftResult:
    """Return the ShiftResult with the largest finite correlation."""
    finite = [result for result in results if np.isfinite(result.correlation)]
    if not finite:
        raise AnalyzerLabError("no shift produced a finite correlation.")
    return max(finite, key=lambda result: result.correlation)


def calibrate(result: ShiftResult, folds: int) -> Calibration:
    """Fit lab ~ a + b*x on all rows and report blocked cross-validated R2, RMSE and lab SD."""
    slope, offset = np.polyfit(result.features, result.labs, deg=1)
    predictions = cross_validated_predictions(result.features, result.labs, folds)
    residuals = result.labs - predictions
    sse = float(np.sum(residuals**2))
    sst = float(np.sum((result.labs - np.mean(result.labs)) ** 2))
    r2 = NAN if sst == 0.0 else 1.0 - sse / sst
    rmse = float(np.sqrt(sse / len(result.labs)))
    return Calibration(slope=float(slope), offset=float(offset), cv_r2=r2,
                       cv_rmse=rmse, lab_sd=float(np.std(result.labs, ddof=1)))


def cross_validated_predictions(features: np.ndarray, labs: np.ndarray, folds: int) -> np.ndarray:
    """Held-out predictions from contiguous folds of the row order."""
    indices = np.arange(len(features))
    predictions = np.empty(len(features), dtype=float)
    for test_indices in np.array_split(indices, folds):
        train = np.setdiff1d(indices, test_indices)
        slope, offset = np.polyfit(features[train], labs[train], deg=1)
        predictions[test_indices] = slope * features[test_indices] + offset
    return predictions


def print_report(results: list[ShiftResult], best: ShiftResult, calibration: Calibration) -> None:
    """Print one line per shift, then the calibration summary and the shift-sign note."""
    for result in results:
        n_rows = len(result.features)
        print(f"shift {result.shift_h:+5.1f} h  n={n_rows:4d}  r={result.correlation:.3f}")
    print(
        f"best shift {best.shift_h:+.1f} h  n={len(best.features)}  "
        f"CV R2={calibration.cv_r2:.3f}  RMSE={calibration.cv_rmse:.3f}  "
        f"lab SD={calibration.lab_sd:.3f}  slope={calibration.slope:.4f}  "
        f"offset={calibration.offset:.4f}"
    )
    print("best shift negative = the stamp is later than the end of the composite window")


if __name__ == "__main__":
    raise SystemExit(main())
