"""Client for the gateway process, reading state and sending commands through files.

The gateway process owns <root>/_gateway/ and communicates through state.json,
inbox and outbox directories. The client reads state.json and writes commands
to the inbox, then polls the outbox for a response.
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


def _read_json_retry(path: Path, attempts: int = 20, delay_s: float = 0.01) -> dict[str, Any]:
    """Read and parse a JSON file, retrying while another process holds or rewrites it."""
    for _ in range(attempts - 1):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (PermissionError, FileNotFoundError, json.JSONDecodeError):
            time.sleep(delay_s)
    return json.loads(path.read_text(encoding="utf-8"))


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
        self._gateway_dir = root / "_gateway"
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._sleep = sleep

    def _read_state(self) -> dict[str, Any]:
        """Read and parse state.json, retrying while the gateway holds or rewrites it."""
        return _read_json_retry(self._gateway_dir / "state.json", delay_s=self._poll_s)

    def _write_command(self, cmd: str, args: dict[str, Any]) -> str:
        """Write a command to the inbox and return its ID."""
        cmd_id = f"{time.time_ns()}-{uuid.uuid4().hex}"
        inbox_dir = self._gateway_dir / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        temp_path = inbox_dir / f"{cmd_id}.tmp"
        final_path = inbox_dir / f"{cmd_id}.json"
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump({"id": cmd_id, "cmd": cmd, "args": args}, file)
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

    def _send_command(self, cmd: str, args: dict[str, Any]) -> Any:
        """Send a command to the gateway and return the result."""
        cmd_id = self._write_command(cmd, args)
        response = self._await_answer(cmd_id)
        if not isinstance(response, dict):
            raise TypeError("unexpected response format")
        if response.get("ok"):
            return response.get("result")
        error = response.get("error", "")
        if error.startswith("unknown key"):
            raise KeyError(error)
        raise ValueError(error)

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

    def approve(self, key: str) -> dict[str, Any]:
        """Approve and execute a queued proposal; raises KeyError if unknown."""
        result = self._send_command("approve", {"key": key})
        if not isinstance(result, dict):
            raise TypeError("unexpected result for approve command")
        return result

    def reject(self, key: str) -> None:
        """Discard a queued proposal without writing; raises KeyError if unknown."""
        self._send_command("reject", {"key": key})

    def kill(self) -> None:
        """Trigger the emergency kill switch on all targets."""
        self._send_command("kill", {})

    def re_enable(self, tag: str) -> None:
        """Re-enable a stopped target; ValueError if refused, KeyError if unknown."""
        self._send_command("re_enable", {"tag": tag})

    def set_mode(self, mode: str) -> None:
        """Change the operating mode; raises ValueError if invalid."""
        self._send_command("set_mode", {"mode": mode})


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
