"""Adversarial envelope fuzzing test suite for Write Gateway.

Generates seeded pseudo-random mutations targeting every layer of the signed envelope
specification and verifies that the gateway service fails closed without crashing.
"""

from __future__ import annotations

import copy
import json
import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from auth_helpers import (
    KEY,
    AuthEnv,
    SignOpts,
    make_env,
    outbox,
    propose_args,
    rejected_reason,
    send,
    signed,
)
from crosscut_gateway import envelope

FUZZ_SEED = 20261105
MUTATION_COUNT = 300
MIN_PASSED_WITHOUT_SIGNATURE = 30
ONE_MB_BYTES = 1024 * 1024

LOOKALIKE_CYRILLIC_A = "\u0430"
ZERO_WIDTH_SPACE = "\u200b"
FULL_WIDTH_KILL = "\uff4b\uff49\uff4c\uff4c"


def _deep_set(target: dict[str, Any], path: list[str], val: Any) -> None:
    """In plain words: Traverse nested dictionary keys and assign a value at the leaf."""
    curr = target
    for key in path[:-1]:
        curr = curr[key]
    curr[path[-1]] = val


def _deep_delete(target: dict[str, Any], path: list[str]) -> None:
    """In plain words: Remove a specified nested key from a dictionary."""
    curr = target
    for key in path[:-1]:
        curr = curr[key]
    curr.pop(path[-1], None)


def _all_envelope_paths() -> list[list[str]]:
    """Return list of key paths for all standard envelope fields including nested auth."""
    return [
        ["id"],
        ["cmd"],
        ["args"],
        ["args", "target_tag"],
        ["args", "value"],
        ["args", "proposer"],
        ["args", "t_ns"],
        ["args", "reason"],
        ["auth"],
        ["auth", "actor"],
        ["auth", "roles"],
        ["auth", "session"],
        ["auth", "source_ip"],
        ["auth", "issued_at_ns"],
        ["auth", "nonce"],
        ["sig"],
    ]


def _create_flipped_mutation(
    base: dict[str, Any], rng: random.Random
) -> dict[str, Any]:
    """In plain words: Pick a random field and flip or scramble its content."""
    mut = copy.deepcopy(base)
    path = rng.choice(_all_envelope_paths())
    scrambled = f"flipped_{rng.randint(1000, 9999)}"
    _deep_set(mut, path, scrambled)
    return mut


def _create_deleted_mutation(
    base: dict[str, Any], rng: random.Random
) -> dict[str, Any]:
    """In plain words: Drop one mandatory field from the envelope or auth block."""
    mut = copy.deepcopy(base)
    path = rng.choice(_all_envelope_paths())
    _deep_delete(mut, path)
    return mut


def _create_retyped_mutation(
    base: dict[str, Any], rng: random.Random
) -> dict[str, Any]:
    """In plain words: Substitute a field's expected type with an incompatible type."""
    mut = copy.deepcopy(base)
    path = rng.choice(_all_envelope_paths())
    weird_types = [12345, ["unexpected", "list"], {"not": "expected"}, None, 3.1415]
    _deep_set(mut, path, rng.choice(weird_types))
    return mut


def _create_numeric_oddity_mutation(
    base: dict[str, Any], rng: random.Random
) -> dict[str, Any] | str:
    """In plain words: Inject huge integers, NaN, or bool values into numeric slots."""
    mut = copy.deepcopy(base)
    kind = rng.choice(["huge_int", "nan", "bool_num", "huge_str_int"])
    if kind == "huge_int":
        mut["args"]["value"] = 10**100
    elif kind == "nan":
        mut["args"]["value"] = float("nan")
    elif kind == "bool_num":
        mut["args"]["value"] = True
    else:
        # >4300 digits triggers Python's integer string conversion limit
        raw = json.dumps(base)
        return raw.replace('"value": 55.0', f'"value": {"9" * 4500}')
    return mut


