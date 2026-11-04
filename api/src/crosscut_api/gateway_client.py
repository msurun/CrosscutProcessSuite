"""Client for the gateway process, sending signed commands and reading state through files.

The gateway process owns <root>/_gateway/ and communicates through state.json,
inbox and outbox directories. The client reads state.json, writes signed command
envelopes (version 2) to the inbox, then polls the outbox for a response. Without a
signing key or an actor only the kill command is sent, unsigned.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crosscut_api.auth.actor import ActorContext
from crosscut_api.auth.signing import MIN_KEY_BYTES, Signer, make_signed_command
from crosscut_api.auth_cli import key_path


class GatewaySigningError(RuntimeError):
    """Raised when a command must be signed but the gateway signing key is unavailable."""


def read_gateway_key(root: Path) -> bytes | None:
    """Return the gateway HMAC key bytes, or None when missing, unreadable or too short.

    Args:
        root: The root directory whose key file is located by key_path.

    Returns:
        The key bytes, or None when the file is missing, unreadable or shorter than
        MIN_KEY_BYTES.
    """
    try:
        key = key_path(root).read_bytes()
    except OSError:
        return None
    if len(key) < MIN_KEY_BYTES:
        return None
    return key


def _read_json_retry(path: Path, attempts: int = 20, delay_s: float = 0.01) -> dict[str, Any]:
    """Read and parse a JSON file, retrying while another process holds or rewrites it."""
    for _ in range(attempts - 1):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (PermissionError, FileNotFoundError, json.JSONDecodeError):
            time.sleep(delay_s)
    return json.loads(path.read_text(encoding="utf-8"))


def _error_for(error: str) -> Exception:
    """Map a gateway error message to the exception the caller should receive."""
    if error.startswith("unknown key"):
        return KeyError(error)
    if error.startswith(("forbidden", "auth_reject")):
        return PermissionError(error)
    return ValueError(error)


class FileGatewayClient:
    """Client for the gateway process, reading state and sending commands through files."""

    def __init__(
        self,
        root: Path,
        timeout_s: float = 5.0,
        poll_s: float = 0.05,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the client with the gateway directory and communication parameters.

        Args:
            root: The root directory of the gateway process.
            timeout_s: Maximum seconds to wait for a response (default: 5.0).
            poll_s: Seconds between polling the outbox (default: 0.05).
            sleep: Callable to sleep between polls (default: time.sleep).
        """
        self._root = root
        self._gateway_dir = root / "_gateway"
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._sleep = sleep

    def _read_state(self) -> dict[str, Any]:
        """Read and parse state.json, retrying while the gateway holds or rewrites it."""
        return _read_json_retry(self._gateway_dir / "state.json", delay_s=self._poll_s)

    def _envelope(
        self, cmd_id: str, cmd: str, args: dict[str, Any], actor: ActorContext | None
    ) -> dict[str, Any]:
        """Return the envelope for a command: signed when possible, otherwise kill only.

        Raises:
            GatewaySigningError: When the command cannot be signed and is not kill.
        """
        key = read_gateway_key(self._root)
        if key is not None and actor is not None:
            return make_signed_command(cmd_id, cmd, args, Signer(actor, key))
        if cmd == "kill":
            return {"id": cmd_id, "cmd": cmd, "args": args}
        raise GatewaySigningError(
            "gateway signing key missing or unreadable; run auth_cli init"
        )

    def _write_command(
        self, cmd: str, args: dict[str, Any], actor: ActorContext | None
    ) -> str:
        """Write a command envelope to the inbox and return its ID."""
        cmd_id = f"{time.time_ns()}-{uuid.uuid4().hex}"
        envelope = self._envelope(cmd_id, cmd, args, actor)
        inbox_dir = self._gateway_dir / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        temp_path = inbox_dir / f"{cmd_id}.tmp"
        final_path = inbox_dir / f"{cmd_id}.json"
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(envelope, file)
        os.replace(temp_path, final_path)
        return cmd_id

    def _await_answer(self, cmd_id: str) -> dict[str, Any]:
        """Poll the outbox for a response to the command with cmd_id."""
        outbox_path = self._gateway_dir / "outbox" / f"{cmd_id}.json"
        deadline = time.monotonic() + self._timeout_s
        while time.monotonic() < deadline:
            try:
                with outbox_path.open("r", encoding="utf-8") as file:
                    response = json.load(file)
            except (PermissionError, FileNotFoundError, json.JSONDecodeError):
                self._sleep(self._poll_s)
            else:
                os.remove(outbox_path)
                return response
        raise TimeoutError("gateway did not answer")

    def _send_command(self, cmd: str, args: dict[str, Any], actor: ActorContext | None) -> Any:
        """Send a command to the gateway and return the result."""
        cmd_id = self._write_command(cmd, args, actor)
        response = self._await_answer(cmd_id)
        if not isinstance(response, dict):
            raise TypeError("unexpected response format")
        if response.get("ok"):
            return response.get("result")
        raise _error_for(response.get("error", ""))

    def mode(self) -> str:
        """Return the active operating mode of the gateway."""
        state = self._read_state()
        return state["mode"]

    def status(self) -> dict[str, str]:
        """Return the state of each target tag."""
        state = self._read_state()
        return state["targets"]

    def pending(self) -> list[dict[str, Any]]:
        """Return proposals awaiting confirmation, each with its stable key."""
        state = self._read_state()
        return state["pending"]

    def audit(self, limit: int) -> dict[str, Any]:
        """Return the newest audit records and the chain integrity flag."""
        state = self._read_state()
        audit_tail = state["audit_tail"]
        if limit <= 0:
            records = []
        else:
            records = audit_tail[-limit:]
        return {"records": records, "chain_ok": state["chain_ok"]}

    def draft_policy(self) -> dict[str, Any] | None:
        """Return the policy draft document, or None when no draft file exists."""
        try:
            text = (self._gateway_dir / "policy-draft.json").read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        return json.loads(text)

    def approve(self, key: str, actor: ActorContext | None = None) -> dict[str, Any]:
        """Approve and execute a queued proposal; raises KeyError if unknown."""
        result = self._send_command("approve", {"key": key}, actor)
        if not isinstance(result, dict):
            raise TypeError("unexpected result for approve command")
        return result

    def reject(self, key: str, actor: ActorContext | None = None) -> None:
        """Discard a queued proposal without writing; raises KeyError if unknown."""
        self._send_command("reject", {"key": key}, actor)

    def kill(self, actor: ActorContext | None = None) -> None:
        """Trigger the emergency kill switch on all targets."""
        self._send_command("kill", {}, actor)

    def kill_reset(self, actor: ActorContext | None = None) -> None:
        """Clear the emergency kill switch so targets can be re-enabled."""
        self._send_command("kill_reset", {}, actor)

    def re_enable(self, tag: str, actor: ActorContext | None = None) -> None:
        """Re-enable a stopped target; ValueError if refused, KeyError if unknown."""
        self._send_command("re_enable", {"tag": tag}, actor)

    def set_mode(self, mode: str, actor: ActorContext | None = None) -> None:
        """Change the operating mode; raises ValueError if invalid."""
        self._send_command("set_mode", {"mode": mode}, actor)

    def policy_draft(self, document: dict[str, Any], actor: ActorContext | None = None) -> None:
        """Submit a policy document as the draft for review."""
        self._send_command("policy_draft", {"document": document}, actor)

    def policy_pin(self, digest: str, actor: ActorContext | None = None) -> None:
        """Pin the policy with the given digest as the active policy."""
        self._send_command("policy_pin", {"digest": digest}, actor)

    def policy_reload(self, actor: ActorContext | None = None) -> None:
        """Reload the pinned policy in the gateway."""
        self._send_command("policy_reload", {}, actor)


