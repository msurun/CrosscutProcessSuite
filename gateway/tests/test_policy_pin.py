"""Tests for policy pin creation, verification, and loading integration."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from auth_helpers import write_key_file
from crosscut_gateway import engine, keyfile, policy, policy_file, policy_pin
from test_gateway_scenarios import POLICY, TAG, SimPlant

KEY = b"a" * 32
SHORT_KEY = b"a" * 31
SIGNERS = policy_pin.PinSigners(author="alice", approver="bob")
NOW = datetime.now(UTC)


def _write_policy(path: Path, mode: str = "supervised") -> None:
    """Write a minimal policy file with the given file-level mode."""
    doc = {
        "version": 1,
        "mode": mode,
        "targets": {TAG: POLICY.__dict__},
    }
    path.write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def policy_path(tmp_path: Path) -> Path:
    """Path to a temporary policy file."""
    path = tmp_path / "policy.json"
    _write_policy(path)
    return path


def test_create_and_verify_pin_success(policy_path: Path) -> None:
    """Verifies pin creation and successful verification of the file."""
    pin_doc = policy_pin.create_pin(policy_path, KEY, SIGNERS, NOW)
    assert set(pin_doc) == {"digest", "author", "approver", "approved_at", "sig"}
    assert pin_doc["digest"] == policy_pin.file_digest(policy_path)

    targets, mode, digest = policy_pin.load_pinned_policy(policy_path, KEY)
    assert targets[TAG].limits == POLICY.limits
    assert mode == "supervised"
    assert digest == pin_doc["digest"]


@pytest.mark.parametrize("field", ["digest", "author", "approver", "approved_at", "sig"])
def test_pin_tamper_raises_error(policy_path: Path, field: str) -> None:
    """Tampering with any field in the pin file causes verification failure."""
    policy_pin.create_pin(policy_path, KEY, SIGNERS, NOW)
    pin_path = policy_pin.pin_path_for(policy_path)
    doc = json.loads(pin_path.read_text())
    doc[field] = "tampered"
    pin_path.write_text(json.dumps(doc))

    with pytest.raises(policy_pin.PinError, match="bad_signature|digest_mismatch"):
        policy_pin.verify_pin(policy_path, KEY)


def test_pin_invalid_structure(policy_path: Path) -> None:
    """Malformed pin structure (missing keys, extra keys) raises PinError."""
    policy_pin.create_pin(policy_path, KEY, SIGNERS, NOW)
    pin_path = policy_pin.pin_path_for(policy_path)

    bad_docs = [
        {"digest": "a"},  # missing keys
        {"digest": "a", "author": "a", "approver": "a", "approved_at": "a", "sig": "a", "x": "y"},
        {"digest": 1, "author": "a", "approver": "a", "approved_at": "a", "sig": "a"},
    ]
    for doc in bad_docs:
        pin_path.write_text(json.dumps(doc))
        with pytest.raises(policy_pin.PinError, match="pin_malformed"):
            policy_pin.verify_pin(policy_path, KEY)


def test_wrong_key_fails(policy_path: Path) -> None:
    """Using the wrong key for signature verification fails."""
    policy_pin.create_pin(policy_path, KEY, SIGNERS, NOW)
    with pytest.raises(policy_pin.PinError, match="bad_signature"):
        policy_pin.verify_pin(policy_path, b"b" * 32)


def test_short_key_rejected(policy_path: Path) -> None:
    """Keys shorter than 32 bytes are rejected immediately."""
    with pytest.raises(policy_pin.PinError, match="key_too_short"):
        policy_pin.create_pin(policy_path, SHORT_KEY, SIGNERS, NOW)


def test_policy_change_mismatch(policy_path: Path) -> None:
    """Changing policy content after pinning raises digest_mismatch."""
    policy_pin.create_pin(policy_path, KEY, SIGNERS, NOW)
    policy_path.write_text("tampered")
    with pytest.raises(policy_pin.PinError, match="digest_mismatch"):
        policy_pin.verify_pin(policy_path, KEY)


def test_self_approval_fails(policy_path: Path) -> None:
    """Author cannot be the approver."""
    with pytest.raises(policy_pin.PinError, match="author_equals_approver"):
        policy_pin.create_pin(policy_path, KEY, policy_pin.PinSigners("a", "a"), NOW)


def test_start_from_policy_file_modes(policy_path: Path) -> None:
    """Gateway runs at the more restrictive of requested and file mode."""
    _write_policy(policy_path, mode="dry_run")
    policy_pin.create_pin(policy_path, KEY, SIGNERS, NOW)
    gw = engine.start_from_policy_file(policy_path, SimPlant(), "supervised", key=KEY)
    assert gw.mode_cap == "dry_run"
    with pytest.raises(ValueError, match="exceeds policy cap"):
        gw.set_mode("confirm")


def test_start_below_the_policy_mode_keeps_the_policy_cap(policy_path: Path) -> None:
    """Starting in advisory under a confirm policy can still be raised to confirm, not beyond."""
    _write_policy(policy_path, mode="confirm")
    policy_pin.create_pin(policy_path, KEY, SIGNERS, NOW)
    gw = engine.start_from_policy_file(policy_path, SimPlant(), "advisory", key=KEY)
    assert gw.mode == "advisory"
    assert gw.mode_cap == "confirm"
    gw.set_mode("confirm")
    with pytest.raises(ValueError, match="exceeds policy cap"):
        gw.set_mode("supervised")


def test_validate_document_schema(policy_path: Path) -> None:
    """Validates schema correctly."""
    doc = json.loads(policy_path.read_text())
    assert policy_file.validate_document(doc)
    with pytest.raises(policy.PolicyError, match="schema validation failed"):
        policy_file.validate_document({"invalid": "doc"})


def test_keyfile_logic(tmp_path: Path, monkeypatch: Any) -> None:
    """Tests key reading and location overrides."""
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    monkeypatch.setenv(keyfile.SECRETS_ENV, str(secrets))
    key_path = keyfile.default_key_path(tmp_path)
    assert key_path == secrets / "gateway-hmac.key"
    assert keyfile.read_key(key_path) is None
    key_path.write_bytes(b"too short")
    assert keyfile.read_key(key_path) is None
    write_key_file(key_path, KEY)
    assert keyfile.read_key(key_path) == KEY