def _create_unicode_lookalike_mutation(
    base: dict[str, Any], rng: random.Random
) -> dict[str, Any]:
    """In plain words: Substitute visual lookalikes, spaces, or casing into cmd/actor/roles."""
    mut = copy.deepcopy(base)
    target = rng.choice(["cmd", "actor", "roles"])
    if target == "cmd":
        variants = ["Kill", "KILL", "pr" + LOOKALIKE_CYRILLIC_A + "pose", FULL_WIDTH_KILL]
        mut["cmd"] = rng.choice(variants)
    elif target == "actor":
        variants = [
            "alice ",
            " alice",
            "ali" + ZERO_WIDTH_SPACE + "ce",
            LOOKALIKE_CYRILLIC_A + "lice",
        ]
        mut["auth"]["actor"] = rng.choice(variants)
    else:
        variants = [
            ["Engineer"],
            ["ENGINEER"],
            ["engineer "],
            ["engin" + LOOKALIKE_CYRILLIC_A + "er"],
        ]
        mut["auth"]["roles"] = rng.choice(variants)
    return mut


def _create_null_or_large_mutation(
    base: dict[str, Any], rng: random.Random
) -> dict[str, Any] | str:
    """In plain words: Inject null bytes, 1 MB strings, or deeply nested objects."""
    choice = rng.choice(["null_byte", "raw_null", "1mb_string", "nested_json"])
    if choice == "null_byte":
        mut = copy.deepcopy(base)
        mut["args"]["reason"] = "inject\x00null"
        return mut
    if choice == "raw_null":
        return json.dumps(base) + "\x00"
    if choice == "1mb_string":
        mut = copy.deepcopy(base)
        mut["args"]["reason"] = "x" * ONE_MB_BYTES
        return mut
    # Deeply nested JSON
    deep: dict[str, Any] = {"bottom": 1}
    for _ in range(120):
        deep = {"nest": deep}
    mut = copy.deepcopy(base)
    mut["args"]["nested"] = deep
    return mut


def _create_duplicate_key_mutation(base: dict[str, Any]) -> str:
    """In plain words: Construct a raw JSON string containing duplicate top-level keys."""
    raw = json.dumps(base)
    return '{"cmd": "kill", ' + raw[1:]


def _generate_single_mutation(
    base: dict[str, Any], rng: random.Random
) -> dict[str, Any] | str:
    """Dispatch to one of the mutation strategies at random."""
    strategies = [
        _create_flipped_mutation,
        _create_deleted_mutation,
        _create_retyped_mutation,
        _create_numeric_oddity_mutation,
        _create_unicode_lookalike_mutation,
        _create_null_or_large_mutation,
    ]
    if rng.random() < 0.1:
        return _create_duplicate_key_mutation(base)
    chosen_strategy = rng.choice(strategies)
    return chosen_strategy(base, rng)



# Reasons that may legitimately refuse a mutant at the syntax or authentication stage.
GATE_REASONS = frozenset({"bad_signature", "malformed", "unsigned_not_allowed"})
SYNTAX_PREFIXES = (
    "malformed JSON",
    "command must be",
    "id must be",
    "id contains",
    "cmd must be",
    "args must be",
)
# Exceptions quarantined by the service guard (parse failures of hostile raw text).
QUARANTINE_REASONS = frozenset({"ValueError", "RecursionError", "UnicodeDecodeError"})
# Audit events a pure-rejection campaign may add; anything else means engine state moved.
REJECTION_EVENTS = frozenset({"auth_reject", "service_error"})


@dataclass(frozen=True)
class Mutant:
    """One hostile inbox file: its payload and whether it parses to the original envelope."""

    index: int
    payload: dict[str, Any] | str
    identical: bool

    @property
    def cmd_id(self) -> str:
        """Return the fresh id the underlying envelope was signed with."""
        return f"m{self.index:04d}"

    @property
    def stem(self) -> str:
        """Return the inbox file name without the .json suffix."""
        return f"fuzz_{self.index:04d}"

    @property
    def filename(self) -> str:
        """Return the inbox file name."""
        return self.stem + ".json"


@dataclass
class Campaign:
    """A finished fuzz campaign: the environment, its mutants and the state around the poll."""

    env: AuthEnv
    mutants: list[Mutant]
    before: dict[str, Any]
    audit_before: int


def _fresh_signed(env: AuthEnv, rng: random.Random, index: int) -> dict[str, Any]:
    """Sign a propose envelope with a fresh id (m<index>) and a fresh random nonce."""
    opts = SignOpts(cmd_id=f"m{index:04d}", nonce=f"{rng.getrandbits(128):032x}")
    return signed(
        env, "propose", propose_args(env, 55.0), actor="alice", roles=("engineer",), extra=opts
    )


