"""Command-line entry point for the Crosscut Write Gateway.

Runs the inbox-mailbox service, drives the gateway loop, and writes state
and audit logs. Handles SIGINT/SIGTERM for graceful shutdown.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from types import FrameType
from typing import cast

from crosscut_gateway.audit import AuditLog
from crosscut_gateway.engine import Mode, start_from_policy_file
from crosscut_gateway.opcua_plant import OpcUaPlant, PlantMapError
from crosscut_gateway.policy import PolicyError
from crosscut_gateway.service import GatewayService, serve


def _positive_float(value: str) -> float:
    """Convert *value* to float and ensure it is > 0."""
    try:
        f = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"must be a number: {value}") from exc
    if f <= 0:
        raise argparse.ArgumentTypeError(f"value must be > 0: {value}")
    return f


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the gateway service."""
    parser = argparse.ArgumentParser(
        description="Run the Crosscut Write Gateway service."
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Root directory containing the _gateway subfolders.",
    )
    parser.add_argument(
        "--policy",
        required=True,
        type=Path,
        help="Path to the write-policy JSON file.",
    )
    parser.add_argument(
        "--plant-map",
        required=True,
        dest="plant_map",
        type=Path,
        help="Path to the plant-map JSON file.",
    )
    parser.add_argument(
        "--mode",
        default="advisory",
        choices=["off", "advisory", "dry_run", "confirm", "supervised"],
        help="Operating mode (default: advisory).",
    )
    parser.add_argument(
        "--interval",
        type=_positive_float,
        default=1.0,
        help="Polling interval in seconds; must be > 0 (default: 1.0).",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=2.0,
        help="OPC-UA connection timeout in seconds; must be > 0 (default: 2.0).",
    )
    return parser.parse_args(argv)


def _install_signals(stop_event: threading.Event) -> None:
    """Install SIGINT and SIGTERM handlers that set *stop_event*."""
    def _handler(_signum: int, _frame: FrameType | None) -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handler)


def _missing_input(policy: Path, plant_map: Path) -> str | None:
    """Return a one-line message for the first missing input file, else None."""
    sidecar = policy.with_suffix(".sha256")
    if not policy.is_file():
        return f"policy file not found: {policy}"
    if not sidecar.is_file():
        return f"policy hash file not found: {sidecar}"
    if not plant_map.is_file():
        return f"plant map file not found: {plant_map}"
    return None


def _initialize(
    root: Path, policy_path: Path, plant: OpcUaPlant, mode: Mode
) -> tuple[GatewayService, threading.Event]:
    """Create audit log, gateway, service, and a stop event wired to signals."""
    audit_path = root / "_gateway" / "audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    gateway = start_from_policy_file(policy_path, plant, mode, AuditLog(audit_path))
    stop_event = threading.Event()
    _install_signals(stop_event)
    return GatewayService(root, gateway), stop_event


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the command-line interface.

    Returns 0 on normal termination, 2 on argument or initialization error.
    """
    args = parse_args(argv)
    problem = _missing_input(args.policy, args.plant_map)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 2
    try:
        plant = OpcUaPlant.from_file(args.plant_map, timeout_s=args.timeout)
    except (OSError, PlantMapError, json.JSONDecodeError) as exc:
        print(f"plant map invalid: {exc}", file=sys.stderr)
        return 2
    try:
        service, stop_event = _initialize(
            args.root, args.policy, plant, cast(Mode, args.mode)
        )
        serve(service, args.interval, stop_event)
        return 0
    except (OSError, PolicyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        plant.close()


if __name__ == "__main__":
    raise SystemExit(main())
