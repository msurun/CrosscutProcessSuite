"""A failed audit file write leaves the in-memory and on-disk chains consistent (no gap)."""

from __future__ import annotations

from pathlib import Path

import pytest
from crosscut_gateway import audit
from crosscut_gateway.audit import AuditError, AuditLog, AuditWriteError, verify_chain

KEY = b"k" * 32


class _FailingFile:
    """File stand-in that writes half of the line to disk, then fails like a full disk."""

    def __init__(self, real: object) -> None:
        self._real = real

    def __enter__(self) -> _FailingFile:
        return self

    def __exit__(self, *exc: object) -> None:
        self._real.close()  # type: ignore[attr-defined]

    def write(self, text: str) -> int:
        self._real.write(text[: len(text) // 2])  # type: ignore[attr-defined]
        self._real.flush()  # type: ignore[attr-defined]
        raise OSError("disk full")


def _fail_next_open(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    """Make the next append-mode open of ``path`` return a failing file."""
    original = Path.open
    state = {"armed": True}

    def flaky(self: Path, mode: str = "r", *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        real = original(self, mode, *args, **kwargs)  # type: ignore[arg-type]
        if self == path and mode == "a" and state["armed"]:
            state["armed"] = False
            return _FailingFile(real)
        return real

    monkeypatch.setattr(Path, "open", flaky)


@pytest.mark.parametrize("key", [None, KEY])
def test_write_error_keeps_memory_and_file_chain_verifiable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: bytes | None
) -> None:
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path, key)
    log.append("one", {"n": "1"}, 1)
    _fail_next_open(monkeypatch, path)
    with pytest.raises(AuditWriteError):
        log.append("two", {"n": "2"}, 2)
    assert [r["event"] for r in log.records()] == ["one"]
    assert verify_chain(log.records(), key)
    third = log.append("three", {"n": "3"}, 3)
    assert third["seq"] == "1" and third["prev_hash"] == log.records()[0]["hash"]
    reloaded = AuditLog(path, key)  # raises AuditError if the file chain has a gap
    assert reloaded.records() == log.records()


def test_write_error_is_an_oserror_and_an_audit_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    log = AuditLog(blocker / "audit.jsonl")  # parent is a file: mkdir/open fail
    with pytest.raises(OSError) as info:
        log.append("one", {}, 1)
    assert isinstance(info.value, AuditWriteError) and isinstance(info.value, AuditError)
    assert log.records() == []


def test_module_exports_write_error() -> None:
    assert issubclass(audit.AuditWriteError, OSError)