def _is_identical(payload: dict[str, Any] | str, original: dict[str, Any]) -> bool:
    """Return True when the written payload parses to exactly the original signed envelope."""
    try:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return bool(json.loads(text) == original)
    except ValueError:
        return False


def _build_mutants(env: AuthEnv, seed: int) -> list[Mutant]:
    """Build the seeded mutants; each starts from its own fresh, validly signed envelope.

    The old signature is kept on purpose, so only the mutated field can make a mutant differ
    from an envelope the gateway would accept.
    """
    rng = random.Random(seed)
    nonces: set[str] = set()
    mutants = []
    for index in range(MUTATION_COUNT):
        base = _fresh_signed(env, rng, index)
        assert base["auth"]["nonce"] not in nonces, "nonce reused between mutants"
        nonces.add(base["auth"]["nonce"])
        payload = _generate_single_mutation(base, rng)
        mutants.append(Mutant(index, payload, _is_identical(payload, base)))
    return mutants


def _write_mutant(inbox: Path, mutant: Mutant) -> None:
    """Persist the mutated envelope to the service inbox directory."""
    path = inbox / mutant.filename
    if isinstance(mutant.payload, str):
        path.write_text(mutant.payload, encoding="utf-8", errors="replace")
    else:
        path.write_text(json.dumps(mutant.payload), encoding="utf-8")


def _state_snapshot(env: AuthEnv) -> dict[str, Any]:
    """Capture everything a rejected command must leave untouched."""
    return {
        "mode": env.gateway.mode,
        "status": env.gateway.status(),
        "pending": list(env.gateway.pending()),
        "killed": env.gateway.killed,
        "writes": len(env.plant.writes),
    }


def _run_campaign(root: Path, *, include_identical: bool = True) -> Campaign:
    """Create an environment under root, drop the mutants in the inbox and poll once."""
    root.mkdir(parents=True, exist_ok=True)
    env = make_env(root, mode="confirm")
    mutants = _build_mutants(env, FUZZ_SEED)
    dropped = [m for m in mutants if include_identical or not m.identical]
    before = _state_snapshot(env)
    audit_before = len(env.gateway.audit_records())
    for mutant in dropped:
        _write_mutant(env.root / "_gateway" / "inbox", mutant)
    env.service.poll_once()
    return Campaign(env, mutants, before, audit_before)


def _reasons(campaign: Campaign) -> dict[int, str | None]:
    """Map each non-identical mutant index to its recorded rejection reason."""
    return {
        m.index: rejected_reason(campaign.env.root, m.stem)
        for m in campaign.mutants
        if not m.identical
    }


def _reason_is_expected(reason: str) -> bool:
    """Return True for a refusal produced at the syntax or authentication stage."""
    return (
        reason in GATE_REASONS
        or reason in QUARANTINE_REASONS
        or reason.startswith(SYNTAX_PREFIXES)
    )


def _outbox_ids(env: AuthEnv) -> set[str]:
    """Return the ids that have a result file in the outbox."""
    return {p.stem for p in (env.root / "_gateway" / "outbox").glob("*.json")}


@pytest.fixture(scope="module")
def real_campaign(tmp_path_factory: pytest.TempPathFactory) -> Campaign:
    """Run the full fuzz campaign once against the real signature check."""
    return _run_campaign(tmp_path_factory.mktemp("fuzz_real"))


@pytest.mark.timeout(20)
def test_campaign_is_large_and_contains_parse_identical_mutants(real_campaign: Campaign) -> None:
    """The seeded campaign has 300 mutants, mostly real mutations plus duplicate-key ones."""
    mutants = real_campaign.mutants
    assert len(mutants) == MUTATION_COUNT
    assert len({m.cmd_id for m in mutants}) == MUTATION_COUNT
    assert any(m.identical for m in mutants), "no duplicate-key mutant was generated"
    assert sum(not m.identical for m in mutants) >= MUTATION_COUNT * 0.8


