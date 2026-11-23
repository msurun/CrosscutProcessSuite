"""Contract tests for schemas/trend-chart.schema.json.

The schema describes one saved Trends chart file. Each test checks the schema
itself is a valid Draft 2020-12 document, accepts a complete example chart, and
rejects the invalid mutations of that example.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "trend-chart.schema.json"
)
DRAFT = "https://json-schema.org/draft/2020-12/schema"

CHART_DOC: dict[str, Any] = {
    "schema_version": 1,
    "id": "abcdef012345",
    "name": "HPGR pressing force and roll speed",
    "owner": "alice",
    "shared": True,
    "created_utc": "2026-10-10T12:00:00Z",
    "updated_utc": "2026-10-11T08:30:00Z",
    "series": [
        {"source": "mill1", "tag": "hpgr.press_sp", "label": "Press SP", "colour": "#1f77b4",
         "axis": "force", "style": "line"},
        {"source": "mill1", "tag": "hpgr.press_pv", "label": "Press PV", "colour": "#ff7f0e",
         "axis": "force", "style": "step"},
        {"source": "mill1", "tag": "hpgr.roll_speed", "label": "Roll speed",
         "colour": "#2ca02c", "axis": "speed", "style": "points"},
    ],
    "axes": [
        {"id": "force", "side": "left", "pane": 0, "unit": "N/mm2", "min": 0.0, "max": 6.0},
        {"id": "speed", "side": "right", "pane": 0, "unit": "rpm", "min": 0, "max": 50},
    ],
    "window": {"kind": "relative", "last_s": 3600, "live": True, "refresh_s": 10},
    "aggregation": "minmax",
}

ABSOLUTE_WINDOW_DOC: dict[str, Any] = {
    **CHART_DOC,
    "window": {
        "kind": "absolute",
        "start_utc": "2026-01-01T00:00:00Z",
        "end_utc": "2026-01-01T06:00:00Z",
    },
}


def load_schema() -> dict[str, Any]:
    """Read the trend chart schema file from disk."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def chart_validator() -> Draft202012Validator:
    """Return a validator for the trend chart schema, after checking the schema is valid."""
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def mutated(
    doc: dict[str, Any], path: list[str | int], value: Any
) -> dict[str, Any]:
    """Return a deep copy of doc with the value at path replaced, or deleted for "__delete__"."""
    out = copy.deepcopy(doc)
    node: Any = out
    for key in path[:-1]:
        node = node[key]
    if value == "__delete__":
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return out


def chart_errors(doc: dict[str, Any]) -> list[Any]:
    """Return the validation errors of one chart document against the schema."""
    return list(chart_validator().iter_errors(doc))


def test_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(load_schema())


def test_schema_metadata() -> None:
    schema = load_schema()
    assert schema["$schema"] == DRAFT
    assert schema["$id"].startswith("https://")
    assert schema["title"]
    assert schema["description"]


def test_relative_live_chart_validates() -> None:
    assert chart_errors(CHART_DOC) == []


def test_absolute_window_chart_validates() -> None:
    assert chart_errors(ABSOLUTE_WINDOW_DOC) == []


INVALID_CHARTS = [
    mutated(CHART_DOC, ["name"], "__delete__"),
    mutated(CHART_DOC, ["series"], "__delete__"),
    mutated(CHART_DOC, ["axes"], "__delete__"),
    mutated(CHART_DOC, ["window"], "__delete__"),
    mutated(CHART_DOC, ["owner"], "__delete__"),
    mutated(CHART_DOC, ["shared"], "__delete__"),
    mutated(CHART_DOC, ["unexpected"], 1),
    mutated(CHART_DOC, ["id"], "ABCDEF012345"),
    mutated(CHART_DOC, ["id"], "abcdef01234"),
    mutated(CHART_DOC, ["id"], "abcdef0123456"),
    mutated(CHART_DOC, ["series"], []),
    mutated(CHART_DOC, ["series"], CHART_DOC["series"] * 9),
    mutated(CHART_DOC, ["series", 0, "colour"], "#12345"),
    mutated(CHART_DOC, ["series", 0, "style"], "bar"),
    mutated(CHART_DOC, ["axes", 0, "side"], "top"),
    mutated(CHART_DOC, ["axes", 0, "pane"], 3),
    mutated(CHART_DOC, ["window", "last_s"], 59),
    mutated(CHART_DOC, ["window", "start_utc"], "2026-01-01T00:00:00Z"),
    mutated(ABSOLUTE_WINDOW_DOC, ["window", "end_utc"], "__delete__"),
    mutated(CHART_DOC, ["aggregation"], "median"),
    mutated(CHART_DOC, ["schema_version"], 2),
]


@pytest.mark.parametrize("doc", INVALID_CHARTS)
def test_chart_rejects_invalid(doc: dict[str, Any]) -> None:
    assert chart_errors(doc)
