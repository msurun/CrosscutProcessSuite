"""Contract tests for schemas/tuning-proposal.schema.json (ADR 014, section 1).

The record must accept a complete proposal in each lifecycle state and reject unknown
keys, missing fields and malformed values.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "tuning-proposal.schema.json"
UUID_A = "0b9f5a52-4c1e-4c63-9d5e-6f3a1e2b7c10"
UUID_B = "1c0a6b63-5d2f-4d74-8e6f-7a4b2f3c8d21"
SHA = "a" * 64

ITEM: dict[str, Any] = {
    "param": "gain", "target": "FIC101.KP", "unit": "1", "from": 1.0, "to": 1.4,
}

RECORD: dict[str, Any] = {
    "id": UUID_A,
    "version": 1,
    "loop_id": "FIC101",
    "created_by": "alice",
    "created_at": "2026-11-05T10:00:00Z",
    "expires_at": "2026-11-05T18:00:00Z",
    "vendor_form": {"key": "siemens_pid_compact", "evidence": "partly_verified"},
    "source": {
        "method": "simc",
        "robustness": 0.5,
        "model": {"K": 1.2, "tau_s": 40.0, "theta_s": 5.0, "process_kind": "self_regulating"},
        "window": {"dataset_id": "wood_berry_nominal", "start": "2026-11-05T00:00:00Z",
                   "end": "2026-11-05T06:00:00Z"},
        "report_digest": SHA,
    },
    "confidence": {"level": "medium", "reasons": ["vendor evidence partly verified"]},
    "caveats": ["check the Ti unit on the real block"],
    "items": [ITEM],
    "preview": {
        "label": "model prediction",
        "iae_ratio": 0.8,
        "overshoot_pct": {"current": 12.0, "proposed": 6.0},
        "settling_time_s": {"current": 300.0, "proposed": 220.0},
        "ms": {"current": 1.9, "proposed": 1.5},
    },
    "rollback_of": None,
    "status": "draft",
    "gateway_key": None,
    "applied": None,
    "review": None,
}


def _validator() -> Draft202012Validator:
    """Validator for the tuning-proposal schema, after checking the schema itself."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _with(**changes: Any) -> dict[str, Any]:
    """A copy of RECORD with top-level fields replaced."""
    doc = copy.deepcopy(RECORD)
    doc.update(changes)
    return doc


def test_draft_record_is_valid() -> None:
    """A freshly created record validates."""
    assert _validator().is_valid(RECORD)


def test_applied_and_reviewed_record_is_valid() -> None:
    """An applied record with a review and a rollback link validates."""
    doc = _with(
        status="reviewed:improved",
        gateway_key=SHA,
        rollback_of=UUID_B,
        applied={"from_read": {"FIC101.KP": 1.0}, "to_read": {"FIC101.KP": 1.4},
                 "t": "2026-11-05T11:00:00Z", "approver": "bob"},
        review={"verdict": "improved", "t": "2026-11-05T14:00:00Z",
                "metrics": {"error_std_ratio": 0.7, "iae_per_h_ratio": None}},
    )
    assert _validator().is_valid(doc)


@pytest.mark.parametrize(
    "status",
    ["draft", "queued", "applied", "rejected", "expired", "reviewing",
     "refused:from_mismatch", "reviewed:worse_early"],
)
def test_status_values_accepted(status: str) -> None:
    """Every lifecycle state of the ADR is accepted."""
    assert _validator().is_valid(_with(status=status))


@pytest.mark.parametrize("status", ["", "done", "refused:", "reviewed:Improved", "queued "])
def test_status_values_rejected(status: str) -> None:
    """Unknown states are rejected."""
    assert not _validator().is_valid(_with(status=status))


@pytest.mark.parametrize("field", list(RECORD))
def test_missing_top_level_field_rejected(field: str) -> None:
    """Every top-level field is required (nullable ones must be present as null)."""
    doc = copy.deepcopy(RECORD)
    del doc[field]
    assert not _validator().is_valid(doc)


def test_unknown_keys_rejected_at_every_level() -> None:
    """additionalProperties is false on the record and its nested objects."""
    v = _validator()
    assert not v.is_valid(_with(extra=1))
    for path in (("source",), ("source", "model"), ("source", "window"), ("confidence",),
                 ("vendor_form",), ("preview",), ("items", 0)):
        doc = copy.deepcopy(RECORD)
        node: Any = doc
        for key in path:
            node = node[key]
        node["extra"] = 1
        assert not v.is_valid(doc), path


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "not-a-uuid"}, {"id": UUID_A.upper()}, {"version": 2}, {"loop_id": "FIC 101"},
        {"loop_id": ""}, {"created_at": "2026-11-05 10:00:00"}, {"expires_at": "tomorrow"},
        {"items": []}, {"items": [{**ITEM, "param": "kc"}]}, {"items": [{**ITEM, "to": "1.4"}]},
        {"items": [{**ITEM, "to": None}]},
        {"items": [{k: v for k, v in ITEM.items() if k != "from"}]},
        {"rollback_of": "x"}, {"gateway_key": "abc"}, {"applied": {"t": "x"}},
        {"review": {"verdict": "great"}}, {"caveats": [""]},
        {"confidence": {"level": "certain", "reasons": []}},
        {"vendor_form": {"key": "x", "evidence": "trust_me"}},
        {"preview": {**RECORD["preview"], "label": "measured"}},
    ],
)
def test_malformed_values_rejected(changes: dict[str, Any]) -> None:
    """Malformed values fail validation."""
    assert not _validator().is_valid(_with(**changes))


@pytest.mark.parametrize("method", ["simc", "amigo", "amigo_pid", "rollback", "manual"])
def test_source_methods_accepted(method: str) -> None:
    """All five methods of the ADR are accepted; others are not."""
    doc = copy.deepcopy(RECORD)
    doc["source"]["method"] = method
    assert _validator().is_valid(doc)
    doc["source"]["method"] = "ziegler"
    assert not _validator().is_valid(doc)


def test_window_needs_dataset_or_history_not_both() -> None:
    """The window names a dataset or the history store, exactly one."""
    v = _validator()
    doc = copy.deepcopy(RECORD)
    win = doc["source"]["window"]
    doc["source"]["window"] = {"history": True, "start": win["start"], "end": win["end"]}
    assert v.is_valid(doc)
    doc["source"]["window"]["dataset_id"] = "d"
    assert not v.is_valid(doc)
    doc["source"]["window"] = {"start": win["start"], "end": win["end"]}
    assert not v.is_valid(doc)


def test_optional_step_test_id_and_four_items() -> None:
    """step_test_id is optional; up to four items (gain, ti, td, tf) are allowed."""
    doc = copy.deepcopy(RECORD)
    doc["source"]["step_test_id"] = "step_001"
    params = ("gain", "ti", "td", "tf")
    doc["items"] = [{**ITEM, "param": p, "target": f"FIC101.{p}"} for p in params]
    assert _validator().is_valid(doc)
    doc["items"].append(ITEM)
    assert not _validator().is_valid(doc)