@pytest.mark.timeout(20)
def test_every_non_identical_mutant_is_rejected_at_the_gate(real_campaign: Campaign) -> None:
    """100% of the non-identical mutants are refused, and the refusal is the expected kind."""
    env = real_campaign.env
    reasons = _reasons(real_campaign)
    rejected_dir = env.root / "_gateway" / "rejected"
    for index, reason in reasons.items():
        name = real_campaign.mutants[index].filename
        assert reason is not None, f"{name} was not rejected"
        assert (rejected_dir / name).exists(), f"{name} missing from rejected/"
        assert _reason_is_expected(reason), f"{name}: unexpected reason {reason!r}"
    assert Counter(reasons.values())["bad_signature"] >= 100, "signature check hardly exercised"
    accepted_ids = {m.cmd_id for m in real_campaign.mutants if m.identical}
    assert _outbox_ids(env) <= accepted_ids, "a non-identical mutant produced a result"


@pytest.mark.timeout(20)
def test_rejected_mutants_leave_engine_state_untouched(tmp_path: Path) -> None:
    """Without the parse-identical ones, pending()==[] and writes, mode and state are unchanged."""
    campaign = _run_campaign(tmp_path / "root", include_identical=False)
    env = campaign.env
    assert env.gateway.pending() == []
    assert len(env.plant.writes) == 0
    assert env.gateway.mode == "confirm"
    assert _state_snapshot(env) == campaign.before
    new_events = {r["event"] for r in env.gateway.audit_records()[campaign.audit_before :]}
    assert new_events <= REJECTION_EVENTS, f"unexpected audit events {new_events}"
    assert _outbox_ids(env) == set()


@pytest.mark.timeout(20)
def test_parse_identical_mutants_are_accepted_exactly_once(real_campaign: Campaign) -> None:
    """Duplicate-key mutants parse to a valid signed envelope; each is accepted exactly once."""
    env = real_campaign.env
    identical = [m for m in real_campaign.mutants if m.identical]
    assert identical
    for mutant in identical:
        result = outbox(env.root, mutant.cmd_id)
        assert result is not None and result["ok"] is True, f"{mutant.cmd_id} not accepted"
        assert rejected_reason(env.root, mutant.stem) is None
    assert _outbox_ids(env) == {m.cmd_id for m in identical}
    assert len(env.gateway.pending()) == 1, "identical proposals must collapse to one pending"
    assert len(env.plant.writes) == 0


