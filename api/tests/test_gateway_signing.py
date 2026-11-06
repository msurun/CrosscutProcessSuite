"""Tests that API-side command signing agrees with the gateway's canonical bytes and verifier.

Covers the signature format, replay protection, tamper detection and the fail-closed
behaviour of FileGatewayClient when the signing key or the actor is missing.
"""

import copy
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from auth_support import write_key_file
from crosscut_api.auth.actor import ActorContext
from crosscut_api.auth.signing import (
    Signer,
    canonical_bytes,
    make_signed_command,
    sign_envelope,
)
from crosscut_api.gateway_client import (
    FileGatewayClient,
    GatewaySigningError,
    read_gateway_key,
)
from crosscut_gateway.envelope import NonceCache, verify_envelope
from crosscut_gateway.policy_file import canonical_bytes as gateway_canonical_bytes

KEY_FILE = "gateway-hmac.key"
ACTOR = ActorContext(
    actor="op1",
    roles=("operator",),
    session="a" * 16,
    source_ip="127.0.0.1",
    stepup=False,
    permissions=frozenset(),
)
TAMPERS = [
    (("auth", "roles"), ["admin"]),
    (("args",), {"key": "other"}),
    (("cmd",), "reject"),
    (("id",), "2-xyz"),
    (("auth", "actor"), "op2"),
]


@pytest.fixture(autouse=True)
def _no_secrets_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any CROSSCUT_SECRETS_DIR override so the default _secrets folder applies."""
    monkeypatch.delenv("CROSSCUT_SECRETS_DIR", raising=False)


@pytest.fixture
def key() -> bytes:
    """Return a fresh random 32-byte HMAC key."""
    return os.urandom(32)


def _write_key(folder: Path, key_bytes: bytes) -> None:
    """Write key_bytes to the gateway key file inside folder."""
    write_key_file(folder / KEY_FILE, key_bytes)


def _client(root: Path) -> FileGatewayClient:
    """Return a client rooted at root with timeouts short enough for tests."""
    return FileGatewayClient(root, timeout_s=0.1, poll_s=0.01)


def _inbox_files(root: Path) -> list[Path]:
    """Return the command files currently in the gateway inbox under root."""
    inbox = root / "_gateway" / "inbox"
    return sorted(inbox.iterdir()) if inbox.exists() else []


def _single_inbox_envelope(root: Path) -> dict[str, Any]:
    """Return the parsed envelope of the only command file in the inbox under root."""
    files = _inbox_files(root)
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


def _signed_approve(key: bytes) -> dict[str, Any]:
    """Return a command envelope for approve("k") signed by ACTOR with key."""
    return make_signed_command("1-abc", "approve", {"key": "k"}, Signer(ACTOR, key))


def test_canonical_bytes_matches_gateway() -> None:
    """API and gateway canonical bytes agree on unicode, nested and unsorted data."""
    data = {
        "zeta": {"b": 2, "a": "zażółć"},
        "alpha": [1, {"y": "ą", "x": None}],
        "name": "zażółć",
    }
    assert canonical_bytes(data) == gateway_canonical_bytes(data)


def test_signed_command_verifies_then_replays(key: bytes) -> None:
    """A freshly signed command verifies once, and a second check reports a replayed nonce."""
    env = _signed_approve(key)
    cache = NonceCache()
    assert verify_envelope(env, key, time.time_ns(), cache) == (True, "ok")
    assert verify_envelope(env, key, time.time_ns(), cache) == (False, "replayed_nonce")


@pytest.mark.parametrize(("path", "value"), TAMPERS)
def test_tampered_envelope_has_bad_signature(key: bytes, path: tuple[str, ...], value: Any) -> None:
    """Changing any signed field after signing fails the signature check."""
    tampered = copy.deepcopy(_signed_approve(key))
    target = tampered
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    assert verify_envelope(tampered, key, time.time_ns(), NonceCache()) == (
        False,
        "bad_signature",
    )


def test_wrong_key_has_bad_signature(key: bytes) -> None:
    """A signature made with one key does not verify under a different key."""
    env = _signed_approve(key)
    assert verify_envelope(env, os.urandom(32), time.time_ns(), NonceCache()) == (
        False,
        "bad_signature",
    )


def test_sign_envelope_rejects_short_key() -> None:
    """sign_envelope refuses a 31-byte key instead of signing with it."""
    with pytest.raises(ValueError, match="32 bytes"):
        sign_envelope({"id": "1-abc", "cmd": "kill", "args": {}}, os.urandom(31))


def test_kill_writes_signed_envelope(tmp_path: Path, key: bytes) -> None:
    """Kill sent with a valid key is signed, and the inbox file verifies with that key."""
    _write_key(tmp_path / "_secrets", key)
    with pytest.raises(TimeoutError):
        _client(tmp_path).kill(actor=ACTOR)
    env = _single_inbox_envelope(tmp_path)
    assert env["cmd"] == "kill"
    assert verify_envelope(env, key, time.time_ns(), NonceCache()) == (True, "ok")


def test_approve_writes_signed_envelope(tmp_path: Path, key: bytes) -> None:
    """Approve sent with a valid key is signed as an approve command for key "k"."""
    _write_key(tmp_path / "_secrets", key)
    with pytest.raises(TimeoutError):
        _client(tmp_path).approve("k", actor=ACTOR)
    env = _single_inbox_envelope(tmp_path)
    assert env["cmd"] == "approve"
    assert env["args"] == {"key": "k"}
    assert verify_envelope(env, key, time.time_ns(), NonceCache()) == (True, "ok")


def test_kill_without_key_is_sent_unsigned(tmp_path: Path) -> None:
    """Without a key, kill is still sent, but the inbox envelope has no signature or auth."""
    with pytest.raises(TimeoutError):
        _client(tmp_path).kill(actor=ACTOR)
    env = _single_inbox_envelope(tmp_path)
    assert env.keys() == {"id", "cmd", "args"}


def test_approve_without_key_fails_closed(tmp_path: Path) -> None:
    """Without a key, approve raises GatewaySigningError and nothing reaches the inbox."""
    with pytest.raises(GatewaySigningError):
        _client(tmp_path).approve("k", actor=ACTOR)
    assert _inbox_files(tmp_path) == []


@pytest.mark.parametrize("length", [0, 31])
def test_short_key_counts_as_missing(tmp_path: Path, length: int) -> None:
    """A key file shorter than 32 bytes is treated as no key at all."""
    _write_key(tmp_path / "_secrets", os.urandom(length))
    assert read_gateway_key(tmp_path) is None


def test_secrets_dir_override_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: bytes
) -> None:
    """A key in CROSSCUT_SECRETS_DIR is used, and kill is signed with it."""
    secrets = tmp_path / "elsewhere"
    _write_key(secrets, key)
    monkeypatch.setenv("CROSSCUT_SECRETS_DIR", str(secrets))
    with pytest.raises(TimeoutError):
        _client(tmp_path).kill(actor=ACTOR)
    env = _single_inbox_envelope(tmp_path)
    assert verify_envelope(env, key, time.time_ns(), NonceCache()) == (True, "ok")


def test_approve_with_no_actor_fails_closed(tmp_path: Path, key: bytes) -> None:
    """Even with a valid key, approve without an actor raises GatewaySigningError."""
    _write_key(tmp_path / "_secrets", key)
    with pytest.raises(GatewaySigningError):
        _client(tmp_path).approve("k", actor=None)
    assert _inbox_files(tmp_path) == []
