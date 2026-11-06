"""Test support for auth-gate and service tests.

Provides helpers to build test environments, sign envelopes, and inspect results.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from crosscut_gateway import engine, envelope, keyfile, policy_pin
from crosscut_gateway import service as gateway_service
from test_gateway_scenarios import POLICY, TAG, S, SimPlant
from test_gateway_service import FakeClock

Mode = Literal["off", "advisory", "dry_run", "confirm", "supervised"]

KEY: bytes = bytes(range(1, 33))


def write_key_file(path: Path, key: bytes) -> Path:
    """Write key to path with owner-only mode, as the gateway refuses loose key files on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    if os.name == "posix":
        os.chmod(path, 0o600)
    return path


@dataclass
class AuthEnv:
    """Test environment with a gateway, service, and paths to key and policy files."""

    root: Path
    clock: FakeClock
    plant: SimPlant
    gateway: engine.WriteGateway
    service: gateway_service.GatewayService
    key_path: Path
    policy_path: Path | None


def make_env(
    tmp_path: Path,
    mode: Mode = "confirm",
    *,
    key: bytes | None = KEY,
    pinned_policy: bool = False,
    start_floor: bool = False,
) -> AuthEnv:
    """Build a test environment with a gateway and service in auth mode.

    Args:
        tmp_path: Root directory for the test environment.
        mode: Initial gateway mode.
        key: HMAC key for the gateway; None to skip writing the key file.
        pinned_policy: True to write a pinned policy file and load it with start_from_policy_file.
        start_floor: True to enforce the replay start-time floor in the service.

    Returns:
        AuthEnv with a gateway, service, and paths to key and policy files.
    """
    clock = FakeClock()
    plant = SimPlant()
    key_path = tmp_path / "_secrets" / keyfile.KEY_FILE_NAME
    if key is not None:
        write_key_file(key_path, key)
    policy_path = None
    if pinned_policy:
        policy_path = tmp_path / "policy" / "write-policy.json"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(json.dumps(policy_doc(mode), indent=2), encoding="utf-8")
        policy_pin.create_pin(
            policy_path,
            KEY,
            policy_pin.PinSigners("author1", "approver1"),
            now=datetime.fromtimestamp(clock(), UTC),
        )
        gateway = engine.start_from_policy_file(policy_path, plant, mode, key=KEY)
    else:
        gateway = engine.WriteGateway(plant, {TAG: POLICY}, mode)
    service = gateway_service.GatewayService(
        tmp_path,
        gateway,
        clock=clock,
        options=gateway_service.ServiceOptions(
            auth_required=True,
            key_path=key_path,
            policy_path=policy_path,
            enforce_start_floor=start_floor,
        ),
    )
    service.poll_once()
    return AuthEnv(tmp_path, clock, plant, gateway, service, key_path, policy_path)


@dataclass(frozen=True)
class SignOpts:
    """Options for signing an envelope."""

    key: bytes = KEY
    cmd_id: str | None = None
    stepup: bool = False
    issued_offset_s: float = 0.0
    nonce: str | None = None


def signed(
    env: AuthEnv,
    cmd: str,
    args: dict[str, Any],
    *,
    actor: str = "alice",
    roles: tuple[str, ...] = ("lead",),
    extra: SignOpts | None = None,
) -> dict[str, Any]:
    """Build and sign an envelope.

    Args:
        env: Test environment.
        cmd: Command name.
        args: Command arguments.
        actor: Actor name.
        roles: Actor roles.
        extra: Additional signing options.

    Returns:
        Signed envelope.
    """
    extra = extra or SignOpts()
    issued_at_ns = int(env.clock() * 1e9) + int(extra.issued_offset_s * 1e9)
    auth = {
        "actor": actor,
        "roles": list(roles),
        "session": "0123456789abcdef",
        "source_ip": "10.0.0.7",
        "issued_at_ns": issued_at_ns,
        "nonce": extra.nonce or secrets.token_hex(16),
    }
    if extra.stepup:
        auth["stepup"] = True
    cmd_id = extra.cmd_id or "c" + secrets.token_hex(4)
    env_without_sig = {"id": cmd_id, "cmd": cmd, "args": args, "auth": auth}
    return envelope.sign_envelope(env_without_sig, extra.key)


def drop(env: AuthEnv, envelope: dict[str, Any]) -> Path:
    """Write an envelope to the inbox.

    Args:
        env: Test environment.
        envelope: Envelope to write.

    Returns:
        Path to the written envelope.
    """
    path = env.root / "_gateway" / "inbox" / f"{envelope['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope), encoding="utf-8")
    return path


def send(env: AuthEnv, cmd: str, args: dict[str, Any], **kw: Any) -> dict[str, Any]:
    """Sign, drop, and poll an envelope.

    Args:
        env: Test environment.
        cmd: Command name.
        args: Command arguments.
        **kw: Additional arguments for signed().

    Returns:
        The signed envelope.
    """
    envelope = signed(env, cmd, args, **kw)
    drop(env, envelope)
    env.service.poll_once()
    return envelope


def rejected_reason(root: Path, name: str) -> str | None:
    """Read the reason for a rejected command.

    Args:
        root: Root directory of the test environment.
        name: Name of the rejected command.

    Returns:
        Reason for rejection, or None if the command was not rejected.
    """
    path = root / "_gateway" / "rejected" / f"{name}.json.reason.txt"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def outbox(root: Path, name: str) -> dict[str, Any] | None:
    """Read an outbox file.

    Args:
        root: Root directory of the test environment.
        name: Name of the outbox file.

    Returns:
        Parsed outbox file, or None if the file does not exist.
    """
    path = root / "_gateway" / "outbox" / f"{name}.json"
    if not path.exists():
        return None
    parsed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return parsed


def audit_events(env: AuthEnv, event: str | None = None) -> list[dict[str, str]]:
    """Filter audit records by event.

    Args:
        env: Test environment.
        event: Event to filter by, or None to return all records.

    Returns:
        List of audit records.
    """
    records = env.gateway.audit_records()
    if event is None:
        return records
    return [r for r in records if r["event"] == event]


def policy_doc(mode: str = "supervised", extra_tags: tuple[str, ...] = ()) -> dict[str, Any]:
    """Build a policy document.

    Args:
        mode: Gateway mode.
        extra_tags: Additional tags to include in the policy.

    Returns:
        Policy document.
    """
    target = {
        "limits": POLICY.limits,
        "max_step": POLICY.max_step,
        "max_rate_per_s": POLICY.max_rate_per_s,
        "min_interval_s": POLICY.min_interval_s,
        "allowed_loop_modes": list(POLICY.allowed_loop_modes),
        "hold_off_s": POLICY.hold_off_s,
        "watchdog_s": POLICY.watchdog_s,
        "readback_tolerance": POLICY.readback_tolerance,
    }
    targets = {TAG: target}
    for tag in extra_tags:
        targets[tag] = target
    return {"version": 1, "mode": mode, "targets": targets}


def propose_args(env: AuthEnv, value: float = 55.0) -> dict[str, Any]:
    """Build propose command arguments.

    Args:
        env: Test environment.
        value: Proposed value.

    Returns:
        Propose command arguments.
    """
    return {
        "target_tag": TAG,
        "value": value,
        "proposer": "tester",
        "t_ns": int(env.clock() * S),
        "reason": "t",
    }

