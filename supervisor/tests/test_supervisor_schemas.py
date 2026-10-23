"""Tests for the advisory supervisor JSON schemas (ADR 010).

Validates schemas/supervisor.schema.json and schemas/advisory-record.schema.json
with a Draft 2020-12 validator: good examples pass, malformed ones are rejected.
"""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
HEX_A = "a" * 64
HEX_B = "b" * 64


def _validator(name):
    """Load a schema file, check it and return its validator."""
    schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture(scope="module")
def config_validator():
    """Validator for the supervisor configuration schema."""
    return _validator("supervisor.schema.json")


@pytest.fixture(scope="module")
def record_validator():
    """Validator for the advisory log record schema."""
    return _validator("advisory-record.schema.json")


def _config(**changes):
    """Return a valid supervisor config with the given keys overridden."""
    base = {
        "schema_version": "1.0.0",
        "id": "sup-1",
        "fuzzy_system_id": "fs1",
        "output_id": "delta_sp",
        "target_loop": "LIC101",
        "mode": "advisory",
        "gates": [{"loop": "LIC101", "block_on": ["manual", "saturated"],
                   "warn_on": ["oscillating"]}],
        "silent_band": 0.5,
        "min_activation": 0.2,
        "min_interval_s": 30,
        "display_clamp": [-5, 5],
    }
    base.update(changes)
    return base


def _advice(**changes):
    """Return a valid advice record with the given keys overridden."""
    base = {
        "kind": "advice",
        "advice_id": HEX_A,
        "t_ns": 1,
        "target_loop": "LIC101",
        "direction": "increase",
        "magnitude": 1.5,
        "activation": 0.7,
        "explanation": [{"rule_id": "r1", "sentence": "error is high",
                         "strength": 0.7}],
        "inputs": {"pv": 1.0},
        "gate": {"state": "open", "reasons": []},
        "rulebase_sha256": HEX_B,
        "prev_sha256": HEX_B,
    }
    base.update(changes)
    return base


def _ack(**changes):
    """Return a valid acknowledgement record with keys overridden."""
    base = {
        "kind": "ack",
        "advice_id": HEX_A,
        "decision": "accepted",
        "reason_code": "ok",
        "who": "operator1",
        "t_ns": 2,
        "prev_sha256": HEX_B,
    }
    base.update(changes)
    return base


def test_full_config_is_valid(config_validator):
    """A complete supervisor config validates."""
    assert config_validator.is_valid(_config(description="x", fuzzy_version_id="v1"))


def test_closed_loop_mode_rejected(config_validator):
    """Mode closed_loop is not allowed."""
    assert not config_validator.is_valid(_config(mode="closed_loop"))


def test_off_mode_ok(config_validator):
    """Mode off is allowed."""
    assert config_validator.is_valid(_config(mode="off"))


def test_missing_required_key_rejected(config_validator):
    """A config without a required key is rejected."""
    cfg = _config()
    del cfg["target_loop"]
    assert not config_validator.is_valid(cfg)


def test_unknown_key_rejected(config_validator):
    """An unknown top-level key is rejected."""
    assert not config_validator.is_valid(_config(write_path="x"))


def test_min_activation_above_one_rejected(config_validator):
    """min_activation 1.5 is out of range."""
    assert not config_validator.is_valid(_config(min_activation=1.5))


def test_display_clamp_three_items_rejected(config_validator):
    """display_clamp must have exactly two items."""
    assert not config_validator.is_valid(_config(display_clamp=[-1, 0, 1]))


def test_warn_on_manual_rejected(config_validator):
    """warn_on only accepts oscillating."""
    gates = [{"loop": "LIC101", "warn_on": ["manual"]}]
    assert not config_validator.is_valid(_config(gates=gates))


def test_valid_advice(record_validator):
    """A complete advice record validates."""
    assert record_validator.is_valid(_advice())


def test_advice_null_magnitude_blocked(record_validator):
    """Null magnitude with a blocked gate validates."""
    gate = {"state": "blocked", "reasons": ["manual"]}
    assert record_validator.is_valid(_advice(magnitude=None, gate=gate))


def test_advice_sideways_rejected(record_validator):
    """Direction sideways is rejected."""
    assert not record_validator.is_valid(_advice(direction="sideways"))


def test_valid_ack(record_validator):
    """A complete acknowledgement validates."""
    assert record_validator.is_valid(_ack())


def test_ack_without_advice_id_rejected(record_validator):
    """An ack must reference an advice."""
    ack = copy.deepcopy(_ack())
    del ack["advice_id"]
    assert not record_validator.is_valid(ack)


def test_ack_decision_maybe_rejected(record_validator):
    """Decision maybe is rejected."""
    assert not record_validator.is_valid(_ack(decision="maybe"))


def test_ack_empty_who_rejected(record_validator):
    """An ack with an empty who is rejected."""
    assert not record_validator.is_valid(_ack(who=""))


def test_first_record_empty_prev_valid(record_validator):
    """The first record of a chain has an empty prev_sha256."""
    assert record_validator.is_valid(_advice(prev_sha256=""))
