"""Hardening tests for the write-gateway auth gate.

Covers keyless set_mode limited to non-raising changes, attribution of refusals issued before
signature verification to unverified actors, and replay protection that survives a restart.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import pytest
from crosscut_gateway.auth_gate import AuthGate
from crosscut_gateway.envelope import NonceCache, sign_envelope

KEY = bytes(range(1, 33))
NS_PER_S = 1_000_000_000
START_S = 1_700_000_000.0
NOW_NS = 1_700_000_000 * NS_PER_S
ROLES: dict[str, frozenset[str]] = {"lead": frozenset({"gw.kill", "gw.propose"})}


@dataclass
class FakeGateway:
    """Stand-in for WriteGateway exposing only the attributes the gate reads."""

    mode: str = "confirm"
    mode_cap: str = "supervised"

    def pending_proposer(self, key: object) -> str | None:
        """Report no pending proposer so the self-approval rule never fires."""
        return None

    def target_state(self, tag: object) -> str | None:
        """Report no target state for re_enable lookups."""
        return None


class Clock:
    """Settable clock returning seconds, shared by the gate and its nonce cache."""

    def __init__(self, now_s: float = START_S) -> None:
        """Start the clock at now_s seconds."""
        self.now_s = now_s

    def __call__(self) -> float:
        """Return the current time in seconds."""
        return self.now_s


def nonce_hex(number: int) -> str:
    """Return a 32-character lowercase hexadecimal nonce derived from number."""
    return f"{number:032x}"


def make_cmd(
    cmd: str = "kill",
    args: Any = None,
    *,
    n: int = 1,
    issued_ns: int = NOW_NS,
    actor: str = "alice",
) -> dict[str, Any]:
    """Return an unsigned envelope whose id and nonce are derived from n."""
    return {
        "id": f"cmd-{n}",
        "cmd": cmd,
        "args": {} if args is None else args,
        "auth": {
            "actor": actor,
            "roles": ["lead"],
            "session": "0123456789abcdef",
            "source_ip": "10.0.0.1",
            "issued_at_ns": issued_ns,
            "nonce": nonce_hex(n),
        },
    }


def signed(cmd: str = "kill", args: Any = None, **fields: Any) -> dict[str, Any]:
    """Return make_cmd(...) signed with KEY."""
    return sign_envelope(make_cmd(cmd, args, **fields), KEY)


def keyless_gate() -> AuthGate:
    """Return a gate with no key loaded."""
    return AuthGate(ROLES, Clock())


def keyed_gate(clock: Clock | None = None, start_ns: int | None = None) -> AuthGate:
    """Return a gate with KEY loaded, optionally sharing clock and carrying a start time."""
    kwargs: dict[str, Any] = {} if start_ns is None else {"start_ns": start_ns}
    gate = AuthGate(ROLES, Clock() if clock is None else clock, **kwargs)
    gate.set_key(KEY)
    return gate


@pytest.mark.parametrize(
    ("current", "new"),
    [("confirm", "advisory"), ("confirm", "confirm"), ("supervised", "off"), ("advisory", "off")],
)
def test_keyless_set_mode_downgrade_or_same_is_accepted(current: str, new: str) -> None:
    """Without a key a set_mode to the same or a lower mode is accepted as unverified."""
    verdict = keyless_gate().check(signed("set_mode", {"mode": new}), FakeGateway(mode=current))
    assert (verdict.ok, verdict.reason) == (True, "ok")
    assert verdict.ctx.actor == "unverified:alice"


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("off", "advisory"),
        ("advisory", "dry_run"),
        ("confirm", "supervised"),
        ("off", "supervised"),
    ],
)
def test_keyless_set_mode_upward_is_refused(current: str, new: str) -> None:
    """Without a key a set_mode that raises the mode is refused, even from off to advisory."""
    verdict = keyless_gate().check(signed("set_mode", {"mode": new}), FakeGateway(mode=current))
    assert (verdict.ok, verdict.reason) == (False, "key_missing")
    assert verdict.ctx.actor == "unverified:alice"


@pytest.mark.parametrize("args", ["advisory", {}, {"mode": None}, {"mode": "bogus"}, {"mode": 1}])
def test_keyless_set_mode_with_bad_args_is_refused(args: Any) -> None:
    """Without a key a set_mode with non-dict or unknown-mode args is refused as key_missing."""
    verdict = keyless_gate().check(signed("set_mode", args), FakeGateway(mode="confirm"))
    assert (verdict.ok, verdict.reason) == (False, "key_missing")


def test_keyless_set_mode_refused_when_current_mode_is_unknown() -> None:
    """Without a key a downgrade is refused when the gateway reports an unknown current mode."""
    verdict = keyless_gate().check(signed("set_mode", {"mode": "off"}), FakeGateway(mode="weird"))
    assert (verdict.ok, verdict.reason) == (False, "key_missing")


@pytest.mark.parametrize("cmd", ["propose", "approve", "policy_pin", "re_enable"])
def test_keyless_other_commands_are_refused(cmd: str) -> None:
    """Without a key every signed command other than kill and set_mode is refused."""
    verdict = keyless_gate().check(signed(cmd, {}), FakeGateway())
    assert (verdict.ok, verdict.reason) == (False, "key_missing")
    assert verdict.ctx.actor == "unverified:alice"


def test_keyless_kill_is_accepted_as_unverified() -> None:
    """Without a key a signed kill is still accepted, attributed to the unverified actor."""
    verdict = keyless_gate().check(signed("kill"), FakeGateway())
    assert (verdict.ok, verdict.reason) == (True, "ok")
    assert verdict.ctx.actor == "unverified:alice"


def test_unsigned_refusal_is_attributed_unverified() -> None:
    """An unsigned non-kill command is refused and audited under the unverified claimed actor."""
    verdict = keyed_gate().check(make_cmd("propose"), FakeGateway())
    assert (verdict.ok, verdict.reason) == (False, "unsigned_not_allowed")
    assert verdict.ctx.actor == "unverified:alice"


def test_unsigned_refusal_without_auth_is_unverified_unknown() -> None:
    """An unsigned command with no auth block is audited as unverified:unknown."""
    env = make_cmd("propose")
    del env["auth"]
    verdict = keyed_gate().check(env, FakeGateway())
    assert verdict.reason == "unsigned_not_allowed"
    assert verdict.ctx.actor == "unverified:unknown"


def test_non_dict_input_is_unverified_unknown() -> None:
    """A JSON list is refused as malformed and audited as unverified:unknown."""
    verdict = keyed_gate().check([1, 2, 3], FakeGateway())
    assert (verdict.reason, verdict.ctx.actor) == ("malformed", "unverified:unknown")


def test_malformed_signed_envelope_is_unverified() -> None:
    """A signed envelope with an invalid auth block is refused as malformed, unverified."""
    env = signed("propose", {})
    env["auth"] = {"actor": "alice"}
    verdict = keyed_gate().check(env, FakeGateway())
    assert (verdict.reason, verdict.ctx.actor) == ("malformed", "unverified:alice")


def test_recursion_in_envelope_is_malformed_and_unverified() -> None:
    """An envelope too deeply nested to canonicalise is refused as malformed and unverified."""
    deep: dict[str, Any] = {}
    cursor = deep
    for _ in range(3000):
        nxt: dict[str, Any] = {}
        cursor["k"] = nxt
        cursor = nxt
    env = make_cmd("propose", {"deep": deep})
    env["sig"] = "0" * 64
    verdict = keyed_gate().check(env, FakeGateway())
    assert (verdict.reason, verdict.ctx.actor) == ("malformed", "unverified:alice")


def test_tampered_signed_envelope_is_bad_signature_unverified() -> None:
    """A signed envelope whose args were altered is refused as bad_signature, unverified."""
    env = signed("propose", {"x": 1})
    env["args"] = {"x": 2}
    verdict = keyed_gate().check(env, FakeGateway())
    assert (verdict.reason, verdict.ctx.actor) == ("bad_signature", "unverified:alice")


def test_signed_envelope_without_key_is_key_missing_unverified() -> None:
    """A signed propose with no key loaded is refused as key_missing, unverified."""
    verdict = keyless_gate().check(signed("propose", {}), FakeGateway())
    assert (verdict.reason, verdict.ctx.actor) == ("key_missing", "unverified:alice")


def test_stale_envelope_keeps_plain_actor() -> None:
    """A verified but stale envelope is refused under the plain claimed actor."""
    env = signed("kill", issued_ns=NOW_NS - 60 * NS_PER_S)
    verdict = keyed_gate().check(env, FakeGateway())
    assert (verdict.reason, verdict.ctx.actor) == ("stale", "alice")


def test_replayed_envelope_keeps_plain_actor() -> None:
    """A verified envelope seen before is refused as replayed under the plain actor."""
    gate = keyed_gate()
    env = signed("kill")
    assert gate.check(env, FakeGateway()).ok is True
    verdict = gate.check(env, FakeGateway())
    assert (verdict.reason, verdict.ctx.actor) == ("replayed_nonce", "alice")


def test_unauthorized_verified_envelope_keeps_plain_actor() -> None:
    """A verified envelope whose roles lack the permission is refused under the plain actor."""
    env = make_cmd("kill")
    env["auth"]["roles"] = ["nobody"]
    verdict = keyed_gate().check(sign_envelope(env, KEY), FakeGateway())
    assert verdict.ok is False
    assert verdict.ctx.actor == "alice"


def test_predates_start_is_refused_after_restart() -> None:
    """A verified envelope issued more than a second before the gate started is refused."""
    gate = keyed_gate(start_ns=NOW_NS)
    verdict = gate.check(signed("kill", issued_ns=NOW_NS - 2 * NS_PER_S), FakeGateway())
    assert (verdict.ok, verdict.reason, verdict.ctx.actor) == (False, "predates_start", "alice")


def test_issued_one_second_before_start_is_accepted() -> None:
    """An envelope issued exactly one second before start is still accepted."""
    gate = keyed_gate(start_ns=NOW_NS)
    verdict = gate.check(signed("kill", issued_ns=NOW_NS - NS_PER_S), FakeGateway())
    assert (verdict.ok, verdict.reason) == (True, "ok")


def test_without_start_ns_old_envelope_is_not_predates_refused() -> None:
    """With no start time configured the predates rule does not apply."""
    verdict = keyed_gate().check(signed("kill", issued_ns=NOW_NS - 2 * NS_PER_S), FakeGateway())
    assert (verdict.ok, verdict.reason) == (True, "ok")


def test_replay_is_refused_after_restart_when_nonces_restored() -> None:
    """A nonce accepted before a restart is still refused after its snapshot is restored."""
    clock = Clock()
    before = keyed_gate(clock)
    env = signed("kill")
    assert before.check(env, FakeGateway()).ok is True
    snapshot = json.loads(json.dumps(before.nonce_snapshot()))
    after = keyed_gate(clock, start_ns=NOW_NS)
    after.restore_nonces(snapshot)
    verdict = after.check(env, FakeGateway())
    assert (verdict.reason, verdict.ctx.actor) == ("replayed_nonce", "alice")


def test_replay_is_accepted_after_restart_without_restore() -> None:
    """Control: without restoring the snapshot a fresh gate accepts the earlier envelope."""
    clock = Clock()
    env = signed("kill")
    assert keyed_gate(clock).check(env, FakeGateway()).ok is True
    assert keyed_gate(clock).check(env, FakeGateway()).ok is True


def test_snapshot_keeps_newest_entries_up_to_limit() -> None:
    """snapshot(limit) returns the newest entries by timestamp in both maps."""
    clock = Clock()
    cache = NonceCache(window_s=120, clock=clock)
    for n in range(5):
        clock.now_s = START_S + n
        assert cache.check_and_add(nonce_hex(n), f"id-{n}") is None
    data = cache.snapshot(limit=2)
    assert set(data["nonces"]) == {nonce_hex(3), nonce_hex(4)}
    assert set(data["ids"]) == {"id-3", "id-4"}
    assert data["nonces"][nonce_hex(4)] == START_S + 4


def test_snapshot_prunes_expired_entries_first() -> None:
    """Entries older than the window are not included in a snapshot."""
    clock = Clock()
    cache = NonceCache(window_s=120, clock=clock)
    cache.check_and_add(nonce_hex(1), "id-1")
    clock.now_s = START_S + 200
    assert cache.snapshot() == {"nonces": {}, "ids": {}}


def test_restore_round_trip_blocks_nonce_and_id_replay() -> None:
    """Restored nonces and ids are reported as replays by the receiving cache."""
    clock = Clock()
    source = NonceCache(window_s=120, clock=clock)
    source.check_and_add(nonce_hex(1), "id-1")
    target = NonceCache(window_s=120, clock=clock)
    target.restore(source.snapshot())
    assert target.check_and_add(nonce_hex(1), "other") == "replayed_nonce"
    assert target.check_and_add(nonce_hex(2), "id-1") == "replayed_id"


@pytest.mark.parametrize(
    "data",
    [
        None,
        "text",
        7,
        [1, 2],
        {"nonces": "x"},
        {"ids": [1]},
        {"nonces": {1: START_S}},
        {"nonces": {"n": "5"}},
        {"nonces": {"n": True}},
        {"nonces": {"n": math.nan}},
        {"nonces": {"n": math.inf}},
    ],
)
def test_restore_ignores_malformed_input(data: object) -> None:
    """Malformed snapshot data loads nothing and never raises."""
    cache = NonceCache(window_s=120, clock=Clock())
    cache.restore(data)
    assert len(cache) == 0


def test_restore_drops_expired_and_far_future_entries() -> None:
    """Restore keeps entries within the window and drops those expired or too far ahead."""
    cache = NonceCache(window_s=120, clock=Clock())
    cache.restore(
        {
            "nonces": {
                nonce_hex(1): START_S - 120,
                nonce_hex(2): START_S - 119,
                nonce_hex(3): START_S + 121,
                nonce_hex(4): START_S + 120,
            },
            "ids": {},
        }
    )
    assert set(cache.snapshot()["nonces"]) == {nonce_hex(2), nonce_hex(4)}


def test_restore_nonces_tolerates_garbage_on_gate() -> None:
    """AuthGate.restore_nonces accepts any object without raising."""
    gate = keyed_gate()
    gate.restore_nonces("garbage")
    gate.restore_nonces(None)
    assert gate.nonce_snapshot() == {"nonces": {}, "ids": {}}
