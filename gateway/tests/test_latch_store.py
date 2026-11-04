"""Tests for latch_store: atomic JSON writes, the KILLED kill latch and tolerant JSON reads.

Covers the write/read roundtrip, leftover-free atomic replacement, latch present/clear
semantics and read_json_object returning None for every unusable input.
"""

from __future__ import annotations

import json
from pathlib import Path

from crosscut_gateway.latch_store import (
    KILLED_NAME,
    clear_kill_latch,
    kill_latch_present,
    read_json_object,
    write_json_atomic,
    write_kill_latch,
)


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    write_json_atomic(target, {"name": "zażółć", "n": 3})
    assert read_json_object(target) == {"name": "zażółć", "n": 3}
    assert "zażółć" in target.read_text(encoding="utf-8")


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    write_json_atomic(target, {"a": 1})
    write_json_atomic(target, {"a": 2})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}


def test_write_json_atomic_creates_missing_parent(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "er" / "state.json"
    write_json_atomic(target, {"ok": True})
    assert read_json_object(target) == {"ok": True}


def test_kill_latch_present_clear_and_clear_twice(tmp_path: Path) -> None:
    assert KILLED_NAME == "KILLED"
    assert kill_latch_present(tmp_path) is False
    write_kill_latch(tmp_path, "operator", "2026-11-04T10:00:00Z")
    assert kill_latch_present(tmp_path) is True
    assert read_json_object(tmp_path / KILLED_NAME) == {
        "actor": "operator",
        "at_utc": "2026-11-04T10:00:00Z",
    }
    clear_kill_latch(tmp_path)
    assert kill_latch_present(tmp_path) is False
    clear_kill_latch(tmp_path)
    assert kill_latch_present(tmp_path) is False


def test_read_json_object_none_for_missing_file(tmp_path: Path) -> None:
    assert read_json_object(tmp_path / "absent.json") is None


def test_read_json_object_none_for_undecodable_bytes(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(b"\xff")
    assert read_json_object(path) is None


def test_read_json_object_none_for_non_object(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[1]", encoding="utf-8")
    assert read_json_object(path) is None


def test_read_json_object_none_for_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "trunc.json"
    path.write_text("[" * 100000, encoding="utf-8")
    assert read_json_object(path) is None


def test_read_json_object_returns_dict(tmp_path: Path) -> None:
    path = tmp_path / "ok.json"
    path.write_text('{"a":1}', encoding="utf-8")
    assert read_json_object(path) == {"a": 1}


