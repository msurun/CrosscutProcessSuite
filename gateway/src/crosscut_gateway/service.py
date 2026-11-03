"""Write Gateway inbox-mailbox service (ADR 011/012, Phase 2 #46).

The only way in is the <root>/_gateway/inbox directory.
Who may write the inbox must be restricted by OS permissions until roles exist (#47).
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from crosscut_gateway.audit import verify_chain
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import WriteProposal
from crosscut_gateway.policy import proposal_key

# Validation kinds:
# "str": non-empty string
# "text": any string
# "number": int or float, not bool
# "int": int, not bool
VALIDATION_SCHEMA: dict[str, list[tuple[str, str]]] = {
    "propose": [
        ("target_tag", "str"),
        ("value", "number"),
        ("proposer", "text"),
        ("t_ns", "int"),
        ("reason", "text"),
    ],
    "approve": [("key", "str")],
    "reject": [("key", "str")],
    "re_enable": [("tag", "str")],
    "set_mode": [("mode", "str")],
    "kill": [],
}


class CommandError(ValueError):
    """Internal error for rejected commands."""


def _replace_with_retry(
    source: Path, target: Path, attempts: int = 50, delay_s: float = 0.01
) -> None:
    """Move *source* over *target*, retrying while a reader on Windows holds *target* open.

    Args:
        source: File to move into place.
        target: Destination that readers may have open.
        attempts: Maximum number of os.replace calls (default: 50).
        delay_s: Seconds to sleep between failed attempts (default: 0.01).

    Raises:
        PermissionError: The last attempt still failed.
    """
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay_s)


class GatewayService:
    """Service that processes command files from an inbox directory and drives a WriteGateway."""

    def __init__(
        self,
        root: Path,
        gateway: WriteGateway,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = root
        self._gateway = gateway
        self._clock = clock
        self._inbox_dir = root / "_gateway" / "inbox"
        self._outbox_dir = root / "_gateway" / "outbox"
        self._rejected_dir = root / "_gateway" / "rejected"
        for directory in (self._inbox_dir, self._outbox_dir, self._rejected_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def _move_to_rejected(self, filepath: Path, reason: str) -> None:
        filename = filepath.name
        rejected_path = self._rejected_dir / filename
        reason_path = self._rejected_dir / (filename + ".reason.txt")
        reason_path.write_text(reason, encoding="utf-8")
        try:
            os.replace(filepath, rejected_path)
        except OSError:
            rejected_path.write_text(filepath.read_text(encoding="utf-8"), encoding="utf-8")
            filepath.unlink()

    @staticmethod
    def _write_atomic(target: Path, data: dict[str, Any]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = target.with_suffix(".tmp")
        with tmp_file.open("w", encoding="utf-8", newline="\n") as output_file:
            json.dump(data, output_file, ensure_ascii=False)
        _replace_with_retry(tmp_file, target)

    def _check_arg(self, cmd: str, name: str, val: Any, kind: str) -> None:
        checkers = {
            "str": self._assert_is_non_empty_string,
            "text": self._assert_is_string,
            "number": self._assert_is_number,
            "int": self._assert_is_int,
        }
        checkers[kind](cmd, name, val)

    def _assert_is_non_empty_string(self, cmd: str, name: str, val: Any) -> None:
        if not isinstance(val, str) or not val:
            raise CommandError(f"{cmd}: {name} must be a non-empty string")

    def _assert_is_string(self, cmd: str, name: str, val: Any) -> None:
        if not isinstance(val, str):
            raise CommandError(f"{cmd}: {name} must be a string")

    def _assert_is_number(self, cmd: str, name: str, val: Any) -> None:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise CommandError(f"{cmd}: {name} must be int or float, not bool")

    def _assert_is_int(self, cmd: str, name: str, val: Any) -> None:
        if isinstance(val, bool) or not isinstance(val, int):
            raise CommandError(f"{cmd}: {name} must be an int")

    def _validate_args(self, cmd: str, args: dict[str, Any]) -> None:
        if cmd not in VALIDATION_SCHEMA:
            raise CommandError(f"unknown cmd: {cmd}")
        for name, kind in VALIDATION_SCHEMA[cmd]:
            if name not in args:
                raise CommandError(f"{cmd}: missing {name}")
            self._check_arg(cmd, name, args[name], kind)

    def _apply(self, cmd_data: dict[str, Any]) -> dict[str, Any]:
        cmd = cmd_data["cmd"]
        args = cmd_data["args"]
        handlers = {
            "propose": self._handle_propose,
            "approve": self._handle_approve,
            "reject": self._handle_reject,
            "kill": self._handle_kill,
            "re_enable": self._handle_re_enable,
            "set_mode": self._handle_set_mode,
        }
        if cmd not in handlers:
            return {"ok": False, "result": None, "error": f"unknown command: {cmd}"}
        try:
            return {"ok": True, "result": handlers[cmd](args), "error": None}
        except (KeyError, ValueError, CommandError) as exc:
            msg = f"unknown key: {exc}" if isinstance(exc, KeyError) else str(exc)
            return {"ok": False, "result": None, "error": msg}

    def _handle_propose(self, args: dict[str, Any]) -> dict[str, Any]:
        proposal = WriteProposal(
            target_tag=args["target_tag"],
            value=float(args["value"]),
            proposer=args["proposer"],
            t_ns=int(args["t_ns"]),
            reason=args["reason"],
        )
        return asdict(self._gateway.propose(proposal))

    def _handle_approve(self, args: dict[str, Any]) -> dict[str, Any]:
        return asdict(self._gateway.approve(args["key"]))

    def _handle_reject(self, args: dict[str, Any]) -> dict[str, Any]:
        self._gateway.reject(args["key"])
        return {}

    def _handle_kill(self, _args: dict[str, Any]) -> dict[str, Any]:
        self._gateway.kill()
        return {}

    def _handle_re_enable(self, args: dict[str, Any]) -> dict[str, Any]:
        self._gateway.re_enable(args["tag"])
        return {}

    def _handle_set_mode(self, args: dict[str, Any]) -> dict[str, Any]:
        self._gateway.set_mode(cast(Literal["confirm", "dry_run", "supervised"], args["mode"]))
        return {}

    def _write_result(self, cmd_id: str, result: dict[str, Any]) -> None:
        outbox_path = self._outbox_dir / f"{cmd_id}.json"
        self._write_atomic(outbox_path, {"id": cmd_id, **result})

    def _get_pending_entries(self) -> list[dict[str, Any]]:
        return [
            {
                "key": proposal_key(proposal),
                "target_tag": proposal.target_tag,
                "value": proposal.value,
                "proposer": proposal.proposer,
                "t_ns": proposal.t_ns,
                "reason": proposal.reason,
            }
            for proposal in self._gateway.pending()
        ]

    def _get_audit_view(self) -> tuple[list[Any], bool]:
        records = self._gateway.audit_records()
        return records[-200:], verify_chain(records)

    def _write_state(self) -> None:
        now = self._clock()
        audit_tail, chain_ok = self._get_audit_view()
        state = {
            "updated_at_utc": datetime.fromtimestamp(now, tz=UTC).isoformat(),
            "mode": self._gateway.mode,
            "targets": self._gateway.status(),
            "pending": self._get_pending_entries(),
            "audit_tail": audit_tail,
            "chain_ok": chain_ok,
        }
        self._write_atomic(self._root / "_gateway" / "state.json", state)

    def poll_once(self) -> None:
        """Process all files in the inbox, then run one gateway tick and write state."""
        for inbox_file in sorted(self._inbox_dir.glob("*.json")):
            self._process_file(inbox_file)
        self._gateway.tick(int(self._clock() * 1_000_000_000))
        self._write_state()

    def _read_command(self, filepath: Path) -> dict[str, Any]:
        try:
            return cast(dict[str, Any], json.loads(filepath.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            raise CommandError(f"malformed JSON: {exc}") from exc

    def _check_envelope(self, cmd_data: Any) -> tuple[str, str, dict[str, Any]]:
        if not isinstance(cmd_data, dict):
            raise CommandError("command must be a JSON object")
        cmd_id, cmd, args = cmd_data.get("id"), cmd_data.get("cmd"), cmd_data.get("args")
        if not isinstance(cmd_id, str) or not cmd_id:
            raise CommandError("id must be a non-empty string")
        if not all(char.isalnum() or char in "._-" for char in cmd_id):
            raise CommandError("id contains invalid characters")
        if not isinstance(cmd, str):
            raise CommandError("cmd must be a string")
        if not isinstance(args, dict):
            raise CommandError("args must be an object")
        return cmd_id, cmd, args

    def _process_file(self, filepath: Path) -> None:
        try:
            cmd_data = self._read_command(filepath)
            cmd_id, cmd, args = self._check_envelope(cmd_data)
            self._validate_args(cmd, args)
            result = self._apply(cmd_data)
            self._write_result(cmd_id, result)
            filepath.unlink()
        except CommandError as exc:
            self._move_to_rejected(filepath, str(exc))


def serve(service: GatewayService, interval_s: float, stop_event: threading.Event) -> None:
    """Run the service loop until *stop_event* is set."""
    while not stop_event.is_set():
        # A transient file-system error must not kill the gateway loop.
        try:
            service.poll_once()
        except OSError:
            pass
        stop_event.wait(interval_s)
