"""Envelope handling utilities.

Provides signing, verification, and replay protection for policy envelopes.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import time
from collections.abc import Callable, Mapping
from typing import Any

from crosscut_gateway.policy_file import canonical_bytes

MIN_KEY_BYTES = 32
ENVELOPE_VERSION = 2  # Informational version identifier

_NONCE_HEX_LEN = 32
_SESSION_HEX_LEN = 16
_NS_PER_SECOND = 1_000_000_000


class EnvelopeError(ValueError):
    """Raised for problems encountered while creating or signing an envelope."""


def sign_envelope(env_without_sig: dict[str, Any], key: bytes) -> dict[str, Any]:
    """Return a signed copy of ``env_without_sig``.

    Raises :class:`EnvelopeError` if ``key`` is shorter than :data:`MIN_KEY_BYTES`
    or if the envelope already contains a ``sig`` field.  The signature is a
    lower-case hexadecimal HMAC-SHA256 of the canonical JSON representation of
    the envelope (excluding the signature).

    Parameters
    ----------
    env_without_sig:
        The envelope dictionary that must not contain a ``sig`` entry.
    key:
        Secret key for HMAC; must be at least :data:`MIN_KEY_BYTES` bytes long.

    Returns
    -------
    dict[str, Any]
        A shallow copy of ``env_without_sig`` with an added ``sig`` field.
    """
    if len(key) < MIN_KEY_BYTES:
        raise EnvelopeError(
            f"Key must be at least {MIN_KEY_BYTES} bytes long, got {len(key)}"
        )
    if "sig" in env_without_sig:
        raise EnvelopeError("Envelope already contains a signature")
    mac = hmac.new(key, canonical_bytes(env_without_sig), hashlib.sha256)
    signed = dict(env_without_sig)
    signed["sig"] = mac.hexdigest()
    return signed


def _newest(entries: dict[str, float], limit: int) -> dict[str, float]:
    """Return at most ``limit`` entries, the most recent timestamps first."""
    ordered = sorted(entries.items(), key=lambda item: item[1], reverse=True)
    return dict(ordered[: max(limit, 0)])


def _finite_timestamp(value: object) -> float | None:
    """Return ``value`` as a finite float when it is a real number, otherwise ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


class NonceCache:
    """Cache to detect replayed nonces and envelope identifiers.

    The cache stores nonce values and envelope identifiers for a configurable
    time window.  Entries older than ``window_s`` seconds are removed each time
    :meth:`check_and_add` is called.

    Parameters
    ----------
    window_s:
        Duration, in seconds, for which nonces and IDs are kept.
    clock:
        Callable returning the current monotonic time; defaults to
        :func:`time.monotonic`.
    """

    def __init__(self, window_s: float = 120, clock: Callable[[], float] = time.monotonic) -> None:
        """Initialize the cache with a time window and clock source."""
        self._window_s = window_s
        self._clock = clock
        self._nonce_to_ts: dict[str, float] = {}
        self._id_to_ts: dict[str, float] = {}

    def _prune_expired(self) -> None:
        """Remove entries older than the configured window."""
        now = self._clock()
        for nonce, ts in list(self._nonce_to_ts.items()):
            if now - ts >= self._window_s:
                del self._nonce_to_ts[nonce]
        for env_id, ts in list(self._id_to_ts.items()):
            if now - ts >= self._window_s:
                del self._id_to_ts[env_id]

    def check_and_add(self, nonce: str, env_id: str) -> str | None:
        """Check for replay, add entries if fresh.

        Returns ``None`` when both nonce and identifier are fresh and records them.
        Returns ``'replayed_nonce'`` if ``nonce`` is already known.
        Returns ``'replayed_id'`` if ``env_id`` is already known.

        If a replay is detected, nothing is recorded.
        """
        self._prune_expired()
        if nonce in self._nonce_to_ts:
            return "replayed_nonce"
        if env_id in self._id_to_ts:
            return "replayed_id"
        now = self._clock()
        self._nonce_to_ts[nonce] = now
        self._id_to_ts[env_id] = now
        return None

    def __len__(self) -> int:
        """Return the total number of stored nonces plus identifiers."""
        return len(self._nonce_to_ts) + len(self._id_to_ts)

    def snapshot(self, limit: int = 500) -> dict[str, dict[str, float]]:
        """Return the newest ``limit`` nonces and ids of each kind, after pruning expired ones."""
        self._prune_expired()
        return {
            "nonces": _newest(self._nonce_to_ts, limit),
            "ids": _newest(self._id_to_ts, limit),
        }

    def restore(self, data: object) -> None:
        """Load entries from a snapshot, keeping only those inside the window; never raises."""
        now = self._clock()
        self._nonce_to_ts.update(self._window_entries(data, "nonces", now))
        self._id_to_ts.update(self._window_entries(data, "ids", now))

    def _window_entries(self, data: object, field: str, now: float) -> dict[str, float]:
        """Return the valid str->timestamp entries of ``field`` that lie within the window."""
        if not isinstance(data, Mapping):
            return {}
        raw = data.get(field)
        if not isinstance(raw, Mapping):
            return {}
        kept: dict[str, float] = {}
        for key, value in raw.items():
            ts = _finite_timestamp(value)
            if isinstance(key, str) and ts is not None:
                if now - self._window_s < ts <= now + self._window_s:
                    kept[key] = ts
        return kept


