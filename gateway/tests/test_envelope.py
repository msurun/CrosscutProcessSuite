"""Tests for policy envelope signing, verification, and replay protection.

Ensures cryptographic signatures, field formats, time skew validation, and
nonce/ID replay caches behave according to the envelope specification.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from crosscut_gateway.envelope import (
    MIN_KEY_BYTES,
    EnvelopeError,
    NonceCache,
    sign_envelope,
    verify_envelope,
)

KEY = b"k" * 32
NOW_NS = 1_700_000_000 * (10**9)
NS_PER_SECOND = 10**9


def nonce(number: int) -> str:
    """Return a 32-character hexadecimal nonce formatted from an integer."""
    return f"{number:032x}"


def make_env(
    env_id: str = "env-1",
    nonce_hex: str | None = None,
    issued_at_ns: int = NOW_NS,
) -> dict[str, Any]:
    """Create a valid unsigned envelope dictionary."""
    return {
        "id": env_id,
        "cmd": "set_sp",
        "args": {"tag": "FIC101", "value": 5.0},
        "auth": {
            "actor": "alice",
            "roles": ["operator"],
            "session": "0123456789abcdef",
            "source_ip": "10.0.0.1",
            "issued_at_ns": issued_at_ns,
            "nonce": nonce_hex or nonce(1),
        },
    }


def signed(**fields: Any) -> dict[str, Any]:
    """Return a signed envelope constructed from the supplied parameters."""
    return sign_envelope(make_env(**fields), KEY)


def verify(
    envelope: dict[str, Any],
    cache: NonceCache | None = None,
    key: bytes = KEY,
    now_ns: int = NOW_NS,
) -> tuple[bool, str]:
    """Verify an envelope against default or specified test settings."""
    active_cache = cache if cache is not None else NonceCache()
    return verify_envelope(envelope, key, now_ns, active_cache)


class FakeClock:
    """Deterministic monotonic clock for cache expiry testing."""

    def __init__(self, start_time: float = 0.0) -> None:
        """Initialize fake clock at the specified starting seconds."""
        self.current_time = start_time

    def __call__(self) -> float:
        """Return the current time in seconds."""
        return self.current_time

    def advance(self, seconds: float) -> None:
        """Advance the current clock time by the given duration in seconds."""
        self.current_time += seconds


def tamper_id(envelope: dict[str, Any]) -> None:
    """Mutate envelope identifier."""
    envelope["id"] = "env-tampered"


def tamper_cmd(envelope: dict[str, Any]) -> None:
    """Mutate envelope command."""
    envelope["cmd"] = "stop_pump"


def tamper_args_tag(envelope: dict[str, Any]) -> None:
    """Mutate args tag field."""
    envelope["args"]["tag"] = "TIC202"


def tamper_args_value(envelope: dict[str, Any]) -> None:
    """Mutate args value field."""
    envelope["args"]["value"] = 99.9


def tamper_auth_actor(envelope: dict[str, Any]) -> None:
    """Mutate auth actor field."""
    envelope["auth"]["actor"] = "mallory"


def tamper_roles_added(envelope: dict[str, Any]) -> None:
    """Append extra role to auth roles."""
    envelope["auth"]["roles"].append("admin")


def tamper_roles_removed(envelope: dict[str, Any]) -> None:
    """Clear auth roles list."""
    envelope["auth"]["roles"] = []


def tamper_session(envelope: dict[str, Any]) -> None:
    """Mutate auth session identifier."""
    envelope["auth"]["session"] = "fedcba9876543210"


def tamper_source_ip(envelope: dict[str, Any]) -> None:
    """Mutate auth source IP address."""
    envelope["auth"]["source_ip"] = "192.168.1.1"


def tamper_issued_at(envelope: dict[str, Any]) -> None:
    """Advance auth issued timestamp by one nanosecond."""
    envelope["auth"]["issued_at_ns"] += 1


def tamper_nonce(envelope: dict[str, Any]) -> None:
    """Replace auth nonce with another valid nonce."""
    envelope["auth"]["nonce"] = nonce(2)


def tamper_extra_nested(envelope: dict[str, Any]) -> None:
    """Inject extra nested key into auth mapping."""
    envelope["auth"]["extra"] = "x"


def mutate_missing_sig(envelope: dict[str, Any]) -> None:
    """Remove signature field."""
    envelope.pop("sig", None)


def mutate_sig_non_string(envelope: dict[str, Any]) -> None:
    """Set signature field to a non-string integer."""
    envelope["sig"] = 123


def mutate_missing_auth(envelope: dict[str, Any]) -> None:
    """Remove auth mapping."""
    envelope.pop("auth", None)


def mutate_auth_not_dict(envelope: dict[str, Any]) -> None:
    """Replace auth field with a string."""
    envelope["auth"] = "invalid_auth"


def mutate_nonce_uppercase(envelope: dict[str, Any]) -> None:
    """Replace nonce with uppercase hex characters."""
    envelope["auth"]["nonce"] = "A" * 32


def mutate_nonce_short(envelope: dict[str, Any]) -> None:
    """Replace nonce with a 31-character hex string."""
    envelope["auth"]["nonce"] = "a" * 31


def mutate_issued_float(envelope: dict[str, Any]) -> None:
    """Set issued_at_ns to a float value."""
    envelope["auth"]["issued_at_ns"] = 1.5


def mutate_issued_bool(envelope: dict[str, Any]) -> None:
    """Set issued_at_ns to a boolean value."""
    envelope["auth"]["issued_at_ns"] = True


def mutate_issued_str(envelope: dict[str, Any]) -> None:
    """Set issued_at_ns to a string value."""
    envelope["auth"]["issued_at_ns"] = "1"


def mutate_roles_not_list(envelope: dict[str, Any]) -> None:
    """Replace roles list with a string."""
    envelope["auth"]["roles"] = "operator"


def test_round_trip_verification_succeeds() -> None:
    """Confirm a newly signed envelope verifies as valid."""
    is_valid, reason = verify(signed())
    assert is_valid is True
    assert reason == "ok"


@pytest.mark.parametrize(
    "mutator",
    [
        tamper_id,
        tamper_cmd,
        tamper_args_tag,
        tamper_args_value,
        tamper_auth_actor,
        tamper_roles_added,
        tamper_roles_removed,
        tamper_session,
        tamper_source_ip,
        tamper_issued_at,
        tamper_nonce,
        tamper_extra_nested,
    ],
    ids=[
        "id",
        "cmd",
        "args_tag",
        "args_value",
        "auth_actor",
        "roles_added",
        "roles_removed",
        "session",
        "source_ip",
        "issued_at_ns",
        "nonce",
        "extra_nested_auth",
    ],
)
def test_tampered_envelope_rejected_with_bad_signature(mutator: Any) -> None:
    """Confirm altering any signed field causes signature mismatch."""
    tampered_envelope = copy.deepcopy(signed())
    mutator(tampered_envelope)
    is_valid, reason = verify(tampered_envelope)
    assert is_valid is False
    assert reason == "bad_signature"


def test_replay_same_envelope_twice_rejected() -> None:
    """Confirm replaying the exact same envelope is detected as replayed nonce."""
    cache = NonceCache()
    envelope = signed()
    first_valid, first_reason = verify(envelope, cache=cache)
    second_valid, second_reason = verify(envelope, cache=cache)
    assert first_valid is True
    assert first_reason == "ok"
    assert second_valid is False
    assert second_reason == "replayed_nonce"


def test_replay_same_nonce_different_id_rejected() -> None:
    """Confirm re-using a nonce with a distinct ID reports replayed nonce."""
    cache = NonceCache()
    first_envelope = signed(env_id="env-1", nonce_hex=nonce(1))
    second_envelope = signed(env_id="env-2", nonce_hex=nonce(1))
    first_valid, first_reason = verify(first_envelope, cache=cache)
    second_valid, second_reason = verify(second_envelope, cache=cache)
    assert first_valid is True
    assert first_reason == "ok"
    assert second_valid is False
    assert second_reason == "replayed_nonce"


def test_replay_same_id_different_nonce_rejected() -> None:
    """Confirm re-using an ID with a distinct nonce reports replayed ID."""
    cache = NonceCache()
    first_envelope = signed(env_id="env-1", nonce_hex=nonce(1))
    second_envelope = signed(env_id="env-1", nonce_hex=nonce(2))
    first_valid, first_reason = verify(first_envelope, cache=cache)
    second_valid, second_reason = verify(second_envelope, cache=cache)
    assert first_valid is True
    assert first_reason == "ok"
    assert second_valid is False
    assert second_reason == "replayed_id"


@pytest.mark.parametrize(
    ("offset_seconds", "expected_reason", "expected_valid"),
    [
        (-31, "stale", False),
        (31, "stale", False),
        (-29, "ok", True),
        (29, "ok", True),
    ],
)
def test_envelope_staleness_thresholds(
    offset_seconds: int,
    expected_reason: str,
    expected_valid: bool,
) -> None:
    """Verify that envelopes outside the permitted skew are marked stale."""
    skewed_envelope = signed(issued_at_ns=NOW_NS + (offset_seconds * NS_PER_SECOND))
    is_valid, reason = verify(skewed_envelope, now_ns=NOW_NS)
    assert is_valid is expected_valid
    assert reason == expected_reason


def test_key_length_and_mismatch_rules() -> None:
    """Verify minimum key length enforcement and signature validation across keys."""
    assert MIN_KEY_BYTES == 32
    short_key = b"k" * 31
    envelope = signed()
    is_valid, reason = verify(envelope, key=short_key)
    assert is_valid is False
    assert reason == "key_too_short"

    with pytest.raises(EnvelopeError):
        sign_envelope(make_env(), short_key)

    different_key = b"z" * 32
    valid_with_diff, diff_reason = verify(envelope, key=different_key)
    assert valid_with_diff is False
    assert diff_reason == "bad_signature"


@pytest.mark.parametrize(
    "mutator",
    [
        mutate_missing_sig,
        mutate_sig_non_string,
        mutate_missing_auth,
        mutate_auth_not_dict,
        mutate_nonce_uppercase,
        mutate_nonce_short,
        mutate_issued_float,
        mutate_issued_bool,
        mutate_issued_str,
        mutate_roles_not_list,
    ],
    ids=[
        "missing_sig",
        "sig_non_string",
        "missing_auth",
        "auth_not_dict",
        "nonce_uppercase",
        "nonce_short",
        "issued_float",
        "issued_bool",
        "issued_str",
        "roles_not_list",
    ],
)
def test_malformed_envelope_variants(mutator: Any) -> None:
    """Confirm envelopes violating schema checks return malformed."""
    malformed_envelope = copy.deepcopy(signed())
    mutator(malformed_envelope)
    is_valid, reason = verify(malformed_envelope)
    assert is_valid is False
    assert reason == "malformed"


def test_nonce_cache_expiry_with_fake_clock() -> None:
    """Confirm entries expire from NonceCache after the configured window."""
    fake_clock = FakeClock(start_time=0.0)
    cache = NonceCache(window_s=10.0, clock=fake_clock)
    first_result = cache.check_and_add(nonce(1), "env-a")
    repeat_result = cache.check_and_add(nonce(1), "env-a")
    assert first_result is None
    assert repeat_result == "replayed_nonce"

    fake_clock.advance(11.0)
    readd_result = cache.check_and_add(nonce(1), "env-a")
    assert readd_result is None


def test_nonce_cache_length_and_pruning() -> None:
    """Confirm NonceCache size reflects nonces and IDs and prunes on addition."""
    fake_clock = FakeClock(start_time=0.0)
    cache = NonceCache(window_s=10.0, clock=fake_clock)
    cache.check_and_add(nonce(1), "env-a")
    cache.check_and_add(nonce(2), "env-b")
    assert len(cache) == 4

    fake_clock.advance(11.0)
    cache.check_and_add(nonce(3), "env-c")
    assert len(cache) == 2


def test_failed_verify_does_not_poison_nonce_cache() -> None:
    """Confirm failed verification leaves the replay cache clean for valid retries."""
    cache = NonceCache()
    tampered_envelope = copy.deepcopy(signed())
    tamper_cmd(tampered_envelope)
    failed_valid, failed_reason = verify(tampered_envelope, cache=cache)
    assert failed_valid is False
    assert failed_reason == "bad_signature"

    genuine_envelope = signed()
    success_valid, success_reason = verify(genuine_envelope, cache=cache)
    assert success_valid is True
    assert success_reason == "ok"


def test_signature_independent_of_dictionary_key_order() -> None:
    """Confirm canonical serialization ensures signature ignores key insertion order."""
    original_env = make_env()
    reversed_args = dict(reversed(list(original_env["args"].items())))
    reversed_auth = dict(reversed(list(original_env["auth"].items())))
    reversed_env = dict(reversed(list(original_env.items())))
    reversed_env["args"] = reversed_args
    reversed_env["auth"] = reversed_auth

    standard_signed = sign_envelope(original_env, KEY)
    reversed_signed = sign_envelope(reversed_env, KEY)
    assert standard_signed["sig"] == reversed_signed["sig"]


def test_sign_envelope_refuses_existing_signature() -> None:
    """Confirm sign_envelope raises EnvelopeError when sig key is present."""
    already_signed = signed()
    with pytest.raises(EnvelopeError):
        sign_envelope(already_signed, KEY)
