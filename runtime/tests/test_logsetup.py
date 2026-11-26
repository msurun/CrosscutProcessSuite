"""Central file logging (issue #170): one rotating file per component, UTC line stamps."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from crosscut_runtime.logsetup import setup_file_logging


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def test_lines_go_to_the_component_file_with_a_utc_stamp(tmp_path: Path) -> None:
    path = setup_file_logging("runtime", tmp_path)
    logging.getLogger("x").warning("hello %s", "world")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert path == tmp_path / "_logs" / "runtime.log"
    line = path.read_text(encoding="utf-8").splitlines()[0]
    assert line[:4].isdigit() and "Z WARNING x hello world" in line


def _own_handlers(root: Path) -> list[RotatingFileHandler]:
    """Rotating handlers writing under this test's root (other tests may leave theirs on the root logger)."""
    return [
        h for h in logging.getLogger().handlers
        if isinstance(h, RotatingFileHandler) and Path(h.baseFilename).is_relative_to(root)
    ]


def test_defaults_and_environment_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_file_logging("a", tmp_path)
    handler = next(h for h in _own_handlers(tmp_path))
    assert (handler.maxBytes, handler.backupCount) == (5_000_000, 5)
    monkeypatch.setenv("CROSSCUT_LOG_MAX_BYTES", "1000")
    monkeypatch.setenv("CROSSCUT_LOG_BACKUPS", "2")
    monkeypatch.setenv("CROSSCUT_LOG_LEVEL", "debug")
    setup_file_logging("a", tmp_path)
    handlers = _own_handlers(tmp_path)
    assert len(handlers) == 1  # idempotent: replaced, not stacked
    assert (handlers[0].maxBytes, handlers[0].backupCount) == (1000, 2)
    assert logging.getLogger().level == logging.DEBUG
