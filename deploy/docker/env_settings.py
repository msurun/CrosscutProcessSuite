"""Readers for the container settings that arrive as environment variables.

The entry points share them so a missing or invalid value fails the same way in
the api, runtime and gateway containers.
"""

from __future__ import annotations

import os
from pathlib import Path


def env_path(name: str, default: Path) -> Path:
    """Return a path from the environment, or the default when it is unset."""
    value = os.environ.get(name, "").strip()
    return Path(value) if value else default


def positive_float(name: str, default: float) -> float:
    """Read a positive number from the environment; refuse zero or negative values."""
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError as error:
        raise ValueError(f"{name} must be a number, got {raw!r}") from error
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero, got {value}")
    return value
