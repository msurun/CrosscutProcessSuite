"""Tests for crosscut_api.auth.passwords.

These tests exercise password hashing, verification, validation helpers and JSON‑schema
compliance for the password record produced by ``hash_password``.
"""

import json
from pathlib import Path

import pytest
from crosscut_api.auth.passwords import (
    ScryptParams,
    dummy_verify,
    hash_password,
    password_problem,
    verify_password,
)


def test_hash_and_verify_correct_and_incorrect_password():
    """hash_password creates a record that verify_password accepts only the original password."""
    params = ScryptParams(n=1024)
    pwd = "correct_password_123"
    record = hash_password(pwd, params)
    assert verify_password(pwd, record) is True
    assert verify_password(pwd + "x", record) is False


def test_hash_password_contains_expected_keys_and_parameters():
    """The generated record includes all mandatory keys and matches the supplied params."""
    params = ScryptParams(n=1024)
    record = hash_password("anyPassword", params)
    expected_keys = {"alg", "n", "r", "p", "salt_b64", "hash_b64"}
    assert set(record) == expected_keys
    assert record["alg"] == "scrypt"
    assert record["n"] == params.n
    assert record["r"] == params.r
    assert record["p"] == params.p


def test_hash_password_produces_unique_salt_and_hash_for_same_password():
    """Identical passwords produce different salts and hashes each call."""
    params = ScryptParams(n=1024)
    rec1 = hash_password("reusedPassword", params)
    rec2 = hash_password("reusedPassword", params)
    assert rec1["salt_b64"] != rec2["salt_b64"]
    assert rec1["hash_b64"] != rec2["hash_b64"]


def test_verify_password_respects_stored_parameters():
    """Verification uses the parameters stored in the record (n=2048 in this case)."""
    pwd = "mySecret123"
    params = ScryptParams(n=2048)
    record = hash_password(pwd, params)
    assert verify_password(pwd, record) is True


def test_plain_password_is_not_present_in_record():
    """The plain password never appears in any string field of the record."""
    pwd = "SuperSecret123!"
    record = hash_password(pwd, ScryptParams(n=1024))
    for value in record.values():
        if isinstance(value, str):
            assert pwd not in value
    assert pwd not in json.dumps(record)


@pytest.mark.parametrize(
    "modify",
    [
        lambda rec: rec.pop("hash_b64"),
        lambda rec: rec.update({"hash_b64": "!!!not-base64!!!"}),
        lambda rec: rec.update({"alg": "bcrypt"}),
        lambda rec: rec.update({"n": "1024"}),
    ],
)
def test_verify_password_with_malformed_records_returns_false(modify):
    """verify_password returns False and never raises for malformed records."""
    pwd = "validPassword123"
    record = hash_password(pwd, ScryptParams(n=1024))
    modify(record)
    assert verify_password(pwd, record) is False


@pytest.mark.parametrize(
    "pwd,min_len,expect_none",
    [
        ("short", None, False),
        ("   ", None, False),
        ("a" * 12, None, True),
        ("abcd", 4, True),
        ("abc", 4, False),
    ],
)
def test_password_problem_various_cases(pwd, min_len, expect_none):
    """password_problem returns None only for acceptable passwords."""
    if min_len is None:
        msg = password_problem(pwd)
    else:
        msg = password_problem(pwd, min_length=min_len)
    assert (msg is None) == expect_none


def test_dummy_verify_returns_none_and_is_cached():
    """dummy_verify should return None without raising, even when called twice."""
    pwd = "anyPassword"
    params = ScryptParams(n=1024)
    assert dummy_verify(pwd, params) is None
    assert dummy_verify(pwd, params) is None


def test_hash_password_record_matches_schema():
    """A password record validates against the auth‑users JSON schema."""
    root = Path(__file__).resolve().parents[2]
    schema_path = root / "schemas" / "auth-users.schema.json"
    schema = json.loads(schema_path.read_text())
    wrapper = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/user/properties/password",
    }
    record = hash_password("validPassword123", ScryptParams(n=1024))
    from jsonschema import validate  # type: ignore

    validate(instance=record, schema=wrapper)