def _is_fresh(state_path: Path, max_age_s: float, now_s: float) -> bool:
    """Return True if state.json parses and its updated_at_utc is within max_age_s of now_s."""
    try:
        state = _read_json_retry(state_path)
        updated_at = datetime.fromisoformat(state["updated_at_utc"])
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        current_time = datetime.fromtimestamp(now_s, tz=UTC)
        return abs((current_time - updated_at).total_seconds()) <= max_age_s
    except (OSError, ValueError, TypeError, KeyError):
        return False


def gateway_provider(
    root: Path,
    max_age_s: float = 10.0,
    now: Callable[[], float] = time.time,
) -> Callable[[], FileGatewayClient | None]:
    """Build a provider for the gateway client, caching the client instance.

    Args:
        root: The root directory of the gateway process.
        max_age_s: Maximum age of the state file in seconds (default: 10.0).
        now: Callable to get the current time (default: time.time).

    Returns:
        A callable that returns the gateway client if the state file is valid,
        otherwise None.
    """
    client = FileGatewayClient(root, timeout_s=5.0)

    def provider() -> FileGatewayClient | None:
        """Return the gateway client if the state file is valid, otherwise None."""
        state_path = root / "_gateway" / "state.json"
        if _is_fresh(state_path, max_age_s, now()):
            return client
        return None

    return provider
