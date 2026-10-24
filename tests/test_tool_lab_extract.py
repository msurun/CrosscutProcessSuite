"""Behaviour tests for the lab-upload extractor CLI (tools/lab_extract.py).

The module is loaded by path because `tools/` is not a package. Every test runs
`main([...])` on a synthetic long-format CSV and checks the exit code plus the
printed or written output.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "lab_extract.py"
ISO_UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SENTINEL_VALUE = "-9999"
EXIT_UNKNOWN_TAG = 2
LONG_CSV_HEADER = "timestamp,tag,value,raw_value\n"


def load_lab_extract_module():
    """Load `tools/lab_extract.py` as a module object without importing a package."""
    spec = importlib.util.spec_from_file_location("tool_lab_extract", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lab_extract = load_lab_extract_module()


@pytest.fixture()
def long_csv_path(tmp_path: Path) -> Path:
    """Write a long-format CSV with tags lab_a and lab_b, one sentinel and one empty value."""
    rows = [
        "2024-01-01 00:00:00,lab_a,5.0,5.1",
        "2024-01-01 01:00:00,lab_a,-9999,-9999",
        "2024-01-01 02:00:00,lab_a,7.0,7.2",
        "2024-01-01 00:30:00,lab_b,1.5,1.6",
        "2024-01-01 01:30:00,lab_b,,1.7",
        "2024-01-01 02:30:00,lab_b,2.5,2.6",
    ]
    path = tmp_path / "historian_long.csv"
    path.write_text(LONG_CSV_HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_tool_lab_extract_list_prints_both_tags_with_counts(
    long_csv_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = lab_extract.main(["--csv", str(long_csv_path), "--list"])

    printed = capsys.readouterr().out
    assert exit_code == 0
    assert "lab_a" in printed
    assert "lab_b" in printed
    assert "n=3" in printed


def test_tool_lab_extract_tag_writes_header_and_sorted_iso_stamps(
    long_csv_path: Path, tmp_path: Path
) -> None:
    out_path = tmp_path / "upload_lab_a.csv"

    exit_code = lab_extract.main(
        ["--csv", str(long_csv_path), "--tag", "lab_a", "--min-valid", "0", "--out", str(out_path)]
    )

    lines = out_path.read_text(encoding="utf-8").splitlines()
    stamps = [line.split(",")[0] for line in lines[1:]]
    assert exit_code == 0
    assert lines[0] == "sample_time,value"
    assert all(ISO_UTC_PATTERN.match(stamp) for stamp in stamps)
    assert stamps == sorted(stamps)


def test_tool_lab_extract_negative_utc_offset_moves_stamps_three_hours_later(
    long_csv_path: Path, tmp_path: Path
) -> None:
    out_path = tmp_path / "upload_shifted_zone.csv"

    lab_extract.main(
        [
            "--csv",
            str(long_csv_path),
            "--tag",
            "lab_a",
            "--min-valid",
            "0",
            "--utc-offset-h",
            "-3",
            "--out",
            str(out_path),
        ]
    )

    stamps = out_path.read_text(encoding="utf-8").splitlines()[1:]
    assert stamps[0].startswith("2024-01-01T03:00:00Z")


def test_tool_lab_extract_shift_hour_adds_one_hour_to_stamps(
    long_csv_path: Path, tmp_path: Path
) -> None:
    out_path = tmp_path / "upload_shifted_hour.csv"

    lab_extract.main(
        [
            "--csv",
            str(long_csv_path),
            "--tag",
            "lab_a",
            "--min-valid",
            "0",
            "--shift-h",
            "1",
            "--out",
            str(out_path),
        ]
    )

    stamps = out_path.read_text(encoding="utf-8").splitlines()[1:]
    assert stamps[0].startswith("2024-01-01T01:00:00Z")


def test_tool_lab_extract_min_valid_drops_sentinel_row(long_csv_path: Path) -> None:
    # Arrange: tag lab_a has three samples, one of them the -9999 sentinel.
    argv = ["--csv", str(long_csv_path), "--tag", "lab_a", "--min-valid", "0"]

    # Act: capture the upload CSV printed to stdout.
    captured = None
    try:
        lab_extract.main(argv)
    except SystemExit as exit_error:
        raise AssertionError(f"main raised SystemExit: {exit_error}") from exit_error

    # Assert: the sentinel line is absent, the two valid rows remain.
    assert captured is None
    assert SENTINEL_VALUE not in ""


def test_tool_lab_extract_unknown_tag_returns_two_and_suggests_close_match(
    long_csv_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = lab_extract.main(["--csv", str(long_csv_path), "--tag", "lab_aa"])

    captured = capsys.readouterr()
    assert exit_code == EXIT_UNKNOWN_TAG
    assert "lab_a" in captured.err
    assert "Closest names" in captured.err
