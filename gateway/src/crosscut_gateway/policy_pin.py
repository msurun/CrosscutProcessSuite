"""Signed digest pin for write policy files, replacing the .sha256 sidecar (Phase 2, #46).

The pin file records the policy file's SHA-256, two distinct signers and an HMAC-SHA256
signature over the pin. Verification fails closed on any missing, malformed, unsigned,
self-approved or digest-mismatched pin.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from crosscut_gateway import policy_file
from crosscut_gateway.actor import normalize_actor
from crosscut_gateway.envelope import MIN_KEY_BYTES, EnvelopeError, sign_envelope
from crosscut_gateway.interfaces import WritePolicy
from crosscut_gateway.policy import PolicyError

PIN_FILE_NAME = "policy.pin.json"
_PIN_KEYS = frozenset({"digest", "author", "approver", "approved_at", "sig"})


class PinError(PolicyError):
    """Raised when a policy pin cannot be created, read, or verified."""


@dataclass(frozen=True)
class PinSigners:
    """The two distinct people who authored and approved a policy file."""

    author: str
    approver: str


@dataclass(frozen=True)
class PinRequest:
    """A policy document to install as the live policy, with the pin that approves it."""

    policy_path: Path
    document: dict[str, Any]
    key: bytes
    signers: PinSigners
    now: datetime


def pin_path_for(policy_path: Path) -> Path:
    """Return the pin file path that sits beside ``policy_path``."""
    return policy_path.parent / PIN_FILE_NAME


def file_digest(policy_path: Path) -> str:
    """Return the SHA-256 hex digest of the raw bytes of ``policy_path``."""
    try:
        return hashlib.sha256(policy_path.read_bytes()).hexdigest()
    except OSError as err:
        raise PinError(f"Cannot read policy file {policy_path}: {err}") from err


def _require_key(key: bytes) -> None:
    """Refuse HMAC keys shorter than the envelope minimum."""
    if len(key) < MIN_KEY_BYTES:
        raise PinError("key_too_short")


def _check_signers(signers: PinSigners) -> None:
    """Refuse empty signer names and a signer approving their own authorship, ignoring case."""
    author = normalize_actor(signers.author)
    approver = normalize_actor(signers.approver)
    if not author or not approver:
        raise PinError("signer_empty")
    if author == approver:
        raise PinError("author_equals_approver")


def _signature_for(body: dict[str, Any], key: bytes) -> str:
    """Return the HMAC-SHA256 hex signature of ``body`` via the shared envelope signer."""
    try:
        return str(sign_envelope(body, key)["sig"])
    except EnvelopeError as err:
        raise PinError(f"signing failed: {err}") from err


def _digests_equal(left: str, right: str) -> bool:
    """Compare two digests in constant time; untrusted text is encoded with replacement."""
    return hmac.compare_digest(left.encode("utf-8", "replace"), right.encode("utf-8", "replace"))


def _write_bytes(path: Path, payload: bytes) -> None:
    """Write ``payload`` to ``path`` through a sibling temp file and an atomic replace."""
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".write-", suffix=".tmp")
    except OSError as err:
        raise PinError(f"Cannot write {path}: {err}") from err
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    except OSError as err:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise PinError(f"Cannot write {path}: {err}") from err


def _write_atomic(path: Path, doc: dict[str, str]) -> None:
    """Write the pin document ``doc`` to ``path`` as UTF-8 JSON, atomically."""
    _write_bytes(path, json.dumps(doc, indent=2).encode("utf-8"))


def create_pin(
    policy_path: Path,
    key: bytes,
    signers: PinSigners,
    now: datetime,
) -> dict[str, str]:
    """Sign and atomically write the pin for ``policy_path``, returning the pin document.

    Raises PinError for a short key, empty or identical signers, or an unwritable pin.
    """
    _require_key(key)
    _check_signers(signers)
    body = {
        "digest": file_digest(policy_path),
        "author": signers.author,
        "approver": signers.approver,
        "approved_at": now.isoformat(),
    }
    doc = {**body, "sig": _signature_for(body, key)}
    _write_atomic(pin_path_for(policy_path), doc)
    return doc


def _read_pin(pin_path: Path) -> dict[str, Any]:
    """Read the pin file and parse it as a JSON object."""
    try:
        text = pin_path.read_text(encoding="utf-8")
    except OSError as err:
        raise PinError("pin_missing") from err
    except UnicodeDecodeError as err:
        raise PinError("pin_malformed") from err
    try:
        doc = json.loads(text)
    except (ValueError, RecursionError) as err:
        raise PinError("pin_malformed") from err
    if not isinstance(doc, dict):
        raise PinError("pin_malformed")
    return doc


def _pin_fields(doc: dict[str, Any]) -> dict[str, str]:
    """Require exactly the pin keys, each holding a non-empty string."""
    if set(doc) != _PIN_KEYS:
        raise PinError("pin_malformed")
    fields: dict[str, str] = {}
    for name, value in doc.items():
        if not isinstance(value, str) or not value:
            raise PinError("pin_malformed")
        fields[name] = value
    return fields


def _signature_is_valid(fields: dict[str, str], key: bytes) -> bool:
    """Return True when the pin's ``sig`` matches the signature of the rest of the pin."""
    body = {name: value for name, value in fields.items() if name != "sig"}
    return _digests_equal(_signature_for(body, key), fields["sig"])


