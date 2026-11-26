"""Tests for history_table.py (issue #201)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from crosscut_connectors.base import CAP_HISTORY
from crosscut_connectors.history_table import BAD, history_table
from crosscut_connectors.registry import create_connector


def test_pi_layout() -> None:
    """Test the PI Web API layout: {tag: [{timestamp_utc, value, quality, reason}]}."""
    raw = {
        "tag1": [
            {"timestamp_utc": "2023-01-01T00:00:00Z", "value": 1.0, "quality": 0},
            {"timestamp_utc": "2023-01-01T00:00:01Z", "value": 2.0, "quality": 1},
        ],
        "tag2": [
            {"timestamp_utc": "2023-01-01T00:00:00Z", "value": 3.0, "quality": 2},
            {"timestamp_utc": "2023-01-01T00:00:02Z", "value": 4.0, "quality": 0},
        ],
    }
    table = history_table(raw, ["tag1", "tag2"])
    assert table.ts_ns.tolist() == [
        1672531200000000000, 1672531201000000000, 1672531202000000000
    ]
    assert table.tag_ids == ["tag1", "tag2"]
    assert np.allclose(table.values, [[1.0, 3.0], [2.0, math.nan], [math.nan, 4.0]], equal_nan=True)
    assert table.qualities.tolist() == [[0, 2], [1, BAD], [BAD, 0]]


def test_sql_profile_layout() -> None:
    """Test the SQL profile layout: {tag_ids, data: [{tag_id, timestamp_utc, value, quality}]}."""
    raw = {
        "tag_ids": ["tag1", "tag2"],
        "data": [
            {"tag_id": "tag1", "timestamp_utc": "2023-01-01T00:00:00Z", "value": 1.0, "quality": 0},
            {"tag_id": "tag2", "timestamp_utc": "2023-01-01T00:00:00Z", "value": 3.0, "quality": 2},
            {"tag_id": "tag1", "timestamp_utc": "2023-01-01T00:00:01Z", "value": 2.0, "quality": 1},
            {"tag_id": "tag2", "timestamp_utc": "2023-01-01T00:00:02Z", "value": 4.0, "quality": 0},
        ],
    }
    table = history_table(raw, ["tag1", "tag2"])
    assert table.ts_ns.tolist() == [
        1672531200000000000, 1672531201000000000, 1672531202000000000
    ]
    assert table.tag_ids == ["tag1", "tag2"]
    assert np.allclose(table.values, [[1.0, 3.0], [2.0, math.nan], [math.nan, 4.0]], equal_nan=True)
    assert table.qualities.tolist() == [[0, 2], [1, BAD], [BAD, 0]]


def test_sql_table_layout() -> None:
    """Test the SQL table layout: {tag_ids, data: [(ts, v0, v1, ...)]}."""
    raw = {
        "tag_ids": ["tag1", "tag2"],
        "data": [
            ("2023-01-01T00:00:00Z", 1.0, 3.0),
            ("2023-01-01T00:00:01Z", 2.0, None),
            ("2023-01-01T00:00:02Z", None, 4.0),
        ],
    }
    table = history_table(raw, ["tag1", "tag2"])
    assert table.ts_ns.tolist() == [
        1672531200000000000, 1672531201000000000, 1672531202000000000
    ]
    assert table.tag_ids == ["tag1", "tag2"]
    assert np.allclose(table.values, [[1.0, 3.0], [2.0, math.nan], [math.nan, 4.0]], equal_nan=True)
    assert table.qualities.tolist() == [[0, 0], [0, BAD], [BAD, 0]]


def test_csv_wide_layout() -> None:
    """Test the CSV wide layout: {tag_ids, data: [DictReader rows of strings]}."""
    raw = {
        "tag_ids": ["file.csv/tag1", "file.csv/tag2"],
        "data": [
            {"timestamp": "2023-01-01T00:00:00Z", "tag1": "1.0", "tag2": "3.0"},
            {"timestamp": "2023-01-01T00:00:01Z", "tag1": "2.0", "tag2": ""},
            {"timestamp": "2023-01-01T00:00:02Z", "tag1": "", "tag2": "4.0"},
        ],
    }
    table = history_table(raw, ["file.csv/tag1", "file.csv/tag2"])
    assert table.ts_ns.tolist() == [
        1672531200000000000, 1672531201000000000, 1672531202000000000
    ]
    assert table.tag_ids == ["file.csv/tag1", "file.csv/tag2"]
    assert np.allclose(table.values, [[1.0, 3.0], [2.0, math.nan], [math.nan, 4.0]], equal_nan=True)
    assert table.qualities.tolist() == [[0, 0], [0, BAD], [BAD, 0]]


def test_csv_long_layout() -> None:
    """Test the CSV long layout: {tag_ids, data: [DictReader rows of strings]}."""
    raw = {
        "tag_ids": ["file.csv/tag1", "file.csv/tag2"],
        "data": [
            {"timestamp": "2023-01-01T00:00:00Z", "tag": "tag1", "value": "1.0", "quality": "0"},
            {"timestamp": "2023-01-01T00:00:00Z", "tag": "tag2", "value": "3.0", "quality": "2"},
            {"timestamp": "2023-01-01T00:00:01Z", "tag": "tag1", "value": "2.0", "quality": "1"},
            {"timestamp": "2023-01-01T00:00:02Z", "tag": "tag2", "value": "4.0", "quality": "0"},
        ],
    }
    table = history_table(raw, ["file.csv/tag1", "file.csv/tag2"])
    assert table.ts_ns.tolist() == [
        1672531200000000000, 1672531201000000000, 1672531202000000000
    ]
    assert table.tag_ids == ["file.csv/tag1", "file.csv/tag2"]
    assert np.allclose(table.values, [[1.0, 3.0], [2.0, math.nan], [math.nan, 4.0]], equal_nan=True)
    assert table.qualities.tolist() == [[0, 2], [1, BAD], [BAD, 0]]


def test_unknown_layout() -> None:
    """Test that an unknown layout raises a ValueError."""
    raw = {"unknown": "layout"}
    with pytest.raises(ValueError, match="unrecognised history layout"):
        history_table(raw, ["tag1"])


def test_no_samples() -> None:
    """Test that no samples raises a ValueError."""
    raw = {"tag1": []}
    with pytest.raises(ValueError, match="no samples"):
        history_table(raw, ["tag1"])


def test_duplicate_tag_ids() -> None:
    """Test that duplicate tag ids in the request collapse."""
    raw = {
        "tag1": [
            {"timestamp_utc": "2023-01-01T00:00:00Z", "value": 1.0, "quality": 0},
        ],
    }
    table = history_table(raw, ["tag1", "tag1"])
    assert table.tag_ids == ["tag1"]


def test_timestamp_conversion() -> None:
    """Test timestamp conversion with Z, offset, and naive timestamps."""
    raw = {
        "tag1": [
            {"timestamp_utc": "2023-01-01T00:00:00Z", "value": 1.0, "quality": 0},
            {"timestamp_utc": "2023-01-01T00:00:01+00:00", "value": 2.0, "quality": 1},
            {"timestamp_utc": "2023-01-01T00:00:02", "value": 3.0, "quality": 2},
        ],
    }
    table = history_table(raw, ["tag1"])
    assert table.ts_ns.tolist() == [
        1672531200000000000, 1672531201000000000, 1672531202000000000
    ]


def test_microseconds_exact() -> None:
    """Test that microseconds are exact in the timestamp conversion."""
    raw = {
        "tag1": [
            {"timestamp_utc": "2023-01-01T00:00:00.123456Z", "value": 1.0, "quality": 0},
        ],
    }
    table = history_table(raw, ["tag1"])
    assert table.ts_ns.tolist() == [1672531200123456000]


def test_none_empty_values() -> None:
    """Test that None and empty values become NaN with quality 2."""
    raw = {
        "tag1": [
            {"timestamp_utc": "2023-01-01T00:00:00Z", "value": None, "quality": None},
            {"timestamp_utc": "2023-01-01T00:00:01Z", "value": "", "quality": ""},
        ],
    }
    table = history_table(raw, ["tag1"])
    assert np.allclose(table.values, [[math.nan], [math.nan]], equal_nan=True)
    assert table.qualities.tolist() == [[BAD], [BAD]]


def test_duplicate_timestamps() -> None:
    """Test that duplicate timestamps keep the last observation."""
    raw = {
        "tag1": [
            {"timestamp_utc": "2023-01-01T00:00:00Z", "value": 1.0, "quality": 0},
            {"timestamp_utc": "2023-01-01T00:00:00Z", "value": 2.0, "quality": 1},
        ],
    }
    table = history_table(raw, ["tag1"])
    assert np.allclose(table.values, [[2.0]], equal_nan=True)
    assert table.qualities.tolist() == [[1]]


def test_end_to_end_csv_connector(tmp_path: Path) -> None:
    """Test the end-to-end CSV connector with a tmp_path folder."""
    csv_path = tmp_path / "test.csv"
    csv_path.write_text(
        "timestamp,tag1,tag2\n"
        "2023-01-01T00:00:00Z,1.0,3.0\n"
        "2023-01-01T00:00:01Z,2.0,\n"
        "2023-01-01T00:00:02Z,,4.0\n"
    )
    connector = create_connector("csv", str(tmp_path))
    assert CAP_HISTORY in connector.capabilities()
    raw = connector.history(
        ["test.csv/tag1", "test.csv/tag2"], "2023-01-01T00:00:00Z", "2023-01-01T00:00:03Z"
    )
    table = history_table(raw, ["test.csv/tag1", "test.csv/tag2"])
    assert table.ts_ns.tolist() == [
        1672531200000000000, 1672531201000000000, 1672531202000000000
    ]
    assert table.tag_ids == ["test.csv/tag1", "test.csv/tag2"]
    assert np.allclose(table.values, [[1.0, 3.0], [2.0, math.nan], [math.nan, 4.0]], equal_nan=True)
    assert table.qualities.tolist() == [[0, 0], [0, BAD], [BAD, 0]]
