"""Entry point of the runtime container: start the scheduler with site settings.

The runtime writes only under the data root and sends signed mailbox commands to
the gateway; it never writes to the plant itself.
"""

from __future__ import annotations

import os
from pathlib import Path

from crosscut_runtime.__main__ import main as runtime_main

ROOT_ENV = "CROSSCUT_ROOT"
INTERVAL_ENV = "CROSSCUT_RUNTIME_INTERVAL"
DEFAULT_ROOT = Path("/var/lib/crosscut")
DEFAULT_INTERVAL_S = 1.0


def _positive_float(name: str, default: float) -> float:
    """Read a positive number from the environment; refuse zero or negative values."""
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError as error:
        raise ValueError(f"{name} must be a number, got {raw!r}") from error
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero, got {value}")
    return value


def build_argv() -> list[str]:
    """Build the crosscut_runtime command line from the container environment."""
    root = os.environ.get(ROOT_ENV, "").strip() or str(DEFAULT_ROOT)
    interval = _positive_float(INTERVAL_ENV, DEFAULT_INTERVAL_S)
    return ["--root", root, "--interval", str(interval)]


def main() -> int:
    """Run the runtime with the arguments from the environment."""
    return runtime_main(build_argv())


if __name__ == "__main__":
    raise SystemExit(main())
