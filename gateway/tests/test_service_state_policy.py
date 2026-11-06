"""The live pinned policy and its pin are published in state.json for the API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from auth_helpers import make_env, policy_doc


def _state_policy(root: Path) -> Any:
    """Return the "policy" entry of the persisted state.json."""
    state = json.loads((root / "_gateway" / "state.json").read_text(encoding="utf-8"))
    return state["policy"]


def test_state_carries_document_and_pin_of_a_verified_policy(tmp_path: Path) -> None:
    """A verified pinned policy is published with document and pin fields, no signature."""
    make_env(tmp_path, pinned_policy=True)
    policy = _state_policy(tmp_path)
    assert policy["document"] == json.loads(json.dumps(policy_doc("confirm")))
    assert set(policy["pin"]) == {"digest", "author", "approver", "approved_at"}
    assert (policy["pin"]["author"], policy["pin"]["approver"]) == ("author1", "approver1")


def test_state_policy_is_null_without_a_policy_file(tmp_path: Path) -> None:
    """With no policy file configured the entry is null."""
    make_env(tmp_path)
    assert _state_policy(tmp_path) is None


def test_state_policy_is_null_when_the_policy_is_tampered(tmp_path: Path) -> None:
    """A policy file that no longer matches its pin is not published."""
    env = make_env(tmp_path, pinned_policy=True)
    assert env.policy_path is not None
    env.policy_path.write_bytes(env.policy_path.read_bytes() + b"\n")
    env.service.poll_once()
    assert _state_policy(tmp_path) is None
