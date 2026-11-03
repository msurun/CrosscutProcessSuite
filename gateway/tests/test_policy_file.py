"""Unit tests for write policy file loading, hashing, and tampering detection (Phase 2, #46).

Verifies canonical JSON serialization, SHA-256 digest determinism, schema validation,
tamper detection, and failure modes when loading policy files from disk.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from crosscut_gateway.policy import PolicyError
from crosscut_gateway.policy_file import (
    canonical_bytes,
    load_policy_file,
    policy_digest,
)

VALID_POLICY_DICT = {
    "version": 1,
    "mode": "supervised",
    "targets": {
        "FIC101.SP": {
            "limits": [0.0, 100.0],
            "max_step": 10.0,
            "max_rate_per_s": 5.0,
            "min_interval_s": 1.0,
            "allowed_loop_modes": ["CAS"],
            "hold_off_s": 60.0,
            "watchdog_s": 5.0,
            "readback_tolerance": 0.5,
        }
    },
}


def test_canonical_bytes_sorts_keys_and_strips_insignificant_whitespace() -> None:
    """Canonical bytes produce identical output irrespective of dictionary insertion order."""
    dict_a = {"b": 2, "a": 1, "c": {"y": 20, "x": 10}}
    dict_b = {"a": 1, "c": {"x": 10, "y": 20}, "b": 2}
    assert canonical_bytes(dict_a) == canonical_bytes(dict_b)
    assert b" " not in canonical_bytes(dict_a)


def test_policy_digest_is_stable_under_reordering_and_whitespace() -> None:
    """SHA-256 digest is unchanged by key order differences in Python dictionaries."""
    dict_a = {**VALID_POLICY_DICT}
    dict_b = {
        "targets": VALID_POLICY_DICT["targets"],
        "mode": VALID_POLICY_DICT["mode"],
        "version": VALID_POLICY_DICT["version"],
    }
    assert policy_digest(dict_a) == policy_digest(dict_b)
    assert len(policy_digest(dict_a)) == 64


def test_policy_digest_changes_when_single_number_changes() -> None:
    """Changing one limit value produces an entirely different SHA-256 digest."""
    modified = json.loads(json.dumps(VALID_POLICY_DICT))
    modified["targets"]["FIC101.SP"]["limits"][1] = 100.1
    digest_orig = policy_digest(VALID_POLICY_DICT)
    digest_mod = policy_digest(modified)
    assert digest_orig != digest_mod


def test_load_valid_policy_file_succeeds(tmp_path: Path) -> None:
    """Load valid policy file from disk and return targets dataclasses, mode, and digest."""
    path = tmp_path / "valid_policy.json"
    path.write_text(json.dumps(VALID_POLICY_DICT, indent=2), encoding="utf-8")

    targets, mode, digest = load_policy_file(path)
    assert mode == "supervised"
    assert "FIC101.SP" in targets
    assert targets["FIC101.SP"].limits == (0.0, 100.0)
    assert targets["FIC101.SP"].max_step == 10.0
    assert digest == policy_digest(VALID_POLICY_DICT)


def test_load_valid_policy_file_with_matching_expected_digest(tmp_path: Path) -> None:
    """Load policy file with explicit expected_digest verification succeeding."""
    path = tmp_path / "pinned_policy.json"
    path.write_text(json.dumps(VALID_POLICY_DICT), encoding="utf-8")
    expected_hash = policy_digest(VALID_POLICY_DICT)

    targets, mode, digest = load_policy_file(path, expected_digest=expected_hash)
    assert digest == expected_hash
    assert mode == "supervised"


def test_tampered_policy_file_raises_policy_error_matching_hash_and_digest(tmp_path: Path) -> None:
    """Raise PolicyError naming hash and digest when disk contents differ from expected digest."""
    path = tmp_path / "tampered_policy.json"
    tampered_data = json.loads(json.dumps(VALID_POLICY_DICT))
    tampered_data["targets"]["FIC101.SP"]["max_step"] = 999.0
    path.write_text(json.dumps(tampered_data), encoding="utf-8")

    expected_digest = policy_digest(VALID_POLICY_DICT)
    with pytest.raises(PolicyError, match=r"digest.*mismatch.*hash.*does not match expected"):
        load_policy_file(path, expected_digest=expected_digest)


def test_load_missing_file_raises_policy_error(tmp_path: Path) -> None:
    """Raise PolicyError when policy file does not exist on disk."""
    non_existent = tmp_path / "does_not_exist.json"
    with pytest.raises(PolicyError, match=r"Cannot read policy file"):
        load_policy_file(non_existent)


def test_load_broken_json_raises_policy_error(tmp_path: Path) -> None:
    """Raise PolicyError when file contains malformed JSON syntax."""
    path = tmp_path / "broken.json"
    path.write_text("{ unquoted_key: 123 ", encoding="utf-8")
    with pytest.raises(PolicyError, match=r"Invalid JSON in policy file"):
        load_policy_file(path)


def test_load_schema_violation_raises_policy_error(tmp_path: Path) -> None:
    """Raise PolicyError when file violates JSON schema constraints (e.g. invalid mode)."""
    invalid = json.loads(json.dumps(VALID_POLICY_DICT))
    invalid["mode"] = "invalid_mode_xyz"
    path = tmp_path / "schema_violation.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(PolicyError, match=r"Policy schema validation failed"):
        load_policy_file(path)


def test_load_reversed_limits_raises_policy_error(tmp_path: Path) -> None:
    """Raise PolicyError when limits[0] > limits[1] in target definition."""
    reversed_limits = json.loads(json.dumps(VALID_POLICY_DICT))
    reversed_limits["targets"]["FIC101.SP"]["limits"] = [100.0, 50.0]
    path = tmp_path / "reversed_limits.json"
    path.write_text(json.dumps(reversed_limits), encoding="utf-8")

    with pytest.raises(PolicyError, match=r"limits\[0\].*>.*limits\[1\]"):
        load_policy_file(path)


VALID_TEXT = json.dumps(VALID_POLICY_DICT, indent=2)


def _write_text(tmp_path: Path, text: str) -> Path:
    """Write raw policy text to a fresh file and return its path."""
    path = tmp_path / "raw_policy.json"
    path.write_text(text, encoding="utf-8")
    return path


def test_undecodable_bytes_raise_policy_error(tmp_path: Path) -> None:
    """Non-UTF-8 bytes must surface as PolicyError, not UnicodeDecodeError."""
    path = tmp_path / "bad_bytes.json"
    path.write_bytes(b"\xff{")
    with pytest.raises(PolicyError, match=r"Cannot read policy file") as exc_info:
        load_policy_file(path)
    assert type(exc_info.value) is PolicyError


def test_utf8_bom_prefixed_policy_file_loads(tmp_path: Path) -> None:
    """A UTF-8 byte-order mark before the JSON object is accepted."""
    path = tmp_path / "bom_policy.json"
    path.write_bytes(b"\xef\xbb\xbf" + VALID_TEXT.encode("utf-8"))
    targets, mode, _ = load_policy_file(path)
    assert mode == "supervised"
    assert "FIC101.SP" in targets


def test_duplicate_top_level_key_raises_policy_error(tmp_path: Path) -> None:
    """A repeated root-level key is rejected instead of silently overwriting the first."""
    text = VALID_TEXT.replace('"mode": "supervised"', '"mode": "supervised", "mode": "advisory"')
    with pytest.raises(PolicyError, match=r"duplicate key 'mode'") as exc_info:
        load_policy_file(_write_text(tmp_path, text))
    assert type(exc_info.value) is PolicyError


def test_duplicate_target_key_raises_policy_error(tmp_path: Path) -> None:
    """A repeated key inside a target definition is rejected."""
    text = VALID_TEXT.replace('"max_step": 10.0', '"max_step": 10.0, "max_step": 5.0')
    with pytest.raises(PolicyError, match=r"duplicate key 'max_step'"):
        load_policy_file(_write_text(tmp_path, text))


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_number_tokens_raise_policy_error(tmp_path: Path, token: str) -> None:
    """NaN and Infinity tokens are not valid policy numbers and must be refused."""
    text = VALID_TEXT.replace('"max_step": 10.0', f'"max_step": {token}')
    with pytest.raises(PolicyError, match=r"non-finite number") as exc_info:
        load_policy_file(_write_text(tmp_path, text))
    assert type(exc_info.value) is PolicyError


def test_five_thousand_digit_number_raises_policy_error(tmp_path: Path) -> None:
    """An integer literal over the int-string conversion limit maps to PolicyError."""
    text = VALID_TEXT.replace('"max_step": 10.0', '"max_step": ' + "9" * 5000)
    with pytest.raises(PolicyError, match=r"Invalid JSON in policy file") as exc_info:
        load_policy_file(_write_text(tmp_path, text))
    assert type(exc_info.value) is PolicyError


def test_missing_jsonschema_raises_policy_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the jsonschema package, validation fails with a clear PolicyError."""
    path = _write_text(tmp_path, VALID_TEXT)
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(PolicyError, match=r"jsonschema is required") as exc_info:
        load_policy_file(path)
    assert type(exc_info.value) is PolicyError
