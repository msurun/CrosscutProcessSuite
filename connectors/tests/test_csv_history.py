"""Check CSV query bounds and last-observation sampling for both layouts.

Small source files expose timestamp offsets, ordering, and per-tag quality so
history filtering cannot silently manufacture or duplicate observations.
"""

from pathlib import Path

import pytest
from crosscut_connectors.csv_connector import CsvConnector

START_UTC = "2026-01-01T00:00:00Z"
END_UTC = "2026-01-01T00:00:04Z"
WIDE_TEXT = (
    "timestamp,A,B\n"
    "2026-01-01T00:00:03Z,30,300\n"
    "2026-01-01T01:00:00+01:00,0,100\n"
    "2026-01-01T00:00:01,10,110\n"
    "2026-01-01T00:00:02Z,20,200\n"
    "2026-01-01T00:00:04Z,40,400\n"
)
LONG_TEXT = (
    "timestamp,tag,value,quality\n"
    "2026-01-01T00:00:03Z,A,30,2\n"
    "2026-01-01T01:00:00+01:00,A,0,0\n"
    "2026-01-01T00:00:01,A,10,1\n"
    "2026-01-01T00:00:02Z,A,20,0\n"
    "2026-01-01T00:00:04Z,A,40,0\n"
    "2026-01-01T00:00:00Z,B,100,0\n"
    "2026-01-01T00:00:02Z,B,200,1\n"
)


def _connector(tmp_path: Path, layout: str) -> CsvConnector:
    """Write one layout and return its folder connector."""
    text = LONG_TEXT if layout == "long" else WIDE_TEXT
    (tmp_path / "history.csv").write_text(text, encoding="utf-8")
    return CsvConnector(str(tmp_path), {"layout": layout})


@pytest.mark.parametrize("layout", ["wide", "long"])
def test_bounds_include_start_and_exclude_end_in_utc(tmp_path: Path, layout: str) -> None:
    """Offset and naive timestamps refer to UTC instants before filtering."""
    connector = _connector(tmp_path, layout)
    history = connector.history(["history.csv/A"], START_UTC, "2026-01-01T00:00:02Z")
    value_column = "value" if layout == "long" else "A"

    assert [row[value_column] for row in history["data"]] == ["0", "10"]


@pytest.mark.parametrize("layout", ["wide", "long"])
def test_a_period_keeps_the_last_observation_in_each_bucket(tmp_path: Path, layout: str) -> None:
    """Two-second periods use the latest observation, retaining its source timestamp."""
    connector = _connector(tmp_path, layout)
    history = connector.history(["history.csv/A"], START_UTC, END_UTC, period_s=2)
    value_column = "value" if layout == "long" else "A"

    assert [row[value_column] for row in history["data"]] == ["10", "30"]
    assert history["data"][1]["timestamp"] == "2026-01-01T00:00:03Z"


def test_long_sampling_keeps_each_tags_quality_and_last_value(tmp_path: Path) -> None:
    """An observation for A never replaces the observation for B in the same bucket."""
    connector = _connector(tmp_path, "long")
    history = connector.history(["history.csv/A", "history.csv/B"], START_UTC, END_UTC, 2)

    assert [(row["tag"], row["value"], row["quality"]) for row in history["data"]] == [
        ("B", "100", "0"), ("A", "10", "1"), ("B", "200", "1"), ("A", "30", "2"),
    ]


def test_requesting_two_wide_tags_reads_each_file_once(tmp_path: Path) -> None:
    """A wide observation contains both selected values without duplicate rows."""
    connector = _connector(tmp_path, "wide")
    history = connector.history(["history.csv/A", "history.csv/B"], START_UTC, END_UTC)

    assert len(history["data"]) == 4
    assert history["data"][0]["A"] == "0"
    assert history["data"][0]["B"] == "100"


@pytest.mark.parametrize("layout", ["wide", "long"])
def test_sampling_periods_start_at_the_requested_bound(tmp_path: Path, layout: str) -> None:
    """A shifted bound changes the bucket origin rather than rounding to the wall clock."""
    connector = _connector(tmp_path, layout)
    history = connector.history(["history.csv/A"], "2026-01-01T00:00:01Z", END_UTC, 2)
    value_column = "value" if layout == "long" else "A"

    assert [row[value_column] for row in history["data"]] == ["20", "30"]


@pytest.mark.parametrize("layout", ["wide", "long"])
def test_an_empty_time_window_returns_no_rows(tmp_path: Path, layout: str) -> None:
    """Equal inclusive and exclusive bounds describe an empty range."""
    connector = _connector(tmp_path, layout)

    assert connector.history(["history.csv/A"], START_UTC, START_UTC)["data"] == []


@pytest.mark.parametrize("period_s", [0, -1, float("nan"), float("inf")])
def test_an_invalid_sampling_period_is_rejected(tmp_path: Path, period_s: float) -> None:
    """Periods must be finite and positive to define bounded buckets."""
    connector = _connector(tmp_path, "wide")

    with pytest.raises(ValueError, match="period_s"):
        connector.history(["history.csv/A"], START_UTC, END_UTC, period_s)


def test_reversed_time_bounds_are_rejected(tmp_path: Path) -> None:
    """A reversed query fails with a helpful bounds error."""
    connector = _connector(tmp_path, "wide")

    with pytest.raises(ValueError, match="end_utc"):
        connector.history(["history.csv/A"], END_UTC, START_UTC)


@pytest.mark.parametrize("layout", ["wide", "long"])
def test_sampling_does_not_fill_periods_without_observations(tmp_path: Path, layout: str) -> None:
    """A quarter-second period retains only observed rows, leaving gaps empty."""
    connector = _connector(tmp_path, layout)
    history = connector.history(["history.csv/A"], START_UTC, END_UTC, 0.25)
    value_column = "value" if layout == "long" else "A"

    assert [row[value_column] for row in history["data"]] == ["0", "10", "20", "30"]
