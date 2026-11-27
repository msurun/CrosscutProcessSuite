"""Central file logging for the Crosscut processes (gateway), issue #170.

Every process writes one rotating log file ``<data root>/_logs/<component>.log`` in addition to
stdout, so the Health page can export the logs of a time range. Defaults (all overridable by
environment variables): level INFO, 5 MB per file, 5 rotated files kept. One line is
``<UTC ISO time>Z <LEVEL> <logger> <message>``; a traceback continues on the following lines.
The runtime and the API share the same code in crosscut_runtime.logsetup.
"""

from __future__ import annotations

import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FOLDER = "_logs"
LINE_FORMAT = "%(asctime)sZ %(levelname)s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
DEFAULT_LEVEL = "INFO"
DEFAULT_MAX_BYTES = 5_000_000
DEFAULT_BACKUPS = 5
_MARK = "_crosscut_component"
CONSOLE = "_console"


def _env_int(name: str, default: int) -> int:
    """A positive integer environment setting, the default when unset or invalid."""
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def _formatter() -> logging.Formatter:
    """UTC time stamps, so lines of all components compare and filter by time."""
    formatter = logging.Formatter(LINE_FORMAT, DATE_FORMAT)
    formatter.converter = time.gmtime
    return formatter


def setup_file_logging(component: str, root: Path) -> Path:
    """Attach a rotating file handler for ``component`` to the root logger; returns the log path.

    Idempotent: a second call for the same component replaces the first handler.
    Settings: ``CROSSCUT_LOG_LEVEL``, ``CROSSCUT_LOG_MAX_BYTES``, ``CROSSCUT_LOG_BACKUPS``.
    """
    path = root / LOG_FOLDER / f"{component}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    for handler in list(logger.handlers):
        if getattr(handler, _MARK, None) in (component, CONSOLE):
            logger.removeHandler(handler)
            handler.close()
    handler = RotatingFileHandler(
        path,
        maxBytes=_env_int("CROSSCUT_LOG_MAX_BYTES", DEFAULT_MAX_BYTES),
        backupCount=_env_int("CROSSCUT_LOG_BACKUPS", DEFAULT_BACKUPS),
        encoding="utf-8",
    )
    handler.setFormatter(_formatter())
    setattr(handler, _MARK, component)
    logger.addHandler(handler)
    console = logging.StreamHandler()  # keeps the stderr output a bare root logger would have
    console.setFormatter(_formatter())
    setattr(console, _MARK, CONSOLE)
    logger.addHandler(console)
    logger.setLevel(os.environ.get("CROSSCUT_LOG_LEVEL", DEFAULT_LEVEL).upper())
    return path
