"""Log export (issue #170): zip content, time range and scrubbing of secrets."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from crosscut_api.log_export import LogRangeError, build_export, parse_instant, scrub

START = datetime(2026, 11, 26, 10, 0, 0, tzinfo=UTC)
END = datetime(2026, 11, 26, 11, 0, 0, tzinfo=UTC)


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _members(payload: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return {n: archive.read(n).decode("utf-8") for n in archive.namelist()}


@pytest.mark.parametrize(
    "line",
    [
        "password=hunter2",
        'login {"password": "hunter2"}',
        "Authorization: Bearer abc.def.ghi",
        "cookie: cc_session=abcdef123456",
        "api_key: hunter2",
        "opc.tcp://user:hunter2@host:4840/path",
        "client_secret = hunter2",
        "access_token=hunter2&x=1",
    ],
)
def test_scrub_hides_secret_values(line: str) -> None:
    cleaned = scrub(line)
    assert "hunter2" not in cleaned and "abc.def.ghi" not in cleaned
    assert "abcdef123456" not in cleaned
    assert "[redacted]" in cleaned


def test_scrub_hides_a_private_key_block_and_keeps_plain_text() -> None:
    key = "-----BEGIN PRIVATE KEY-----\nMIIBVgIBADANBg\n-----END PRIVATE KEY-----"
    assert "MIIBVg" not in scrub(f"before\n{key}\nafter")
    assert scrub("job j1 finished in 3 s") == "job j1 finished in 3 s"


def test_export_contains_the_existing_files_inside_the_range(tmp_path: Path) -> None:
    _write(tmp_path, "_logs/api.log",
           "2026-11-26T09:59:59Z INFO a before\n"
           "2026-11-26T10:30:00Z ERROR a inside password=hunter2\n"
           "Traceback (most recent call last):\n  boom\n"
           "2026-11-26T11:00:01Z INFO a after\n")
    _write(tmp_path, "_logs/runtime.log.1", "2026-11-26T10:10:00Z INFO r rotated\n")
    inside = json.dumps({"ts": "2026-11-26T10:20:00+00:00", "level": "error", "message": "x"})
    outside = json.dumps({"ts": "2026-11-26T12:20:00+00:00", "level": "error", "message": "y"})
    _write(tmp_path, "_runtime/log.jsonl", f"{inside}\n{outside}\n")
    payload, names = build_export(tmp_path, START, END)
    members = _members(payload)
    assert names == ["_logs/api.log", "_logs/runtime.log.1", "_runtime/log.jsonl"]
    api = members["_logs/api.log"]
    assert "inside" in api and "boom" in api and "before" not in api and "after" not in api
    assert "hunter2" not in api and "[redacted]" in api
    assert "rotated" in members["_logs/runtime.log.1"]
    assert '"x"' in members["_runtime/log.jsonl"] and '"y"' not in members["_runtime/log.jsonl"]
    assert "README.txt" in members


def test_export_without_any_log_is_an_empty_archive_with_a_readme(tmp_path: Path) -> None:
    payload, names = build_export(tmp_path, START, END)
    assert names == [] and list(_members(payload)) == ["README.txt"]


def test_reversed_range_and_bad_time_are_refused(tmp_path: Path) -> None:
    with pytest.raises(LogRangeError):
        build_export(tmp_path, END, START)
    with pytest.raises(LogRangeError):
        parse_instant("yesterday")
    assert parse_instant("2026-11-26T10:00:00") == START
