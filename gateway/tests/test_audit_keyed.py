"""Tests for the optionally keyed (HMAC) audit chain in crosscut_gateway.audit."""

from __future__ import annotations

from pathlib import Path

import pytest
from crosscut_gateway.audit import AuditError, AuditLog, _compute_hash, verify_chain

KEY = b"k" * 32
OTHER_KEY = b"o" * 32


def _keyed_chain(count: int) -> list[dict[str, str]]:
    log = AuditLog(None, KEY)
    for index in range(count):
        log.append("event", {"n": str(index)}, t_ns=index)
    return log.records()


def _plain_chain(count: int) -> list[dict[str, str]]:
    log = AuditLog()
    for index in range(count):
        log.append("event", {"n": str(index)}, t_ns=index)
    return log.records()


def _next_record(records: list[dict[str, str]], key: bytes | None) -> dict[str, str]:
    """Build a well-formed record after 'records', hashed with 'key' (None means plain)."""
    body = {
        "seq": str(len(records)),
        "t_ns": "99",
        "event": "forged",
        "n": "forged",
        "prev_hash": records[-1]["hash"],
    }
    return {**body, "hash": _compute_hash(body, key)}


def test_keyed_chain_verifies_with_same_key() -> None:
    assert verify_chain(_keyed_chain(3), KEY)


def test_keyed_chain_fails_with_other_key() -> None:
    assert not verify_chain(_keyed_chain(3), OTHER_KEY)


def test_keyed_chain_fails_without_key() -> None:
    assert not verify_chain(_keyed_chain(3))


def test_tampered_field_fails_with_key() -> None:
    records = _keyed_chain(3)
    records[1]["n"] = "tampered"
    assert not verify_chain(records, KEY)


def test_plain_hash_forgery_after_keyed_record_fails() -> None:
    records = _keyed_chain(2)
    records.append(_next_record(records, None))
    assert not verify_chain(records, KEY)


def test_wrong_key_forgery_after_keyed_record_fails() -> None:
    records = _keyed_chain(2)
    records.append(_next_record(records, OTHER_KEY))
    assert not verify_chain(records, KEY)


def test_legacy_plain_prefix_then_keyed_append_verifies(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    plain_log = AuditLog(path)
    plain_log.append("event", {"n": "0"}, t_ns=0)
    plain_log.append("event", {"n": "1"}, t_ns=1)

    keyed_log = AuditLog(path, KEY)
    keyed_log.append("event", {"n": "2"}, t_ns=2)

    reopened = AuditLog(path, KEY)
    assert len(reopened.records()) == 3
    assert verify_chain(reopened.records(), KEY)


def test_plain_prefix_rejected_when_not_allowed() -> None:
    plain = _plain_chain(2)
    assert verify_chain(plain, KEY)
    assert not verify_chain(plain, KEY, allow_plain_prefix=False)


def test_plain_mode_unchanged() -> None:
    records = _plain_chain(3)
    assert verify_chain(records)
    records[0]["n"] = "tampered"
    assert not verify_chain(records)


def test_keyed_hash_differs_from_plain_hash() -> None:
    body = {"seq": "0", "event": "event", "prev_hash": "0" * 64}
    assert _compute_hash(body, KEY) != _compute_hash(body)


def test_keyed_file_reopens_with_same_key(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    AuditLog(path, KEY).append("event", {"n": "0"}, t_ns=0)
    reopened = AuditLog(path, KEY)
    assert len(reopened.records()) == 1


def test_keyed_file_with_wrong_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    AuditLog(path, KEY).append("event", {"n": "0"}, t_ns=0)
    with pytest.raises(AuditError):
        AuditLog(path, OTHER_KEY)


def test_keyed_file_without_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    AuditLog(path, KEY).append("event", {"n": "0"}, t_ns=0)
    with pytest.raises(AuditError):
        AuditLog(path)