@pytest.mark.timeout(20)
def test_control_without_signature_check_accepts_field_mutants(
    real_campaign: Campaign, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the signature check off, field mutants get through: the check is what refuses them."""
    real_bad_sig = {i for i, r in _reasons(real_campaign).items() if r == "bad_signature"}
    monkeypatch.setattr(envelope, "_signature_matches", lambda _env, _key: True)
    control = _run_campaign(tmp_path / "control")
    rejected_dir = control.env.root / "_gateway" / "rejected"
    passed = {
        m.index
        for m in control.mutants
        if not m.identical and not (rejected_dir / m.filename).exists()
    }
    assert len(passed) >= MIN_PASSED_WITHOUT_SIGNATURE, "mutants too weak to need the signature"
    assert passed <= real_bad_sig, "a mutant passed without the signature for another reason"
    ok_results = [outbox(control.env.root, f"m{i:04d}") for i in passed]
    assert any(r is not None and r["ok"] for r in ok_results), "none reached an ok result"


def _resign(mutated: dict[str, Any]) -> dict[str, Any]:
    """Re-sign a mutated envelope so only its semantics are under test."""
    body = {k: v for k, v in mutated.items() if k != "sig"}
    return envelope.sign_envelope(body, KEY)


def _set(path: list[str], value: Any) -> Callable[[dict[str, Any]], None]:
    """Return a mutator that sets the nested field at path."""
    return lambda env_: _deep_set(env_, path, value)


def _drop(path: list[str]) -> Callable[[dict[str, Any]], None]:
    """Return a mutator that removes the nested field at path."""
    return lambda env_: _deep_delete(env_, path)


SEMANTIC_CASES: dict[str, Callable[[dict[str, Any]], None]] = {
    "value_inf": _set(["args", "value"], float("inf")),
    "value_nan": _set(["args", "value"], float("nan")),
    "value_huge": _set(["args", "value"], 10**400),
    "value_bool": _set(["args", "value"], True),
    "value_str": _set(["args", "value"], "55"),
    "value_none": _set(["args", "value"], None),
    "t_ns_float": _set(["args", "t_ns"], 1.5),
    "t_ns_bool": _set(["args", "t_ns"], True),
    "tag_missing": _drop(["args", "target_tag"]),
    "tag_empty": _set(["args", "target_tag"], ""),
    "tag_int": _set(["args", "target_tag"], 7),
    "proposer_int": _set(["args", "proposer"], 5),
    "reason_none": _set(["args", "reason"], None),
    "args_list": _set(["args"], []),
    "cmd_int": _set(["cmd"], 5),
    "cmd_title": _set(["cmd"], "Propose"),
    "cmd_upper": _set(["cmd"], "PROPOSE"),
    "cmd_space": _set(["cmd"], "propose "),
    "cmd_cyrillic": _set(["cmd"], "pr" + LOOKALIKE_CYRILLIC_A + "pose"),
    "cmd_fullwidth": _set(["cmd"], "ｐropose"),
    "role_title": _set(["auth", "roles"], ["Engineer"]),
    "role_upper": _set(["auth", "roles"], ["ENGINEER"]),
    "role_space": _set(["auth", "roles"], ["engineer "]),
    "role_cyrillic": _set(["auth", "roles"], ["engin" + LOOKALIKE_CYRILLIC_A + "er"]),
    "role_empty": _set(["auth", "roles"], []),
    "role_viewer": _set(["auth", "roles"], ["viewer"]),
    "actor_cyrillic_mix": _set(["auth", "actor"], LOOKALIKE_CYRILLIC_A + "lice"),
    "actor_zero_width": _set(["auth", "actor"], "ali" + ZERO_WIDTH_SPACE + "ce"),
    "actor_empty": _set(["auth", "actor"], ""),
    "nonce_upper": _set(["auth", "nonce"], "A" * 32),
    "nonce_short": _set(["auth", "nonce"], "a" * 31),
    "session_short": _set(["auth", "session"], "abc"),
    "issued_bool": _set(["auth", "issued_at_ns"], True),
    "issued_stale": _set(["auth", "issued_at_ns"], 1),
    "id_slash": _set(["id"], "a/b"),
    "id_dotdot": _set(["id"], "../x"),
    "id_empty": _set(["id"], ""),
}


def _was_accepted(env: AuthEnv, cmd_id: str) -> bool:
    """Return True when an ok result with an accepted decision exists for cmd_id."""
    if not cmd_id or "/" in cmd_id:
        return False
    result = outbox(env.root, cmd_id)
    if result is None or not result["ok"]:
        return False
    return bool(result["result"].get("accepted"))


@pytest.mark.timeout(20)
def test_correctly_signed_semantic_mutants_are_refused(tmp_path: Path) -> None:
    """Re-signed hostile semantics (valid signature, fresh id and nonce) are never accepted."""
    env = make_env(tmp_path, mode="confirm")
    before = _state_snapshot(env)
    rng = random.Random(FUZZ_SEED)
    sent: dict[str, tuple[str, str]] = {}
    for index, (name, mutate) in enumerate(SEMANTIC_CASES.items()):
        mutated = _fresh_signed(env, rng, 1000 + index)
        mutate(mutated)
        try:
            payload = _resign(mutated)
        except (TypeError, ValueError, OverflowError):
            continue  # not representable as signed JSON at all
        stem = f"sem_{index:03d}"
        (env.root / "_gateway" / "inbox" / f"{stem}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        sent[name] = (stem, str(payload.get("id")))
    assert len(sent) >= len(SEMANTIC_CASES) - 4
    env.service.poll_once()
    for name, (stem, cmd_id) in sent.items():
        reason = rejected_reason(env.root, stem)
        assert reason != "bad_signature", f"{name}: the signature should have verified"
        assert not _was_accepted(env, cmd_id), f"{name} was accepted"
    assert _state_snapshot(env) == before
    assert env.gateway.pending() == []
    assert len(env.plant.writes) == 0


@pytest.mark.timeout(20)
def test_pristine_envelope_still_accepted_after_fuzzing(tmp_path: Path) -> None:
    """Positive control: an untouched fresh envelope passes on a service that saw mutants."""
    campaign = _run_campaign(tmp_path / "root", include_identical=False)
    env = campaign.env
    valid_env = send(env, "propose", propose_args(env, 56.0), actor="alice", roles=("engineer",))
    result = outbox(env.root, valid_env["id"])
    assert result is not None and result["ok"] is True, "Pristine envelope was rejected!"
    assert rejected_reason(env.root, valid_env["id"]) is None
    assert len(env.gateway.pending()) == 1
