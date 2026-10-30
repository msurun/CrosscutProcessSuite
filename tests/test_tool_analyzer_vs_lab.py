"""Tests for tools/analyzer_vs_lab.py.

The CLI is loaded by path (it is not an installed package), driven through main([...]) and
checked through its printed report. Synthetic CSVs are placed in tmp_path: an analyser
random walk and a lab composite built as lab = 2*mean(window ending 1 h before the stamp) + 0.5.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "analyzer_vs_lab.py"
ANALYSER_TAG = "an_tag"
LAB_TAG = "lab_composite"
STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
SECONDS_PER_DAY = 86400
SAMPLES_PER_DAY = 1440
WINDOW_HOURS = 6.0
TRUE_SHIFT_HOURS = -1.0
SLOPE = 2.0
OFFSET = 0.5
SENTINEL = -9999.0


def load_tool_module() -> ModuleType:
    """Import the tool by file path so dataclasses resolve (module must be in sys.modules)."""
    spec = importlib.util.spec_from_file_location("tool_analyzer_vs_lab", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {TOOL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TOOL = load_tool_module()


def make_analyser_series(days: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Return (unix seconds, positive smoothed random-walk values) at 1-min spacing."""
    rng = np.random.default_rng(0)
    total = days * SAMPLES_PER_DAY
    walk = np.cumsum(rng.normal(0.0, 0.05, total))
    kernel = np.ones(60) / 60.0
    smoothed = np.convolve(walk, kernel, mode="same")
    values = 10.0 + smoothed - smoothed.min()
    times_s = np.arange(total, dtype=float) * 60.0
    return times_s, values


def format_stamp(unix_seconds: float) -> str:
    """Format Unix seconds as a UTC wall-clock stamp in the parser's expected format."""
    from datetime import UTC, datetime  # noqa: PLC0415 - local helper, keeps import list short

    return datetime.fromtimestamp(unix_seconds, tz=UTC).strftime(STAMP_FORMAT)


def write_wide_csv(path: Path, times_s: np.ndarray, values: np.ndarray) -> None:
    """Write a wide CSV with a timestamp column and the analyser column."""
    stamps = [format_stamp(seconds) for seconds in times_s]
    np.savetxt(
        path,
        np.column_stack([values]),
        fmt="%.6f",
        delimiter=",",
        header=f"timestamp,{ANALYSER_TAG}",
        comments="",
    )
    lines = path.read_text().splitlines()
    rewritten = [lines[0]] + [
        f"{stamp},{line}" for stamp, line in zip(stamps, lines[1:], strict=True)
    ]
    path.write_text("\n".join(rewritten) + "\n")


def window_mean_at(times_s: np.ndarray, values: np.ndarray, stamp_s: float) -> float:
    """Mean of analyser samples over [stamp - 7 h, stamp - 1 h], matching the true recipe."""
    start_s = stamp_s + (TRUE_SHIFT_HOURS - WINDOW_HOURS) * 3600.0
    stop_s = stamp_s + TRUE_SHIFT_HOURS * 3600.0
    mask = (times_s >= start_s) & (times_s <= stop_s)
    return float(np.mean(values[mask]))


def build_lab_rows(times_s: np.ndarray, values: np.ndarray) -> list[tuple[float, float]]:
    """Lab stamps every 6 h on days 1..9; value = 2*window_mean(stamp) + 0.5."""
    rows: list[tuple[float, float]] = []
    for day in range(1, 10):
        for hour in range(0, 24, 6):
            stamp_s = day * SECONDS_PER_DAY + hour * 3600.0
            lab_value = SLOPE * window_mean_at(times_s, values, stamp_s) + OFFSET
            rows.append((stamp_s, lab_value))
    return rows


def write_lab_csv(path: Path, rows: list[tuple[float, float]]) -> None:
    """Write a long-format CSV with timestamp, tag, value, raw_value columns."""
    lines = ["timestamp,tag,value,raw_value"]
    for stamp_s, value in rows:
        lines.append(f"{format_stamp(stamp_s)},{LAB_TAG},{value:.6f},{value:.6f}")
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture()
def dataset(tmp_path: Path) -> dict[str, Path]:
    """Create the wide analyser CSV and the long lab CSV, returning their paths."""
    times_s, values = make_analyser_series()
    wide_path = tmp_path / "wide.csv"
    lab_path = tmp_path / "lab.csv"
    write_wide_csv(wide_path, times_s, values)
    write_lab_csv(lab_path, build_lab_rows(times_s, values))
    return {"wide": wide_path, "lab": lab_path, "times": times_s, "values": values}


def run_tool(wide_path: Path, lab_path: Path, extra: list[str] | None = None) -> int:
    """Invoke the CLI with the required options plus any extra flags."""
    argv = [
        "--wide", str(wide_path),
        "--analyser", ANALYSER_TAG,
        "--lab-csv", str(lab_path),
        "--lab-tag", LAB_TAG,
    ]
    return TOOL.main(argv + (extra or []))