def _is_nonempty_str(value: Any) -> bool:
    """Return ``True`` if ``value`` is a non-empty string."""
    return isinstance(value, str) and bool(value)


def _is_hex_string(value: Any, length: int, lowercase: bool = False) -> bool:
    """Return ``True`` if ``value`` is a hex string of exactly ``length`` characters.

    If ``lowercase`` is ``True``, characters must be in ``0-9a-f``.
    """
    if not isinstance(value, str) or len(value) != length:
        return False
    if lowercase:
        allowed = "0123456789abcdef"
        return all(ch in allowed for ch in value)
    return all(ch in "0123456789abcdefABCDEF" for ch in value)


def _is_roles_list(value: Any) -> bool:
    """Return ``True`` if ``value`` is a list of strings."""
    if not isinstance(value, list):
        return False
    return all(isinstance(item, str) for item in value)


def _auth_is_valid(auth: Any) -> bool:
    """Validate the ``auth`` dictionary according to the envelope specification."""
    if not isinstance(auth, dict):
        return False
    if not _is_nonempty_str(auth.get("actor")):
        return False
    if not _is_roles_list(auth.get("roles")):
        return False
    if not _is_hex_string(auth.get("session"), _SESSION_HEX_LEN):
        return False
    if not isinstance(auth.get("source_ip"), str):
        return False
    issued = auth.get("issued_at_ns")
    if not isinstance(issued, int) or isinstance(issued, bool):
        return False
    return _is_hex_string(auth.get("nonce"), _NONCE_HEX_LEN, lowercase=True)


def _envelope_is_valid(env: Mapping[str, Any]) -> bool:
    """Validate required envelope fields and their types.

    Extra keys are tolerated.
    """
    if not _is_nonempty_str(env.get("id")):
        return False
    if not isinstance(env.get("cmd"), str):
        return False
    if not isinstance(env.get("args"), dict):
        return False
    if not isinstance(env.get("sig"), str):
        return False
    return _auth_is_valid(env.get("auth"))


def _expected_signature(env: Mapping[str, Any], key: bytes) -> str | None:
    """Compute the HMAC-SHA256 signature that ``env`` should have.

    Returns ``None`` if the envelope cannot be serialized to JSON.
    """
    try:
        env_copy = dict(env)
        env_copy.pop("sig", None)
        mac = hmac.new(key, canonical_bytes(env_copy), hashlib.sha256)
        return mac.hexdigest()
    except (TypeError, ValueError):
        return None


def _signature_matches(env: Mapping[str, Any], key: bytes) -> bool:
    """Return ``True`` if ``env`` carries the correct HMAC-SHA256 signature.

    Both sides are compared as bytes: ``hmac.compare_digest`` raises ``TypeError``
    for non-ASCII ``str``, so the received signature (untrusted input) is encoded
    with ``"replace"`` to guarantee comparison never raises.
    """
    expected = _expected_signature(env, key)
    if expected is None:
        return False
    received = env["sig"].encode("utf-8", "replace")
    return bool(hmac.compare_digest(expected.encode(), received))


def _is_fresh(auth: Mapping[str, Any], now_ns: int, max_skew_s: float) -> bool:
    """Return ``True`` if the envelope's issue time is within ``max_skew_s`` of ``now_ns``."""
    delta_ns = abs(now_ns - int(auth["issued_at_ns"]))
    return bool(delta_ns <= max_skew_s * _NS_PER_SECOND)


def verify_envelope(
    env: Mapping[str, Any],
    key: bytes,
    now_ns: int,
    nonce_cache: NonceCache,
    max_skew_s: float = 30,
) -> tuple[bool, str]:
    """Validate an envelope against cryptographic and replay rules.

    Parameters
    ----------
    env:
        The envelope to verify.
    key:
        Secret HMAC key; must be at least :data:`MIN_KEY_BYTES` bytes long.
    now_ns:
        Current time in nanoseconds since the epoch, from the caller's clock.
    nonce_cache:
        Cache used to detect replayed nonces and envelope identifiers.
    max_skew_s:
        Maximum allowed difference, in seconds, between ``now_ns`` and the
        envelope's ``issued_at_ns``.

    Returns
    -------
    tuple[bool, str]
        ``(is_valid, reason)`` where ``reason`` explains the failure or is
        ``'ok'`` when the envelope passes all checks.
    """
    if len(key) < MIN_KEY_BYTES:
        return False, "key_too_short"
    if not _envelope_is_valid(env):
        return False, "malformed"
    if not _signature_matches(env, key):
        return False, "bad_signature"
    auth = env["auth"]
    if not _is_fresh(auth, now_ns, max_skew_s):
        return False, "stale"
    cache_result = nonce_cache.check_and_add(auth["nonce"], env["id"])
    if cache_result is not None:
        return False, cache_result
    return True, "ok"
