"""Write Gateway inbox-mailbox service (ADR 011/012, Phase 2 #46).

The only way in is the <root>/_gateway/inbox directory. With auth_required, each command must
carry an HMAC envelope that AuthGate verifies, and policy commands pass a policy precheck.
Without it (legacy mode) the inbox is trusted, so OS permissions must restrict who writes it.
A KILL file in <root>/_gateway kills the gateway in every mode.
Seen nonces persist in _gateway/nonce-cache.json; envelopes issued before start are refused.
The kill latch is _gateway/KILLED, which survives restarts until a signed kill_reset.
Every refusal of a command whose sender is trusted (verified signature, or legacy mode with a
valid id) writes the outbox reply {id, ok: false, error: <code>} besides the rejected/ file, so
the API answers at once. Commands that fail before trust (id invalid or unsafe, unsigned,
bad signature, stale, replayed, key missing) get no reply; their sender keeps its timeout.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from crosscut_gateway import latch_store, policy_pin
from crosscut_gateway.actor import GATEWAY_ACTOR, ActorContext
from crosscut_gateway.audit import verify_chain
from crosscut_gateway.auth_gate import AuthGate, roles_digest
from crosscut_gateway.authz import roles_or_default
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import WriteProposal
from crosscut_gateway.keyfile import default_key_path, key_acl_status, read_key
from crosscut_gateway.param_intent_store import IntentStoreUnreadableError, ParamIntentRecord
from crosscut_gateway.param_ledger import ParamLedger
from crosscut_gateway.policy import PolicyError, proposal_key
from crosscut_gateway.policy_cmds import PolicyCommandError, PolicyCommands, PolicyPaths
from crosscut_gateway.service_params import (
    ParamArgsError,
    parse_propose_params,
    proposal_summary,
)

# Longest command id accepted; it becomes the outbox file name, so it must stay well under
# the file-name limit.
MAX_ID_LENGTH = 128

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
    "propose_params": [],  # list-valued arguments: checked by service_params
    "approve": [("key", "str")],
    "reject": [("key", "str")],
    "re_enable": [("tag", "str")],
    "set_mode": [("mode", "str")],
    "kill": [],
    "kill_reset": [],
    "policy_draft": [("document", "object")],
    "policy_pin": [("digest", "str")],
    "policy_reload": [],
    "list_open_intents": [],
    "open_intents": [],
    "resolve_intent": [("key", "str"), ("actor", "str")],
}


# Refusals of commands whose sender is already authenticated. They get an outbox reply
# {id, ok: false, error: <reason>} so the caller is answered at once instead of timing out.
# Refusals before trust (unsigned, key missing, malformed, bad signature, stale, replayed)
# stay silent: the id is not trusted, so the sender keeps its timeout.
_REPLIED_REASONS = frozenset(
    {
        "self_approval",
        "service_cannot_propose_tuning",
        "stepup_required",
        "predates_start",
        "unknown_cmd",
        "bad_mode",
        "mode_step_too_large",
        "above_cap",
        "author_equals_approver",
        "reload_requires_off_or_advisory",
        "reload_blocked_param_pending",
        "policy_path_not_configured",
        "no_draft",
        "draft_changed",
        "draft_bad_signature",
        "key_missing",
        "key_too_short",
    }
)
_REPLIED_PREFIX = "missing_permission:"


def _is_replied(reason: str) -> bool:
    """Return True when a refusal for an authenticated caller is answered in the outbox."""
    return reason in _REPLIED_REASONS or reason.startswith(_REPLIED_PREFIX)


class CommandError(ValueError):
    """Internal error for rejected commands; ``code`` is the stable code sent in the outbox."""

    def __init__(self, message: str, code: str = "invalid_args") -> None:
        """Store the message and the stable error code."""
        super().__init__(message)
        self.code = code


class AuthRejected(Exception):
    """A command failed authentication or the policy precheck; carries the reason and caller."""

    def __init__(self, reason: str, ctx: ActorContext) -> None:
        """Store the refusal reason and the attributed caller."""
        super().__init__(reason)
        self.reason = reason
        self.ctx = ctx

    @property
    def answerable(self) -> bool:
        """Return True when the sender was authenticated, so the refusal gets an outbox reply."""
        return _is_replied(self.reason)


@dataclass(frozen=True)
class ServiceOptions:
    """Startup switches: whether commands must be authenticated, and the key, roles and policy."""

    auth_required: bool = False
    key_path: Path | None = None
    roles_path: Path | None = None
    policy_path: Path | None = None
    enforce_start_floor: bool = True
    allow_kill_file: bool = True


_DEFAULT_OPTIONS = ServiceOptions()
_UNKNOWN_CTX = ActorContext(actor="unverified:unknown")
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


_PIN_VIEW_KEYS = ("digest", "author", "approver", "approved_at")


def live_policy_view(policy_path: Path | None, key: bytes | None) -> dict[str, Any] | None:
    """Return the verified live policy document with its pin fields, or None.

    None when no policy file is configured, no key is loaded, or the pin does not verify
    (missing, malformed, unsigned, self-approved or not matching the file). The pin
    signature is left out.
    """
    if policy_path is None or key is None:
        return None
    try:
        policy_pin.verify_pin(policy_path, key)
        document = json.loads(policy_path.read_text(encoding="utf-8-sig"))
        pin = json.loads(policy_pin.pin_path_for(policy_path).read_text(encoding="utf-8"))
    except (PolicyError, OSError, ValueError, RecursionError):
        return None
    if not isinstance(document, dict):
        return None
    return {"document": document, "pin": {name: pin[name] for name in _PIN_VIEW_KEYS}}


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
        self._start_ns = int(clock() * 1_000_000_000)
        self._last_nonce_snapshot: dict[str, Any] | None = None
        self._inbox_dir = root / "_gateway" / "inbox"
        self._outbox_dir = root / "_gateway" / "outbox"
        self._rejected_dir = root / "_gateway" / "rejected"
        self._gateway_dir = root / "_gateway"
        self._kill_path = self._gateway_dir / "KILL"
        self._allow_kill_file = options.allow_kill_file
        self._key_path = options.key_path or default_key_path(root)
        self._gate: AuthGate | None = None
        self._roles_digest = ""
        self._policy_file = options.policy_path
        self._policy = PolicyCommands(
            PolicyPaths(options.policy_path, root / "_gateway" / "policy-draft.json"),
            key_source=self._policy_key,
            clock=clock,
        )
        for directory in (self._inbox_dir, self._outbox_dir, self._rejected_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._setup_auth(options)
        self._restore_kill_latch()
        self._ledger = ParamLedger()
        self._ledger.update(self._gateway.audit_records())  # rebuilt from the whole audit log

    def _restore_kill_latch(self) -> None:
        """Re-engage the kill after a restart while the persisted KILLED latch is present."""
        if not latch_store.kill_latch_present(self._gateway_dir):
            return
        self._gateway.kill(actor_ctx=ActorContext(actor="kill_latch", source_ip="restart"))
        self._gateway.record_event("kill_latch_restored", GATEWAY_ACTOR, "restart")

    def _setup_auth(self, options: ServiceOptions) -> None:
        """Load roles and the gate when auth is required; legacy mode keeps no gate."""
        if not options.auth_required:
            return
        roles, fallback_reason = roles_or_default(options.roles_path)
        floor = self._start_ns if options.enforce_start_floor else None
        gate = AuthGate(roles, self._clock, floor)
        self._gate = gate
        self._restore_nonce_cache(gate)
        self._roles_digest = roles_digest(roles)
        self._refresh_key()
        self._gateway.record_event(
            "roles_loaded", GATEWAY_ACTOR, fallback_reason or "ok", value=self._roles_digest
        )

    def _restore_nonce_cache(self, gate: AuthGate) -> None:
        """Reload the persisted nonce cache so a replay across a restart is still refused."""
        data = latch_store.read_json_object(self._gateway_dir / latch_store.NONCE_NAME)
        if data is not None:
            gate.restore_nonces(data)

    def _save_nonces(self) -> None:
        """Save the nonce cache when it changed since the last save; audit a failed write."""
        if self._gate is None:
            return
        snapshot = self._gate.nonce_snapshot()
        if snapshot == self._last_nonce_snapshot:
            return
        try:
            latch_store.write_json_atomic(self._gateway_dir / latch_store.NONCE_NAME, snapshot)
        except OSError:
            self._gateway.record_event("service_error", GATEWAY_ACTOR, "nonce_save_failed")
            return
        self._last_nonce_snapshot = snapshot

    def _refresh_key(self) -> None:
        """Reload the HMAC key from disk so a key rotation takes effect on the next poll."""
        if self._gate is not None:
            self._gate.set_key(read_key(self._key_path))

    def _move_to_rejected(self, filepath: Path, reason: str) -> None:
        """Move filepath (file or directory) into rejected/ beside a reason file, never raising."""
        rejected_path = self._rejected_dir / filepath.name
        with contextlib.suppress(OSError, ValueError):
            reason_path = self._rejected_dir / (filepath.name + ".reason.txt")
            reason_path.write_text(reason, encoding="utf-8")
        try:
            os.replace(filepath, rejected_path)
        except OSError:
            self._drop_source(filepath, rejected_path)

    @staticmethod
    def _drop_source(source: Path, target: Path) -> None:
        """Fallback after a failed move: copy a file's bytes to target, or remove a directory."""
        with contextlib.suppress(OSError):
            if source.is_dir():
                shutil.rmtree(source, ignore_errors=True)
                return
            target.write_bytes(source.read_bytes())
        with contextlib.suppress(OSError):
            source.unlink()

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
        try:
            finite = math.isfinite(float(val))
        except OverflowError:
            finite = False
        if not finite:
            raise CommandError(f"{cmd}: {name} out of range")

    def _assert_is_int(self, cmd: str, name: str, val: Any) -> None:
        if isinstance(val, bool) or not isinstance(val, int):
            raise CommandError(f"{cmd}: {name} must be an int")

    def _assert_is_object(self, cmd: str, name: str, val: Any) -> None:
        if not isinstance(val, dict):
            raise CommandError(f"{cmd}: {name} must be an object")

    def _validate_args(self, cmd: str, args: dict[str, Any]) -> None:
        if cmd not in VALIDATION_SCHEMA:
            raise CommandError(f"unknown cmd: {cmd}", code="unknown_cmd")
        for name, kind in VALIDATION_SCHEMA[cmd]:
            if name not in args:
                raise CommandError(f"{cmd}: missing {name}")
            self._check_arg(cmd, name, args[name], kind)
        if cmd == "propose_params":
            self._validate_params_args(args)

    @staticmethod
    def _validate_params_args(args: dict[str, Any]) -> None:
        """Strictly validate propose_params arguments; a bad one is an invalid_args reply."""
        try:
            parse_propose_params(args)
        except ParamArgsError as exc:
            raise CommandError(str(exc)) from exc

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
            "propose_params": self._handle_propose_params,
            "approve": self._handle_approve,
            "reject": self._handle_reject,
            "kill": self._handle_kill,
            "kill_reset": self._handle_kill_reset,
            "re_enable": self._handle_re_enable,
            "set_mode": self._handle_set_mode,
            "policy_draft": self._handle_policy_draft,
            "policy_pin": self._handle_policy_pin,
            "policy_reload": self._handle_policy_reload,
            "list_open_intents": self._handle_list_open_intents,
            "open_intents": self._handle_list_open_intents,
            "resolve_intent": self._handle_resolve_intent,
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

    def _handle_propose_params(
        self, args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        proposal = parse_propose_params(args)
        return asdict(self._gateway.propose_params(proposal, actor_ctx=ctx))

    def _handle_approve(
        self, args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        self._handle_kill_file()  # a KILL file that appeared since the poll started wins
        return asdict(self._gateway.approve(args["key"], actor_ctx=ctx))

    def _handle_reject(
        self, args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        self._gateway.reject(args["key"], actor_ctx=ctx)
        return {}

    def _handle_kill(self, _args: dict[str, Any], ctx: ActorContext | None) -> dict[str, Any]:
        self._gateway.kill(actor_ctx=ctx)
        self._latch_kill(ctx)
        return {}

    def _latch_kill(self, ctx: ActorContext | None) -> None:
        """Persist the kill latch so a restart stays killed; a failed write keeps the kill."""
        actor = ctx.actor if ctx else "legacy"
        at_utc = datetime.fromtimestamp(self._clock(), tz=UTC).isoformat()
        try:
            latch_store.write_kill_latch(self._gateway_dir, actor, at_utc)
        except OSError:
            self._gateway.record_event("service_error", GATEWAY_ACTOR, "kill_latch_write_failed")

    def _handle_kill_reset(
        self, _args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        self._gateway.reset_kill(actor_ctx=ctx)
        self._clear_latch()
        return {}

    def _clear_latch(self) -> None:
        """Remove the kill latch after a reset; refuse only when the latch file survives."""
        try:
            latch_store.clear_kill_latch(self._gateway_dir)
        except OSError as exc:
            self._gateway.record_event("service_error", GATEWAY_ACTOR, "kill_latch_clear_failed")
            if latch_store.kill_latch_present(self._gateway_dir):
                raise CommandError("kill latch could not be cleared") from exc

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

    def _handle_list_open_intents(
        self, _args: dict[str, Any], _ctx: ActorContext | None
    ) -> dict[str, Any]:
        """Return all open parameter write intents, or report the store as damaged."""
        # In plain words:
        # A damaged intent file blocks write operations, but listing commands must never
        # crash with an unhandled exception. We report the damaged state explicitly.
        try:
            records = self._gateway.open_intents()
        except IntentStoreUnreadableError:
            return {
                "store_state": "damaged",
                "state": "damaged",
                "damaged": True,
                "intents": [],
            }
        intents = [self._serialize_open_intent(record) for record in records]
        return {
            "store_state": "ok",
            "state": "ok",
            "damaged": False,
            "intents": intents,
        }

    def _serialize_open_intent(self, record: ParamIntentRecord) -> dict[str, Any]:
        """Convert one open intent record into a summary dict with live values."""
        items: list[dict[str, Any]] = []
        for item in record.items:
            live = self._read_item_current(item.target)
            items.append({
                "target": item.target,
                "from_value": item.from_value,
                "to_value": item.to_value,
                "current_value": live,
            })
        data = record.to_dict()
        data["items"] = items
        return data

    def _read_item_current(self, target: str) -> float | None:
        """Read live value for target if plant is present; None on error."""
        plant = getattr(self._gateway, "_plant", None)
        if plant is None:
            return None
        try:
            val = plant.read_param(target)
            return float(val)
        except Exception:  # noqa: BLE001
            return None

    def _handle_resolve_intent(
        self, args: dict[str, Any], ctx: ActorContext | None
    ) -> dict[str, Any]:
        """Resolve an open parameter write intent by reading live plant values."""
        key = args["key"]
        actor = args["actor"]
        decision = self._gateway.resolve_intent(key, actor, actor_ctx=ctx)
        return asdict(decision)

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

    def _get_pending_params(self) -> list[dict[str, Any]]:
        """Summaries of the queued PID parameter sets (kind ``pid_param``)."""
        return [proposal_summary(p.key, p.proposal) for p in self._gateway.pending_params()]

    def _get_audit_view(self) -> tuple[list[Any], bool]:
        records = self._gateway.audit_records()
        self._ledger.update(records)
        return records[-200:], verify_chain(records, self._policy_key())

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
            "alarms": self._gateway.alarms(),
            "pending": self._get_pending_entries(),
            "pending_params": self._get_pending_params(),
            "audit_tail": audit_tail,
            "applied_params": self._ledger.applied,
            "param_events": list(self._ledger.events),
            "chain_ok": chain_ok,
            "auth": self._auth_status(),
            "roles_digest": self._roles_digest,
            "key_acl": key_acl_status(self._key_path),
            "policy": live_policy_view(self._policy_file, self._policy_key()),
        }
        self._write_atomic(self._root / "_gateway" / "state.json", state)

    def poll_once(self) -> None:
        """Refresh the key, handle the KILL file, process the inbox, tick and write state."""
        self._refresh_key()
        self._handle_kill_file()
        for inbox_file in self._inbox_files():
            self._guarded_process(inbox_file)
        self._save_nonces()
        self._gateway.tick(int(self._clock() * 1_000_000_000))
        self._write_state()

    def _inbox_files(self) -> list[Path]:
        """Return the inbox's JSON entries in name order, or [] when the inbox cannot be listed."""
        try:
            return sorted(self._inbox_dir.glob("*.json"))
        except OSError:
            return []

    def _guarded_process(self, filepath: Path) -> None:
        """Process one inbox file; any failure quarantines that file and the cycle goes on."""
        try:
            self._process_file(filepath)
        except Exception as exc:
            self._quarantine(filepath, exc)

    def _quarantine(self, filepath: Path, exc: Exception) -> None:
        """Move a file that broke processing to rejected/ and audit it; skip vanished files."""
        if isinstance(exc, FileNotFoundError):
            return
        self._move_to_rejected(filepath, exc.__class__.__name__)
        self.record_service_error(exc)

    def record_service_error(self, exc: BaseException) -> None:
        """Audit a failed service step by exception class name only, never its message."""
        with contextlib.suppress(Exception):
            self._gateway.record_event("service_error", GATEWAY_ACTOR, exc.__class__.__name__)

    def _handle_kill_file(self) -> None:
        """Kill the gateway while the KILL file exists, retiring the file after each kill.

        With the KILL file trigger switched off (``--no-kill-file``) the file is ignored.
        """
        if not self._allow_kill_file or not self._kill_path.exists():
            return
        self._gateway.kill(actor_ctx=_KILL_FILE_CTX)
        self._latch_kill(_KILL_FILE_CTX)
        self._retire_kill_file()

    def _retire_kill_file(self) -> None:
        """Rename the handled KILL file to KILL.handled-<ts>, falling back to unlink."""
        target = self._kill_path.with_name(f"KILL.handled-{int(self._clock())}")
        try:
            os.replace(self._kill_path, target)
        except OSError:
            with contextlib.suppress(OSError):
                self._kill_path.unlink()

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
        if len(cmd_id) > MAX_ID_LENGTH or not all(
            char.isalnum() or char in "._-" for char in cmd_id
        ):
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
        return self._precheck(cmd_data["cmd"], verdict.ctx, cmd_data["args"])

    def _precheck(self, cmd: str, ctx: ActorContext, args: Any) -> ActorContext:
        """Return ctx when the policy precheck passes for cmd; otherwise raise AuthRejected."""
        reason = self._policy.precheck(cmd, ctx, self._gateway, args)
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
            self._answer(filepath, cmd_id, result)
        except AuthRejected as exc:
            self._audit_rejection(exc, cmd)
            self._move_to_rejected(filepath, exc.reason)
            if exc.answerable:
                self._answer_refusal(cmd_id, exc.reason)
        except CommandError as exc:
            self._move_to_rejected(filepath, str(exc))
            self._answer_refusal(cmd_id, exc.code)

    def _answer_refusal(self, cmd_id: str, code: str) -> None:
        """Write the outbox reply of a refused command; a failed write is audited, not raised."""
        result = {"ok": False, "result": None, "error": code}
        try:
            self._write_result(cmd_id, result)
        except OSError:
            self._gateway.record_event(
                "result_write_failed", GATEWAY_ACTOR, "refused", value=cmd_id[:64]
            )

    def _answer(self, filepath: Path, cmd_id: str, result: dict[str, Any]) -> None:
        """Write the outbox answer of an applied command; a failed write is audited, not hidden."""
        try:
            self._write_result(cmd_id, result)
        except OSError:
            self._gateway.record_event(
                "result_write_failed", GATEWAY_ACTOR, "applied", value=cmd_id[:64]
            )
            self._move_to_rejected(filepath, "result_write_failed")
            return
        filepath.unlink()


def serve(service: GatewayService, interval_s: float, stop_event: threading.Event) -> None:
    """Run poll cycles until *stop_event* is set; a failing cycle is reported and skipped."""
    while not stop_event.is_set():
        try:
            service.poll_once()
        except Exception as exc:
            service.record_service_error(exc)
        stop_event.wait(interval_s)