def parse_summary(text: str) -> dict[str, float]:
    """Parse the 'best shift ...' summary line into named numeric fields."""
    match = re.search(r"^best shift .*$", text, flags=re.MULTILINE)
    if match is None:
        raise AssertionError(f"no summary line in output:\n{text}")
    line = match.group(0)
    fields: dict[str, float] = {}
    for key, pattern in {
        "shift": r"best shift\s+([+-]?\d+\.\d+)\s+h",
        "cv_r2": r"CV R2=(-?\d+\.\d+)",
        "slope": r"slope=(-?\d+\.\d+)",
    }.items():
        found = re.search(pattern, line)
        fields[key] = float(found.group(1)) if found else float("nan")
    return fields


def test_tool_analyzer_vs_lab_prints_one_line_per_shift(
    dataset: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The report contains one 'shift' line for each requested shift."""
    exit_code = run_tool(dataset["wide"], dataset["lab"])
    output = capsys.readouterr().out
    shift_lines = [line for line in output.splitlines() if line.startswith("shift ")]
    assert exit_code == 0
    assert len(shift_lines) == 13  # default --shifts-h -3,3,0.5 spans 13 values inclusive


def test_tool_analyzer_vs_lab_reports_best_shift_minus_one(
    dataset: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The true best shift is -1 h and the report states it."""
    run_tool(dataset["wide"], dataset["lab"])
    output = capsys.readouterr().out
    assert "best shift -1.0 h" in output


def test_tool_analyzer_vs_lab_cv_r2_exceeds_ninety_percent(
    dataset: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Blocked cross-validated R2 on the best shift is above 0.9."""
    run_tool(dataset["wide"], dataset["lab"])
    summary = parse_summary(capsys.readouterr().out)
    assert summary["cv_r2"] > 0.9


def test_tool_analyzer_vs_lab_recovers_slope_of_two(
    dataset: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The fitted slope matches the synthetic calibration slope of 2 within 0.1."""
    run_tool(dataset["wide"], dataset["lab"])
    summary = parse_summary(capsys.readouterr().out)
    assert abs(summary["slope"] - SLOPE) <= 0.1


def test_tool_analyzer_vs_lab_unknown_analyser_column_returns_two(
    dataset: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing analyser column is reported as an error and yields exit code 2."""
    argv = [
        "--wide", str(dataset["wide"]),
        "--analyser", "missing_tag",
        "--lab-csv", str(dataset["lab"]),
        "--lab-tag", LAB_TAG,
    ]
    exit_code = TOOL.main(argv)
    assert exit_code == 2
    assert "error:" in capsys.readouterr().err


def test_tool_analyzer_vs_lab_too_few_lab_rows_returns_two(
    dataset: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Fewer than 20 aligned lab rows triggers exit code 2 with an explanatory error."""
    sparse_lab = dataset["lab"].with_name("sparse_lab.csv")
    write_lab_csv(sparse_lab, [(2 * SECONDS_PER_DAY, 12.0)] * 3)
    exit_code = run_tool(dataset["wide"], sparse_lab)
    assert exit_code == 2
    assert "error:" in capsys.readouterr().err


def test_tool_analyzer_vs_lab_ignores_values_below_min_valid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sentinel blocks below --min-valid do not change the recovered best shift."""
    times_s, values = make_analyser_series()
    corrupted = values.copy()
    # Replace 5-minute blocks every 3 h with a sentinel; window means keep enough valid samples.
    block = 5
    for start in range(0, len(corrupted), 180):
        corrupted[start:start + block] = SENTINEL
    wide_path = tmp_path / "wide.csv"
    write_wide_csv(wide_path, times_s, corrupted)
    lab_path = tmp_path / "lab.csv"
    write_lab_csv(lab_path, build_lab_rows(times_s, values))

    exit_code = run_tool(wide_path, lab_path, ["--min-valid", "-100"])
    summary = parse_summary(capsys.readouterr().out)
    assert exit_code == 0
    assert summary["shift"] == -1.0


def test_tool_analyzer_vs_lab_min_rows_option_sets_the_row_limit(
    dataset: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """--min-rows raises the limit above the aligned rows (exit 2) or lowers it (exit 0)."""
    assert run_tool(dataset["wide"], dataset["lab"], ["--min-rows", "100000"]) == 2
    assert "need at least 100000" in capsys.readouterr().err
    assert run_tool(dataset["wide"], dataset["lab"], ["--min-rows", "5"]) == 0


def test_window_mean_uses_the_finite_fraction_argument() -> None:
    """A window with 60 % finite samples passes at 0.5 and gives NaN at 0.9."""
    t_s = np.arange(10, dtype=float)
    values = np.array([1.0] * 6 + [np.nan] * 4)
    series = TOOL.TagSeries(tag="x", t_s=t_s, values=values)
    assert TOOL.window_mean(series, 0.0, 9.0, 0.0, 0.5) == pytest.approx(1.0)
    assert np.isnan(TOOL.window_mean(series, 0.0, 9.0, 0.0, 0.9))
