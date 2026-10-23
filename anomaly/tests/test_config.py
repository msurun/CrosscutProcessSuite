"""Tests for the anomaly configuration loader and its JSON schema (jsonschema in tests only)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from crosscut_anomaly.config import AnomalyConfigError, load_config

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "schemas" / "anomaly.schema.json").read_text("utf-8")
)
GOOD: dict[str, Any] = {
    "schema_version": "1.0.0", "id": "mill-pca", "tags": ["a", "b", "c"], "mode": "advisory",
}


def doc(**changes: Any) -> dict[str, Any]:
    """A valid document with ``changes`` applied (None removes a key)."""
    out = copy.deepcopy(GOOD)
    for key, value in changes.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def test_defaults() -> None:
    cfg = load_config(GOOD)
    assert (cfg.variance_fraction, cfg.alpha) == (0.90, 0.99)
    assert (cfg.min_consecutive, cfg.close_after, cfg.sample_period_s) == (5, 10, 60.0)
    assert cfg.tags == ("a", "b", "c") and cfg.description == ""
    jsonschema.validate(GOOD, SCHEMA)


def test_full_document_roundtrip() -> None:
    full = doc(description="x", variance_fraction=0.8, alpha=0.999, min_consecutive=3,
               close_after=4, sample_period_s=10)
    cfg = load_config(full)
    assert (cfg.alpha, cfg.min_consecutive, cfg.sample_period_s) == (0.999, 3, 10.0)
    jsonschema.validate(full, SCHEMA)


BAD = [
    (doc(schema_version=None), "schema_version"),
    (doc(id=None), "id"),
    (doc(tags=None), "tags"),
    (doc(mode=None), "mode"),
    (doc(extra=1), "extra"),
    (doc(schema_version="1.0"), "schema_version"),
    (doc(id="bad id"), "id"),
    (doc(description=3), "description"),
    (doc(tags="abc"), "tags"),
    (doc(tags=["a", "b"]), "tags"),
    (doc(tags=["a", "b", "b"]), "tags"),
    (doc(tags=["a", "b", ""]), "tags"),
    (doc(tags=["a", "b", 3]), "tags"),
    (doc(mode="closed_loop"), "mode"),
    (doc(mode="Advisory"), "mode"),
    (doc(variance_fraction=0.4), "variance_fraction"),
    (doc(variance_fraction=1.0), "variance_fraction"),
    (doc(variance_fraction="0.9"), "variance_fraction"),
    (doc(alpha=0.89), "alpha"),
    (doc(alpha=0.99999), "alpha"),
    (doc(alpha=True), "alpha"),
    (doc(min_consecutive=0), "min_consecutive"),
    (doc(min_consecutive=2.5), "min_consecutive"),
    (doc(min_consecutive=True), "min_consecutive"),
    (doc(close_after=0), "close_after"),
    (doc(close_after="3"), "close_after"),
    (doc(sample_period_s=0), "sample_period_s"),
    (doc(sample_period_s=-1), "sample_period_s"),
    (doc(sample_period_s="60"), "sample_period_s"),
]


@pytest.mark.parametrize(("bad", "field"), BAD)
def test_invalid_rejected_by_loader_and_schema(bad: dict[str, Any], field: str) -> None:
    with pytest.raises(AnomalyConfigError) as err:
        load_config(bad)
    assert str(err.value).startswith(field)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)


def test_closed_loop_mode_rejected_everywhere() -> None:
    with pytest.raises(AnomalyConfigError, match="^mode"):
        load_config(doc(mode="closed_loop"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc(mode="closed_loop"), SCHEMA)
    assert SCHEMA["properties"]["mode"]["enum"] == ["off", "advisory"]
