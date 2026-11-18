"""Validate explicit site OUT bounds and schema documentation for manual tests.

No schema keyword may silently introduce a plant safety value.
"""

import json
from pathlib import Path

import pytest
from crosscut_gateway.policy import PolicyError, outputs_from_dict
from crosscut_gateway.policy_file import validate_document

SITE_TARGET = {
    "kind": "out_step", "loop": "FIC", "limits": [0, 100], "pv_limits": [10, 90],
    "max_amplitude": 1, "max_duration_s": 10, "readback_tolerance": 0.01,
}


def test_an_output_policy_is_a_distinct_validated_target_kind() -> None:
    """OUT policies are validated without becoming ordinary setpoint policies."""
    document = {"version": 1, "mode": "confirm", "targets": {"FIC.OUT": SITE_TARGET}}
    assert validate_document(document) == {}
    assert outputs_from_dict(document)["FIC.OUT"].max_amplitude == 1


@pytest.mark.parametrize("field", ["max_amplitude", "max_duration_s", "pv_limits"])
def test_missing_site_bounds_are_refused(field: str) -> None:
    """Omitted bounds must not acquire a permissive implicit value."""
    incomplete = {key: value for key, value in SITE_TARGET.items() if key != field}
    with pytest.raises(PolicyError, match="supply exactly"):
        outputs_from_dict({"FIC.OUT": incomplete})


@pytest.mark.parametrize("value", [True, float("nan"), 0, -1])
def test_nonpositive_or_nonfinite_amplitude_bounds_are_refused(value: object) -> None:
    """A configured amplitude cap must be a positive finite number."""
    with pytest.raises(PolicyError):
        outputs_from_dict({"FIC.OUT": {**SITE_TARGET, "max_amplitude": value}})


def test_output_schema_describes_bounds_without_a_default_keyword() -> None:
    """The schema documents conservative starting points while requiring site input."""
    path = Path(__file__).resolve().parents[2] / "schemas/write-policy.schema.json"
    schema_text = path.read_text(encoding="utf-8")
    target = json.loads(schema_text)["$defs"]["out_step_target"]
    assert '"default"' not in schema_text
    assert target["properties"]["max_duration_s"]["description"]
    assert "max_amplitude" in target["required"]
