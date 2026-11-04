"""Signing utilities for the Crosscut API.

These helpers produce signed command envelopes without pulling in the
gateway package, allowing the API to remain independent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from crosscut_api.auth.actor import ActorContext

# Minimum size for a secret HMAC key (bytes)
MIN_KEY_BYTES = 32


def canonical_bytes(data: dict[str, Any]) -> bytes:
    """Return deterministic UTF‑8 bytes for a JSON object.

    The JSON representation uses lexicographically sorted keys, compact
    separators (',' and ':'), and leaves Unicode characters unescaped.
    """
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign_envelope(env_without_sig: dict[str, Any], key: bytes) -> dict[str, Any]:
    """Return a shallow copy of ``env_without_sig`` with an HMAC‑SHA256 signature.

    Raises:
        ValueError: If ``key`` is shorter than :data:`MIN_KEY_BYTES` or
            the envelope already contains a ``sig`` field.
    """
    if len(key) < MIN_KEY_BYTES:
        raise ValueError(f"Key must be at least {MIN_KEY_BYTES} bytes long")
    if "sig" in env_without_sig:
        raise ValueError("Envelope already contains a signature")
    mac = hmac.new(key, canonical_bytes(env_without_sig), hashlib.sha256)
    signed = dict(env_without_sig)
    signed["sig"] = mac.hexdigest()
    return signed


def build_auth_block(actor: ActorContext, now_ns: int, nonce: str) -> dict[str, Any]:
    """Create the ``auth`` section of an envelope from an ``ActorContext``.

    The block contains the actor identifier, role list, session token,
    source IP, issuance timestamp, a random nonce, and any step‑up flag.
    """
    return {
        "actor": actor.actor,
        "roles": list(actor.roles),
        "session": actor.session,
        "source_ip": actor.source_ip,
        "issued_at_ns": now_ns,
        "nonce": nonce,
        "stepup": actor.stepup,
    }


@dataclass(frozen=True)
class Signer:
    """Container for an actor and the secret key used to sign envelopes."""

    actor: ActorContext
    key: bytes


def make_signed_command(
    cmd_id: str,
    cmd: str,
    args: dict[str, Any],
    signer: Signer,
) -> dict[str, Any]:
    """Create a signed command envelope for ``cmd``.

    The function builds the envelope, adds an authentication block,
    and signs it with the signer's secret key.
    """
    auth = build_auth_block(
        signer.actor,
        time.time_ns(),
        secrets.token_hex(16),  # 32‑character hexadecimal nonce
    )
    envelope = {"id": cmd_id, "cmd": cmd, "args": args, "auth": auth}
    return sign_envelope(envelope, signer.key)
