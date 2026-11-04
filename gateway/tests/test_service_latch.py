"""Behaviour tests for the kill latch, the restart start-floor and the persisted nonce cache.

Covers the KILLED latch written on kill, the KILL trigger file rename, signed kill_reset, replay
refusal across a restart, the bounded nonce-cache file and the key_acl field in state.json.
All tests use auth_helpers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from auth_helpers import (
    AuthEnv,
    drop,
    make_env,
    outbox,
    propose_args,
    rejected_reason,
    send,
    signed,
)
from crosscut_gateway import engine, keyfile
from crosscut_gateway import service as gateway_service
from test_gateway_scenarios import POLICY, TAG, SimPlant


@pytest.fixture
def env(tmp_path: Path) -> AuthEnv:
    """Build a confirm-mode environment whose service does not enforce the start floor."""
    return make_env(tmp_path, start_floor=False)


def _gateway_dir(root: Path) -> Path:
    """Return the <root>/_gateway directory holding the latch, inbox and state files."""
    return root / "_gateway"


def _state(env: AuthEnv) -> dict:
    """Read the persisted gateway state.json for the test environment."""
    return json.loads((_gateway_dir(env.root) / "state.json").read_text(encoding="utf-8"))


def _build(
    env: AuthEnv, gateway: engine.WriteGateway, *, floor: bool = True
) -> gateway_service.GatewayService:
    """Construct a GatewayService over the environment root with the given gateway."""
    options = gateway_service.ServiceOptions(
        auth_required=True,
        key_path=env.key_path,
        policy_path=env.policy_path,
        enforce_start_floor=floor,
    )
    return gateway_service.GatewayService(env.root, gateway, clock=env.clock, options=options)


def restart(
    env: AuthEnv, *, floor: bool = True
) -> tuple[gateway_service.GatewayService, engine.WriteGateway]:
    """Simulate a process restart: a fresh WriteGateway and a new service over the same root.

    Args:
        env: Test environment whose root, clock and key paths are reused.
        floor: True to enforce the start floor on the new service.

    Returns:
        The new service and the gateway it drives.
    """
    gateway = engine.WriteGateway(SimPlant(), {TAG: POLICY}, "confirm")
    return _build(env, gateway, floor=floor), gateway


def _send_to(
    env: AuthEnv, service: gateway_service.GatewayService, cmd: str, args: dict, **kw: object
) -> dict:
    """Sign and drop an envelope, then poll the given service (not necessarily env.service)."""
    envelope = signed(env, cmd, args, **kw)  # type: ignore[arg-type]
    drop(env, envelope)
    service.poll_once()
    return envelope


def _refused(root: Path, cmd_id: str) -> bool:
    """Return True when the command was refused, via its outbox decision or rejected file."""
    result = outbox(root, cmd_id)
    if result is not None:
        inner = result.get("result") or {}
        return result.get("ok") is False or inner.get("accepted") is False
    return rejected_reason(root, cmd_id) is not None


def _reason(root: Path, cmd_id: str) -> str:
    """Return the stripped rejection reason for a command, or an empty string."""
    return (rejected_reason(root, cmd_id) or "").strip()


def test_signed_kill_writes_latch_file(env: AuthEnv) -> None:
    """A signed kill writes KILLED atomically with the actor and a UTC timestamp."""
    send(env, "kill", {}, roles=("lead",))
    latch = json.loads((_gateway_dir(env.root) / "KILLED").read_text(encoding="utf-8"))
    assert latch["actor"] == "alice"
    assert isinstance(latch["at_utc"], str)


def test_kill_file_trigger_is_renamed(env: AuthEnv) -> None:
    """A KILL trigger file kills the gateway, is renamed to KILL.handled-<ts> and sets the latch."""
    gateway_dir = _gateway_dir(env.root)
    (gateway_dir / "KILL").write_text("", encoding="utf-8")
    env.service.poll_once()
    assert not (gateway_dir / "KILL").exists()
    assert len(list(gateway_dir.glob("KILL.handled-*"))) == 1
    assert (gateway_dir / "KILLED").exists()
    assert env.gateway.killed is True


def test_restart_after_kill_stays_killed(env: AuthEnv) -> None:
    """After a restart the latch holds: targets stay killed and a signed propose is refused."""
    send(env, "kill", {}, roles=("operator",))
    service, gateway = restart(env)
    service.poll_once()
    assert gateway.killed is True
    assert set(gateway.status().values()) == {"killed"}
    envelope = _send_to(env, service, "propose", propose_args(env), roles=("engineer",))
    assert _refused(env.root, envelope["id"])


def test_restart_killed_with_empty_policy_still_accepts_kill_reset(env: AuthEnv) -> None:
    """A KILLED latch on a gateway with no policies still lets a signed kill_reset clear it."""
    gateway_dir = _gateway_dir(env.root)
    gateway_dir.mkdir(parents=True, exist_ok=True)
    (gateway_dir / "KILLED").write_text(json.dumps({"actor": "x", "at_utc": "t"}), "utf-8")
    gateway = engine.WriteGateway(SimPlant(), {}, "off")
    service = _build(env, gateway)
    service.poll_once()
    assert gateway.killed is True
    _send_to(env, service, "kill_reset", {}, roles=("lead",))
    assert not (gateway_dir / "KILLED").exists()
    assert gateway.killed is False
    assert gateway.mode == "advisory"


def test_kill_reset_clears_latch_and_stops_targets(env: AuthEnv) -> None:
    """kill_reset clears the latch, returns the gateway to advisory and leaves targets stopped."""
    send(env, "kill", {}, roles=("lead",))
    send(env, "kill_reset", {}, roles=("lead",))
    assert env.gateway.mode == "advisory"
    statuses = env.gateway.status()
    assert statuses and set(statuses.values()) == {"stopped:kill"}
    assert not (_gateway_dir(env.root) / "KILLED").exists()


def test_latch_persists_when_kill_reset_is_refused(env: AuthEnv) -> None:
    """A viewer's kill_reset is refused and the KILLED latch file stays in place."""
    send(env, "kill", {}, roles=("lead",))
    send(env, "kill_reset", {}, roles=("viewer",))
    assert (_gateway_dir(env.root) / "KILLED").exists()
    assert env.gateway.killed is True


