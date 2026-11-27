"""Entry point of the gateway container: turn the env file into gateway flags.

The gateway stays a separate container and process and is the only writer to the
plant (ADR 012); it receives only its own variables, never source credentials.
"""

from __future__ import annotations

import os
from pathlib import Path

from crosscut_gateway.__main__ import main as gateway_main

ROOT_ENV = "CROSSCUT_ROOT"
POLICY_ENV = "CROSSCUT_POLICY"
PLANT_MAP_ENV = "CROSSCUT_PLANT_MAP"
MODE_ENV = "CROSSCUT_GATEWAY_MODE"
INTERVAL_ENV = "CROSSCUT_GATEWAY_INTERVAL"
TIMEOUT_ENV = "CROSSCUT_GATEWAY_TIMEOUT"
KILL_FILE_ENV = "CROSSCUT_GATEWAY_KILL_FILE"
DEFAULT_ROOT = Path("/var/lib/crosscut")
DEFAULT_POLICY = DEFAULT_ROOT / "_gateway" / "policy" / "write-policy.json"
DEFAULT_PLANT_MAP = DEFAULT_ROOT / "plant-map.json"
DEFAULT_MODE = "advisory"
DEFAULT_INTERVAL_S = 1.0
DEFAULT_TIMEOUT_S = 2.0
DEFAULT_KILL_FILE = "config"
KILL_FILE_FLAGS = {"config": [], "on": ["--allow-kill-file"], "off": ["--no-kill-file"]}


def _env_path(name: str, default: Path) -> Path:
    """Return a path from the environment, or the default when it is unset."""
    value = os.environ.get(name, "").strip()
    return Path(value) if value else default


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


def _kill_file_flags() -> list[str]:
    """Map CROSSCUT_GATEWAY_KILL_FILE to the gateway flag, or refuse an unknown value."""
    value = os.environ.get(KILL_FILE_ENV, DEFAULT_KILL_FILE).strip().lower()
    if value not in KILL_FILE_FLAGS:
        allowed = ", ".join(sorted(KILL_FILE_FLAGS))
        raise ValueError(f"{KILL_FILE_ENV} must be one of {allowed}, got {value!r}")
    return KILL_FILE_FLAGS[value]


def build_argv() -> list[str]:
    """Build the crosscut_gateway command line from the container environment."""
    return [
        "--root", str(_env_path(ROOT_ENV, DEFAULT_ROOT)),
        "--policy", str(_env_path(POLICY_ENV, DEFAULT_POLICY)),
        "--plant-map", str(_env_path(PLANT_MAP_ENV, DEFAULT_PLANT_MAP)),
        "--mode", os.environ.get(MODE_ENV, DEFAULT_MODE),
        "--interval", str(_positive_float(INTERVAL_ENV, DEFAULT_INTERVAL_S)),
        "--timeout", str(_positive_float(TIMEOUT_ENV, DEFAULT_TIMEOUT_S)),
        *_kill_file_flags(),
    ]


def main() -> int:
    """Run the gateway with the arguments from the environment."""
    return gateway_main(build_argv())


if __name__ == "__main__":
    raise SystemExit(main())
