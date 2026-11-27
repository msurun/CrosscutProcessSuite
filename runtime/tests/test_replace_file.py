"""Tests of store.replace_file: a target another process holds open is retried, not fatal."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from crosscut_runtime import store


def test_replace_file_moves_the_source_over_the_target(tmp_path: Path) -> None:
    """Without a lock it is a plain os.replace."""
    source, target = tmp_path / "a.tmp", tmp_path / "state.json"
    source.write_text("new", encoding="utf-8")
    target.write_text("old", encoding="utf-8")
    store.replace_file(source, target)
    assert target.read_text(encoding="utf-8") == "new"
    assert not source.exists()


def test_replace_file_retries_a_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two refusals (a reader holds the file on Windows) and then success: no error."""
    calls: list[int] = []
    real = os.replace

    def flaky(source: object, target: object) -> None:
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("held by a reader")
        real(source, target)  # type: ignore[arg-type]

    monkeypatch.setattr(store.os, "replace", flaky)
    monkeypatch.setattr(store.time, "sleep", lambda _seconds: None)
    source, target = tmp_path / "a.tmp", tmp_path / "state.json"
    source.write_text("new", encoding="utf-8")
    store.replace_file(source, target)
    assert len(calls) == 3
    assert target.read_text(encoding="utf-8") == "new"


def test_replace_file_gives_up_after_the_last_try(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lock that never clears is still reported."""

    def locked(source: object, target: object) -> None:
        raise PermissionError("always held")

    monkeypatch.setattr(store.os, "replace", locked)
    monkeypatch.setattr(store.time, "sleep", lambda _seconds: None)
    source = tmp_path / "a.tmp"
    source.write_text("new", encoding="utf-8")
    with pytest.raises(PermissionError):
        store.replace_file(source, tmp_path / "state.json")