def test_envelope_before_start_is_refused_after_restart(env: AuthEnv) -> None:
    """An envelope issued before the restarted service started is refused as predates_start."""
    envelope = signed(env, "propose", propose_args(env), roles=("engineer",))
    env.clock.advance(20)
    service, _ = restart(env, floor=True)
    drop(env, envelope)
    service.poll_once()
    assert _reason(env.root, envelope["id"]) == "predates_start"


def test_replay_after_restart_is_refused(env: AuthEnv) -> None:
    """A propose replayed after a restart is refused, because the nonce cache survives it."""
    envelope = send(env, "propose", propose_args(env), roles=("engineer",))
    cache = json.loads((_gateway_dir(env.root) / "nonce-cache.json").read_text(encoding="utf-8"))
    assert envelope["auth"]["nonce"] in cache["nonces"]
    service, _ = restart(env, floor=False)
    drop(env, envelope)
    service.poll_once()
    assert _reason(env.root, envelope["id"]) in {"replayed_nonce", "replayed_id"}


def test_nonce_cache_file_is_bounded_and_atomic_json(env: AuthEnv) -> None:
    """The nonce cache is a JSON object with nonces and ids maps, each capped at 500 entries."""
    send(env, "propose", propose_args(env), roles=("engineer",))
    cache = json.loads((_gateway_dir(env.root) / "nonce-cache.json").read_text(encoding="utf-8"))
    assert isinstance(cache["nonces"], dict)
    assert isinstance(cache["ids"], dict)
    assert len(cache["nonces"]) <= 500
    assert len(cache["ids"]) <= 500


def test_state_json_reports_key_acl(env: AuthEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """state.json reports key_acl as ok or unchecked, and unchecked on non-POSIX platforms."""
    send(env, "propose", propose_args(env), roles=("engineer",))
    assert _state(env)["key_acl"] in {"unchecked", "ok"}
    monkeypatch.setattr(keyfile, "_IS_POSIX", False)
    env.service.poll_once()
    assert _state(env)["key_acl"] == "unchecked"
