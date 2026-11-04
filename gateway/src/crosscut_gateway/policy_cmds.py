"""Two-person policy commands for the write gateway: draft, pin and reload.

One actor drafts a policy document and a different actor pins it, signing the pin with
the gateway key. Reload swaps in only a verified pin, and only while the gateway is off
or advisory.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from crosscut_gateway import policy_file, policy_pin
from crosscut_gateway.actor import ActorContext
from crosscut_gateway.engine import Mode, WriteGateway
from crosscut_gateway.envelope import MIN_KEY_BYTES
from crosscut_gateway.policy import PolicyError
from crosscut_gateway.policy_pin import PinSigners

_RELOAD_MODES = ("off", "advisory")


class PolicyCommandError(ValueError):
    """Raised when a policy command is refused; the message carries the reason code."""


@dataclass(frozen=True)
class PolicyPaths:
    """Locations used by the policy commands; ``policy_path`` is None when unconfigured."""

    policy_path: Path | None
    draft_path: Path


@dataclass(frozen=True)
class _Draft:
    """A saved, schema-valid policy draft and the actor who wrote it."""

    document: dict[str, Any]
    author: str


def _write_atomic(path: Path, text: str) -> None:
    """Write ``text`` as UTF-8 through a sibling temp file and an atomic replace."""
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".policy-", suffix=".tmp")
    except OSError as err:
        raise PolicyCommandError(f"cannot write {path}: {err}") from err
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
        os.replace(tmp_name, path)
    except OSError as err:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise PolicyCommandError(f"cannot write {path}: {err}") from err


def _dump_json(data: dict[str, Any]) -> str:
    """Return ``data`` as indented, non-ASCII-preserving JSON with a trailing newline."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


class PolicyCommands:
    """Handle the policy_draft, policy_pin and policy_reload gateway commands."""

    def __init__(
        self,
        paths: PolicyPaths,
        key_source: Callable[[], bytes | None],
        clock: Callable[[], float],
    ) -> None:
        """Store the file locations, the signing key source and the UTC clock."""
        self._paths = paths
        self._key_source = key_source
        self._clock = clock

    def precheck(self, cmd: str, ctx: ActorContext, gateway: WriteGateway) -> str | None:
        """Return a refusal reason for ``cmd``, or None when it may proceed."""
        if cmd == "policy_pin":
            return self._pin_refusal(ctx)
        if cmd == "policy_reload":
            return self._reload_refusal(gateway)
        return None

    def draft(self, args: dict[str, Any], ctx: ActorContext) -> dict[str, Any]:
        """Validate and save a draft for a second actor to pin; the live file is untouched."""
        document = args.get("document")
        if not isinstance(document, dict):
            raise PolicyCommandError("document must be an object")
        try:
            policy_file.validate_document(document)
        except PolicyError as err:
            raise PolicyCommandError(str(err)) from err
        saved = {"document": document, "author": ctx.actor, "saved_at": self._now().isoformat()}
        _write_atomic(self._paths.draft_path, _dump_json(saved))
        return {"digest": policy_file.policy_digest(document), "author": ctx.actor}

    def pin(self, args: dict[str, Any], ctx: ActorContext) -> dict[str, Any]:
        """Write the drafted policy as the live file and sign its pin as ``ctx.actor``."""
        del args
        policy_path = self._require_policy_path()
        draft = self._require_draft(ctx)
        key = self._require_key()
        _write_atomic(policy_path, _dump_json(draft.document))
        try:
            pin_doc = policy_pin.create_pin(
                policy_path,
                key,
                PinSigners(author=draft.author, approver=ctx.actor),
                now=self._now(),
            )
        except PolicyError as err:
            raise PolicyCommandError(str(err)) from err
        return {"digest": pin_doc["digest"], "author": draft.author, "approver": ctx.actor}

    def reload(
        self,
        args: dict[str, Any],
        ctx: ActorContext,
        gateway: WriteGateway,
    ) -> dict[str, Any]:
        """Verify the pinned policy file and swap it into ``gateway``."""
        del args
        policy_path = self._require_policy_path()
        key = self._require_key()
        try:
            targets, mode, digest = policy_pin.load_pinned_policy(policy_path, key)
        except PolicyError as err:
            raise PolicyCommandError(str(err)) from err
        try:
            # The schema restricts the policy file's mode to the Mode literals.
            gateway.swap_policies(targets, cast(Mode, mode), digest=digest, actor_ctx=ctx)
        except ValueError as err:
            raise PolicyCommandError(str(err)) from err
        return {"digest": digest}

    def _now(self) -> datetime:
        """Return the current UTC time from the injected clock."""
        return datetime.fromtimestamp(self._clock(), tz=UTC)

    def _require_policy_path(self) -> Path:
        """Return the configured live policy path or refuse as not configured."""
        if self._paths.policy_path is None:
            raise PolicyCommandError("policy_path_not_configured")
        return self._paths.policy_path

    def _require_key(self) -> bytes:
        """Return the signing key, refusing a missing or envelope-too-short key."""
        key = self._key_source()
        if key is None:
            raise PolicyCommandError("key_missing")
        if len(key) < MIN_KEY_BYTES:
            raise PolicyCommandError("key_too_short")
        return key

    def _read_draft(self) -> _Draft | None:
        """Return the saved draft, or None when it is missing, unreadable or schema-invalid."""
        try:
            raw = json.loads(self._paths.draft_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            return None
        if not isinstance(raw, dict):
            return None
        document, author = raw.get("document"), raw.get("author")
        if not isinstance(document, dict) or not isinstance(author, str) or not author.strip():
            return None
        try:
            policy_file.validate_document(document)
        except PolicyError:
            return None
        return _Draft(document=document, author=author)

    def _require_draft(self, ctx: ActorContext) -> _Draft:
        """Return the valid draft, refusing a missing draft or one authored by ``ctx.actor``."""
        draft = self._read_draft()
        if draft is None:
            raise PolicyCommandError("no_draft")
        if draft.author == ctx.actor:
            raise PolicyCommandError("author_equals_approver")
        return draft

    def _pin_refusal(self, ctx: ActorContext) -> str | None:
        """Return the refusal reason for policy_pin, or None."""
        try:
            self._require_policy_path()
            self._require_draft(ctx)
        except PolicyCommandError as err:
            return str(err)
        return None

    def _reload_refusal(self, gateway: WriteGateway) -> str | None:
        """Return the refusal reason for policy_reload, or None."""
        if self._paths.policy_path is None:
            return "policy_path_not_configured"
        if gateway.mode not in _RELOAD_MODES:
            return "reload_requires_off_or_advisory"
        return None
