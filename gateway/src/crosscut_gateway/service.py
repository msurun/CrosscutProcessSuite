"""Write Gateway inbox-mailbox service (ADR 011/012, Phase 2 #46).

The only way in is the <root>/_gateway/inbox directory. With auth_required, each command must
carry an HMAC envelope that AuthGate verifies, and policy commands pass a policy precheck.
Without it (legacy mode) the inbox is trusted, so OS permissions must restrict who writes it.
A KILL file in <root>/_gateway kills the gateway in every mode.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from crosscut_gateway.actor import GATEWAY_ACTOR, ActorContext
from crosscut_gateway.audit import verify_chain
from crosscut_gateway.auth_gate import AuthGate, roles_digest
from crosscut_gateway.authz import roles_or_default
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import WriteProposal
from crosscut_gateway.keyfile import default_key_path, read_key
from crosscut_gateway.policy import proposal_key
from crosscut_gateway.policy_cmds import PolicyCommandError, PolicyCommands, PolicyPaths

# Validation kinds:
# "str": non-empty string
# "text": any string
# "number": int or float, not bool
# "int": int, not bool
# "object": dict
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
    "kill_reset": [],
    "policy_draft": [("document", "object")],
    "policy_pin": [],
    "policy_reload": [],
}


class CommandError(ValueError):
    """Internal error for rejected commands."""


class AuthRejected(Exception):
    """A command failed authentication or the policy precheck; carries the reason and caller."""

    def __init__(self, reason: str, ctx: ActorContext) -> None:
        """Store the refusal reason and the attributed caller."""
        super().__init__(reason)
        self.reason = reason
        self.ctx = ctx


@dataclass(frozen=True)
class ServiceOptions:
    """Startup switches: whether commands must be authenticated, and the key, roles and policy."""

    auth_required: bool = False
    key_path: Path | None = None
    roles_path: Path | None = None
    policy_path: Path | None = None


_DEFAULT_OPTIONS = ServiceOptions()
_UNKNOWN_CTX = ActorContext(actor="unknown")
_LEGACY_CTX = ActorContext(actor="legacy")
_KILL_FILE_CTX = ActorContext(actor="unsigned", source_ip="kill_file", cmd_id="KILL")
_Handler = Callable[[dict[str, Any], ActorContext | None], dict[str, Any]]


def _policy_actor(ctx: ActorContext | None) -> ActorContext:
    """Return ctx, or the legacy actor when no gate attributed the command."""
    return _LEGACY_CTX if ctx is None else ctx


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
        *,
        options: ServiceOptions = _DEFAULT_OPTIONS,
    ) -> None:
        self._root = root
        self._gateway = gateway
        self._clock = clock
        self._inbox_dir = root / "_gateway" / "inbox"
        self._outbox_dir = root / "_gateway" / "outbox"
        self._rejected_dir = root / "_gateway" / "rejected"
        self._kill_path = root / "_gateway" / "KILL"
        self._key_path = options.key_path or default_key_path(root)
        self._gate: AuthGate | None = None
        self._roles_digest = ""
        self._policy = PolicyCommands(
            PolicyPaths(options.policy_path, root / "_gateway" / "policy-draft.json"),
            key_source=self._policy_key,
            clock=clock,
        )
        for directory in (self._inbox_dir, self._outbox_dir, self._rejected_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._setup_auth(options)

    def _setup_auth(self, options: ServiceOptions) -> None:
        """Load roles and the gate when auth is required; legacy mode keeps no gate."""
        if not options.auth_required:
            return
        roles, fallback_reason = roles_or_default(options.roles_path)
        self._gate = AuthGate(roles, self._clock)
        self._roles_digest = roles_digest(roles)
        self._refresh_key()
        self._gateway.record_event(
            "roles_loaded", GATEWAY_ACTOR, fallback_reason or "ok", value=self._roles_digest
        )

    def _refresh_key(self) -> None:
        """Reload the HMAC key from disk so a key rotation takes effect on the next poll."""
        if self._gate is not None:
            self._gate.set_key(read_key(self._key_path))

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
            "object": self._assert_is_object,
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

    def _assert_is_object(self, cmd: str, name: str, val: Any) -> None:
        if not isinstance(val, dict):
            raise CommandError(f"{cmd}: {name} must be an object")

    def _validate_args(self, cmd: str, args: dict[str, Any]) -> None:
        if cmd not in VALIDATION_SCHEMA:
            raise CommandError(f"unknown cmd: {cmd}")
        for name, kind in VALIDATION_SCHEMA[cmd]:
            if name not in args:
                raise CommandError(f"{cmd}: missing {name}")
            self._check_arg(cmd, name, args[name], kind)

    def _apply(self, cmd_data: dict[str, Any], ctx: ActorContext | None) -> dict[str, Any]:
        """Run the command in cmd_data as ctx; refusals return ok=False instead of raising."""
        cmd = cmd_data["cmd"]
        args = cmd_data["args"]
        handlers = self._handlers()
        if cmd not in handlers:
            return {"ok": False, "result": None, "error": f"unknown command: {cmd}"}
        try:
            return {"ok": True, "result": handlers[cmd](args, ctx), "error": None}
        except (KeyError, ValueError, CommandError, PolicyCommandError) as exc:
            msg = f"unknown key: {exc}" if isinstance(exc, KeyError) else str(exc)
            return {"ok": False, "result": None, "error": msg}

    def _handlers(self) -> dict[str, _Handler]:
        """Return the table mapping each gateway command name to its handler."""
        return {
            "propose": self._handle_propose,
            "approve": self._handle_approve,
            "reject": self._handle_reject,
            "kill": self._handle_kill,
            "kill_reset": self._handle_kill_reset,
            "re_enable": self._handle_re_enable,
            "set_mode": self._handle_set_mode,
            "policy_draft": self._handle_policy_draft,
            "policy_pin": self._handle_policy_pin,
            "policy_reload": self._handle_policy_reload,
        }

    def _handle_propose(
        self, args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        proposal = WriteProposal(
            target_tag=args["target_tag"],
            value=float(args["value"]),
            proposer=args["proposer"],
            t_ns=int(args["t_ns"]),
            reason=args["reason"],
        )
        return asdict(self._gateway.propose(proposal, actor_ctx=ctx))

    def _handle_approve(
        self, args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        return asdict(self._gateway.approve(args["key"], actor_ctx=ctx))

    def _handle_reject(
        self, args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        self._gateway.reject(args["key"], actor_ctx=ctx)
        return {}

    def _handle_kill(self, _args: dict[str, Any], ctx: ActorContext | None) -> dict[str, Any]:
        self._gateway.kill(actor_ctx=ctx)
        return {}

    def _handle_kill_reset(
        self, _args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        self._gateway.reset_kill(actor_ctx=ctx)
        return {}

    def _handle_re_enable(
        self, args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        self._gateway.re_enable(args["tag"], actor_ctx=ctx)
        return {}

    def _handle_set_mode(
        self, args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        mode = cast(Literal["confirm", "dry_run", "supervised"], args["mode"])
        self._gateway.set_mode(mode, actor_ctx=ctx)
        return {}

    def _handle_policy_draft(
        self, args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        return self._policy.draft(args, _policy_actor(ctx))

    def _handle_policy_pin(
        self, args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        return self._policy.pin(args, _policy_actor(ctx))

    def _handle_policy_reload(
        self, args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        return self._policy.reload(args, _policy_actor(ctx), self._gateway)

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

    def _policy_key(self) -> bytes | None:
        """Return the loaded gateway key for policy signing, or None in legacy mode."""
        return None if self._gate is None else self._gate.key

    def _auth_status(self) -> str:
        """Return 'key_missing' when auth is on without a usable key, else 'ok'."""
        if self._gate is not None and not self._gate.key_ok:
            return "key_missing"
        return "ok"

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
            "auth": self._auth_status(),
            "roles_digest": self._roles_digest,
        }
        self._write_atomic(self._root / "_gateway" / "state.json", state)

    def poll_once(self) -> None:
        """Refresh the key, handle the KILL file, process the inbox, tick and write state."""
        self._refresh_key()
        self._handle_kill_file()
        for inbox_file in sorted(self._inbox_dir.glob("*.json")):
            self._process_file(inbox_file)
        self._gateway.tick(int(self._clock() * 1_000_000_000))
        self._write_state()

    def _handle_kill_file(self) -> None:
        """Kill the gateway while the KILL file exists, consuming the file after each kill."""
        if not self._kill_path.exists():
            return
        self._gateway.kill(actor_ctx=_KILL_FILE_CTX)
        try:
            self._kill_path.unlink()
        except OSError:
            self._retire_kill_file()

    def _retire_kill_file(self) -> None:
        """Rename an undeletable KILL file to KILL.handled, ignoring a failure to do so."""
        with contextlib.suppress(OSError):
            os.replace(self._kill_path, self._kill_path.with_name("KILL.handled"))

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

    def _authenticate(self, cmd_data: dict[str, Any]) -> ActorContext | None:
        """Return the verified caller, or None in legacy mode; raise AuthRejected on refusal."""
        if self._gate is None:
            return None
        verdict = self._gate.check(cmd_data, self._gateway)
        if not verdict.ok:
            raise AuthRejected(verdict.reason, verdict.ctx)
        return self._precheck(cmd_data["cmd"], verdict.ctx)

    def _precheck(self, cmd: str, ctx: ActorContext) -> ActorContext:
        """Return ctx when the policy precheck passes for cmd; otherwise raise AuthRejected."""
        reason = self._policy.precheck(cmd, ctx, self._gateway)
        if reason is not None:
            raise AuthRejected(reason, ctx)
        return ctx

    def _reject_unparsed(self, filepath: Path, reason: str) -> None:
        """Move a command that failed the syntax checks to rejected, auditing it in auth mode."""
        if self._gate is not None:
            self._gateway.record_event("auth_reject", _UNKNOWN_CTX, reason)
        self._move_to_rejected(filepath, reason)

    def _audit_rejection(self, exc: AuthRejected, cmd: str) -> None:
        """Record an auth_reject audit event for a command refused after syntax checks."""
        self._gateway.record_event("auth_reject", exc.ctx, exc.reason, value=cmd)

    def _process_file(self, filepath: Path) -> None:
        """Run one inbox command through syntax, authentication, validation and apply."""
        try:
            cmd_data = self._read_command(filepath)
            cmd_id, cmd, args = self._check_envelope(cmd_data)
        except CommandError as exc:
            self._reject_unparsed(filepath, str(exc))
            return
        try:
            ctx = self._authenticate(cmd_data)
            self._validate_args(cmd, args)
            result = self._apply(cmd_data, ctx)
            self._write_result(cmd_id, result)
            filepath.unlink()
        except AuthRejected as exc:
            self._audit_rejection(exc, cmd)
            self._move_to_rejected(filepath, exc.reason)
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
