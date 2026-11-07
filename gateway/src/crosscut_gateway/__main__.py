"""Command-line entry point for the Crosscut Write Gateway.

Runs the inbox-mailbox service, drives the gateway loop, and writes state
and audit logs. Handles SIGINT/SIGTERM for graceful shutdown.
The gateway always runs strict: the policy needs a signed pin verified with the HMAC key.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import cast

from crosscut_gateway.audit import AuditError, AuditLog
from crosscut_gateway.engine import Mode, WriteGateway, safe_gateway, start_from_policy_file
from crosscut_gateway.keyfile import default_key_path, key_permission_problem, read_key
from crosscut_gateway.latch_store import kill_latch_present
from crosscut_gateway.opcua_plant import OpcUaPlant, PlantMapError
from crosscut_gateway.policy import PolicyError
from crosscut_gateway.policy_pin import pin_path_for
from crosscut_gateway.service import GatewayService, ServiceOptions, serve


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
        "--roles",
        default=None,
        type=Path,
        help="Roles JSON file; defaults to the packaged table.",
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
    parser.add_argument(
        "--allow-kill-file",
        dest="allow_kill_file",
        action="store_true",
        default=None,
        help="Honour the KILL file in _gateway (default; overrides _auth/config.json).",
    )
    parser.add_argument(
        "--no-kill-file",
        dest="allow_kill_file",
        action="store_false",
        help="Ignore the KILL file; the OS permissions on the folder are then irrelevant to kill.",
    )
    return parser.parse_args(argv)


def kill_file_allowed(args: argparse.Namespace) -> bool:
    """Return whether the KILL file trigger is on: flag first, then the site config, else on."""
    flag = getattr(args, "allow_kill_file", None)
    if flag is not None:
        return bool(flag)
    try:
        data = json.loads((args.root / "_auth" / "config.json").read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return True
    except (OSError, ValueError) as exc:
        print(f"auth config unreadable ({exc}); KILL file stays enabled", file=sys.stderr)
        return True
    value = data.get("kill_file_enabled", True) if isinstance(data, dict) else True
    return value is not False


def _install_signals(stop_event: threading.Event) -> None:
    """Install SIGINT and SIGTERM handlers that set *stop_event*."""
    def _handler(_signum: int, _frame: FrameType | None) -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handler)


def _missing_input(policy: Path, plant_map: Path) -> str | None:
    """Return a one-line message for the first missing input file, else None."""
    if not policy.is_file():
        return f"policy file not found: {policy}"
    pin = pin_path_for(policy)
    if not pin.is_file():
        return f"policy pin file not found: {pin}"
    return _missing_plant_map(plant_map)


def _missing_plant_map(plant_map: Path) -> str | None:
    """Return a one-line message when the plant map is missing, else None."""
    if not plant_map.is_file():
        return f"plant map file not found: {plant_map}"
    return None


def _input_problem(args: argparse.Namespace) -> str | None:
    """Return the first input problem; a set kill latch waives the policy and pin files."""
    if kill_latch_present(args.root / "_gateway"):
        return _missing_plant_map(args.plant_map)
    return _missing_input(args.policy, args.plant_map)


@dataclass(frozen=True)
class _Inputs:
    """Validated paths and the HMAC key the gateway starts from."""

    root: Path
    policy: Path
    roles: Path | None
    key_path: Path
    key: bytes
    allow_kill_file: bool = True


def _load_key(key_path: Path) -> bytes | None:
    """Return the HMAC key at *key_path*, or report why it is unusable and return None."""
    problem = key_permission_problem(key_path)
    if problem is not None:
        print(
            f"gateway HMAC key file rejected ({problem}): {key_path} - chmod 600",
            file=sys.stderr,
        )
        return None
    key = read_key(key_path)
    if key is None:
        print(
            f"gateway HMAC key missing, unreadable or shorter than 32 bytes: {key_path}",
            file=sys.stderr,
        )
    return key


def _prepare(args: argparse.Namespace) -> _Inputs | None:
    """Check the input files and read the HMAC key; return None after reporting a problem."""
    problem = _input_problem(args)
    if problem is not None:
        print(problem, file=sys.stderr)
        return None
    key_path = default_key_path(args.root)
    key = _load_key(key_path)
    if key is None:
        return None
    return _Inputs(args.root, args.policy, args.roles, key_path, key, kill_file_allowed(args))


def _start_gateway(
    inputs: _Inputs, plant: OpcUaPlant, mode: Mode, audit: AuditLog
) -> WriteGateway:
    """Start from the pinned policy; with the kill latch set, fall back to the safe gateway."""
    try:
        return start_from_policy_file(inputs.policy, plant, mode, audit, key=inputs.key)
    except (OSError, PolicyError) as exc:
        if not kill_latch_present(inputs.root / "_gateway"):
            raise
        print(f"policy not loaded, kill latch set; safe gateway only: {exc}", file=sys.stderr)
        return safe_gateway(plant, audit)


def _initialize(
    inputs: _Inputs, plant: OpcUaPlant, mode: Mode
) -> tuple[GatewayService, threading.Event]:
    """Create audit log, gateway, service, and a stop event wired to signals."""
    audit_path = inputs.root / "_gateway" / "audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(audit_path, key=inputs.key)
    gateway = _start_gateway(inputs, plant, mode, audit)
    stop_event = threading.Event()
    _install_signals(stop_event)
    options = ServiceOptions(
        auth_required=True,
        key_path=inputs.key_path,
        roles_path=inputs.roles,
        policy_path=inputs.policy,
        allow_kill_file=inputs.allow_kill_file,
    )
    return GatewayService(inputs.root, gateway, options=options), stop_event


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the command-line interface.

    Returns 0 on normal termination, 2 on argument or initialization error.
    """
    args = parse_args(argv)
    inputs = _prepare(args)
    if inputs is None:
        return 2
    try:
        plant = OpcUaPlant.from_file(args.plant_map, timeout_s=args.timeout)
    except (OSError, PlantMapError, json.JSONDecodeError) as exc:
        print(f"plant map invalid: {exc}", file=sys.stderr)
        return 2
    try:
        service, stop_event = _initialize(inputs, plant, cast(Mode, args.mode))
        serve(service, args.interval, stop_event)
        return 0
    except AuditError as exc:
        message = " ".join(str(exc).split())
        print(f"audit log unusable ({message}); move or archive audit.jsonl", file=sys.stderr)
        return 2
    except (OSError, PolicyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        plant.close()


if __name__ == "__main__":
    raise SystemExit(main())
