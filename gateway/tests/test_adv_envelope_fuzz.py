"""Adversarial envelope fuzzing test suite for Write Gateway.

Generates seeded pseudo-random mutations targeting every layer of the signed envelope
specification and verifies that the gateway service fails closed without crashing.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

import pytest
from auth_helpers import (
    make_env,
    outbox,
    propose_args,
    rejected_reason,
    send,
    signed,
)

FUZZ_SEED = 20261105
MIN_MUTATIONS_COUNT = 300
MIN_REJECTION_RATIO = 0.90
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


def _write_mutated_file(inbox: Path, index: int, payload: dict[str, Any] | str) -> str:
    """In plain words: Persist the mutated envelope to the service inbox directory."""
    filename = f"fuzz_{index:04d}.json"
    file_path = inbox / filename
    if isinstance(payload, str):
        file_path.write_text(payload, encoding="utf-8", errors="replace")
    else:
        file_path.write_text(json.dumps(payload), encoding="utf-8")
    return filename


@pytest.mark.timeout(20)
def test_adversarial_envelope_fuzz_never_crashes(tmp_path: Path) -> None:
    """Fuzz valid envelopes with seeded mutations, asserting complete rejection safety."""
    env = make_env(tmp_path, mode="confirm")
    initial_mode = env.gateway.mode
    base_env = signed(
        env,
        "propose",
        propose_args(env, 55.0),
        actor="alice",
        roles=("engineer",),
    )

    rng = random.Random(FUZZ_SEED)
    inbox = env.root / "_gateway" / "inbox"
    rejected_dir = env.root / "_gateway" / "rejected"

    filenames = [
        _write_mutated_file(inbox, i, _generate_single_mutation(base_env, rng))
        for i in range(MIN_MUTATIONS_COUNT)
    ]

    # Process all mutations through gateway service loop
    env.service.poll_once()

    # Core Safety Invariants: no plant writes, no mode changes, service survived
    assert len(env.plant.writes) == 0, "Mutated envelopes caused unexpected plant write!"
    assert env.gateway.mode == initial_mode, "Mutated envelopes altered gateway mode!"

    # Count rejected envelopes
    rejected_count = sum((rejected_dir / name).exists() for name in filenames)
    rejection_ratio = rejected_count / len(filenames)
    assert rejection_ratio >= MIN_REJECTION_RATIO, (
        f"Expected at least {MIN_REJECTION_RATIO * 100}% rejections, got {rejection_ratio * 100}%"
    )

    # Positive sanity check: pristine unmodified envelope is still accepted
    valid_env = send(
        env,
        "propose",
        propose_args(env, 56.0),
        actor="alice",
        roles=("engineer",),
    )
    result = outbox(env.root, valid_env["id"])
    assert result is not None and result["ok"] is True, "Pristine envelope was rejected!"
    assert rejected_reason(env.root, valid_env["id"]) is None