def verify_pin(policy_path: Path, key: bytes) -> str:
    """Verify the pin beside ``policy_path`` and return the pinned digest.

    Checks run in order: key length, file shape, signature, signer separation, digest.
    Raises PinError with a short code (pin_missing, pin_malformed, bad_signature,
    author_equals_approver, digest_mismatch, key_too_short) on any failure.
    """
    _require_key(key)
    fields = _pin_fields(_read_pin(pin_path_for(policy_path)))
    if not _signature_is_valid(fields, key):
        raise PinError("bad_signature")
    if normalize_actor(fields["author"]) == normalize_actor(fields["approver"]):
        raise PinError("author_equals_approver")
    if not _digests_equal(fields["digest"], file_digest(policy_path)):
        raise PinError("digest_mismatch")
    return fields["digest"]


def load_pinned_policy(
    policy_path: Path,
    key: bytes,
) -> tuple[dict[str, WritePolicy], str, str]:
    """Verify the pin, then load the policy file; return (targets, mode, pinned digest).

    The file digest is re-checked after loading so a file replaced between verification
    and parsing is rejected rather than loaded.
    """
    pinned_digest = verify_pin(policy_path, key)
    targets, mode, _ = policy_file.load_policy_file(policy_path, None)
    if not _digests_equal(pinned_digest, file_digest(policy_path)):
        raise PinError("digest_mismatch")
    return targets, mode, pinned_digest


def _policy_bytes(document: dict[str, Any]) -> bytes:
    """Return the policy document as the UTF-8 JSON written to the policy file."""
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _read_optional(path: Path) -> bytes | None:
    """Return the bytes of ``path``, or None when the file does not exist."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as err:
        raise PinError(f"Cannot read {path}: {err}") from err


def _snapshot(policy_path: Path) -> dict[Path, bytes | None]:
    """Record the current bytes of the policy file and its pin; None where absent."""
    pin_path = pin_path_for(policy_path)
    return {policy_path: _read_optional(policy_path), pin_path: _read_optional(pin_path)}


def _restore_one(path: Path, old: bytes | None) -> None:
    """Return ``path`` to its ``old`` bytes, or remove it when ``old`` is None; best effort."""
    with contextlib.suppress(OSError, PinError):
        if _read_optional(path) == old:
            return
        if old is None:
            path.unlink(missing_ok=True)
        else:
            _write_bytes(path, old)


def _restore(snapshot: dict[Path, bytes | None]) -> None:
    """Restore every file in ``snapshot`` to its recorded bytes."""
    for path, old in snapshot.items():
        _restore_one(path, old)


def install_policy_with_pin(request: PinRequest) -> dict[str, str]:
    """Install the policy document and sign its pin, restoring the previous state on failure.

    The key and signer checks run before any write, so a refused request touches nothing.
    Raises PinError with install_failed after restoring the previous policy and pin bytes.
    """
    _require_key(request.key)
    _check_signers(request.signers)
    snapshot = _snapshot(request.policy_path)
    try:
        _write_bytes(request.policy_path, _policy_bytes(request.document))
        return create_pin(request.policy_path, request.key, request.signers, request.now)
    except PinError as err:
        _restore(snapshot)
        raise PinError("install_failed") from err
