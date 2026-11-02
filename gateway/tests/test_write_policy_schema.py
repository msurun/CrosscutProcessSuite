"""Contract tests for write-policy.schema.json (Phase 2, #46).

Validates schema constraints on write gateway policies, including modes,
limits, step and rate clamps, hold-off, watchdog, and allowed loop modes.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "write-policy.schema.json"

VALID_TARGET_POLICY: dict[str, Any] = {
    "limits": [0.0, 100.0],
    "max_step": 10.0,
    "max_rate_per_s": 5.0,
    "min_interval_s": 1.0,
    "allowed_loop_modes": ["CAS", "AUTO"],
    "hold_off_s": 60.0,
    "watchdog_s": 5.0,
    "readback_tolerance": 0.5,
}

VALID_POLICY_DOC: dict[str, Any] = {
    "version": 1,
    "mode": "supervised",
    "targets": {
        "LIC_101.SP": VALID_TARGET_POLICY,
    },
}


def _validator() -> Draft202012Validator:
    """Return a draft 2020-12 validator instance for write-policy schema."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_valid_policy_document_passes() -> None:
    """A well-formed write policy document must be valid against the schema."""
    validator = _validator()
    assert validator.is_valid(VALID_POLICY_DOC)


def test_empty_targets_passes() -> None:
    """A policy with an empty targets mapping is valid (refuses all writes)."""
    doc = {"version": 1, "mode": "advisory", "targets": {}}
    assert _validator().is_valid(doc)


@pytest.mark.parametrize("missing_field", ["version", "mode", "targets"])
def test_missing_root_required_fields_fail(missing_field: str) -> None:
    """Omitting any root-level required field must fail validation."""
    doc = copy.deepcopy(VALID_POLICY_DOC)
    del doc[missing_field]
    assert not _validator().is_valid(doc)


@pytest.mark.parametrize(
    "missing_target_field",
    [
        "limits",
        "max_step",
        "max_rate_per_s",
        "min_interval_s",
        "allowed_loop_modes",
        "hold_off_s",
        "watchdog_s",
        "readback_tolerance",
    ],
)
def test_missing_target_required_fields_fail(missing_target_field: str) -> None:
    """Omitting any target-level field must fail validation."""
    doc = copy.deepcopy(VALID_POLICY_DOC)
    del doc["targets"]["LIC_101.SP"][missing_target_field]
    assert not _validator().is_valid(doc)


def test_unknown_root_field_fails() -> None:
    """Extra unexpected properties at the root must be rejected."""
    doc = copy.deepcopy(VALID_POLICY_DOC)
    doc["extra_root_field"] = "unexpected"
    assert not _validator().is_valid(doc)


def test_unknown_target_field_fails() -> None:
    """Extra unexpected properties inside a target policy must be rejected."""
    doc = copy.deepcopy(VALID_POLICY_DOC)
    doc["targets"]["LIC_101.SP"]["extra_target_field"] = 42
    assert not _validator().is_valid(doc)


@pytest.mark.parametrize("invalid_mode", ["manual", "open_loop", "INVALID", "", "super"])
def test_mode_outside_enum_fails(invalid_mode: str) -> None:
    """Modes not in (off, advisory, dry_run, confirm, supervised) must fail."""
    doc = copy.deepcopy(VALID_POLICY_DOC)
    doc["mode"] = invalid_mode
    assert not _validator().is_valid(doc)


def test_max_step_zero_fails() -> None:
    """max_step must be strictly positive (exclusiveMinimum > 0)."""
    doc = copy.deepcopy(VALID_POLICY_DOC)
    doc["targets"]["LIC_101.SP"]["max_step"] = 0
    assert not _validator().is_valid(doc)


def test_max_rate_zero_fails() -> None:
    """max_rate_per_s must be strictly positive (exclusiveMinimum > 0)."""
    doc = copy.deepcopy(VALID_POLICY_DOC)
    doc["targets"]["LIC_101.SP"]["max_rate_per_s"] = 0
    assert not _validator().is_valid(doc)


def test_allowed_loop_modes_empty_fails() -> None:
    """allowed_loop_modes must contain at least one mode string."""
    doc = copy.deepcopy(VALID_POLICY_DOC)
    doc["targets"]["LIC_101.SP"]["allowed_loop_modes"] = []
    assert not _validator().is_valid(doc)


def test_limits_must_have_exactly_two_items() -> None:
    """limits array must contain exactly [lo, hi]."""
    doc1 = copy.deepcopy(VALID_POLICY_DOC)
    doc1["targets"]["LIC_101.SP"]["limits"] = [0.0]
    assert not _validator().is_valid(doc1)

    doc2 = copy.deepcopy(VALID_POLICY_DOC)
    doc2["targets"]["LIC_101.SP"]["limits"] = [0.0, 50.0, 100.0]
    assert not _validator().is_valid(doc2)


def test_invalid_target_tag_identifier_fails() -> None:
    """Target tags must conform to valid identifier syntax."""
    doc = copy.deepcopy(VALID_POLICY_DOC)
    doc["targets"]["bad tag with spaces"] = copy.deepcopy(VALID_TARGET_POLICY)
    assert not _validator().is_valid(doc)

