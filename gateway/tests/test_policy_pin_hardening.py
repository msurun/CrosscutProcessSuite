"""Hardening tests for the policy draft and pin flow.

Covers actor normalisation in the two-person rule, HMAC-signed drafts, digest binding of
policy_pin to the reviewed draft, and crash-safe installation with rollback.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from auth_helpers import (
    KEY,
    AuthEnv,
    SignOpts,
    make_env,
    outbox,
    policy_doc,
    rejected_reason,
    send,
)
from crosscut_gateway import actor, envelope, policy_file, policy_pin

NOW = datetime.now(UTC)
SIGNERS = policy_pin.PinSigners(author="alice", approver="bob")
ZERO_DIGEST = "0" * 64


def _doc(extra_tags: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return an advisory policy document as it reads back from JSON."""
    return json.loads(json.dumps(policy_doc("advisory", extra_tags)))


def _policy_file(tmp_path: Path) -> Path:
    """Write a supervised policy file with no pin and return its path."""
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy_doc("supervised")), encoding="utf-8")
    return path


def _signed_pin(policy_path: Path, *, author: str, approver: str) -> None:
    """Write a pin validly signed with KEY, bypassing the signer checks of create_pin."""
    body = {
        "digest": policy_pin.file_digest(policy_path),
        "author": author,
        "approver": approver,
        "approved_at": NOW.isoformat(),
    }
    doc = {**body, "sig": envelope.sign_envelope(body, KEY)["sig"]}
    policy_pin.pin_path_for(policy_path).write_text(json.dumps(doc), encoding="utf-8")


def _request(
    policy_path: Path,
    document: dict[str, Any],
    *,
    key: bytes = KEY,
    signers: policy_pin.PinSigners = SIGNERS,
) -> policy_pin.PinRequest:
    """Build a PinRequest with the shared test clock."""
    return policy_pin.PinRequest(
        policy_path=policy_path,
        document=document,
        key=key,
        signers=signers,
        now=NOW,
    )


def _fail_pin_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the atomic replace fail only when it targets the pin file."""
    real_replace = os.replace

    def flaky_replace(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
        if Path(dst).name == policy_pin.PIN_FILE_NAME:
            raise OSError("injected crash")
        real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(policy_pin.os, "replace", flaky_replace)


def _draft_path(env: AuthEnv) -> Path:
    """Return the path of the saved policy draft."""
    return env.root / "_gateway" / "policy-draft.json"


def _read_draft(env: AuthEnv) -> dict[str, Any]:
    """Return the saved draft as a dict."""
    return json.loads(_draft_path(env).read_text(encoding="utf-8"))


def _write_draft(env: AuthEnv, draft: dict[str, Any]) -> None:
    """Overwrite the saved draft file with ``draft``."""
    _draft_path(env).write_text(json.dumps(draft, indent=2), encoding="utf-8")


def _save(env: AuthEnv, document: dict[str, Any], who: str = "alice") -> str:
    """Save a draft as ``who`` and return the digest the gateway reported in the outbox."""
    cmd = send(env, "policy_draft", {"document": document}, actor=who, roles=("lead",))
    return str(outbox(env.root, cmd["id"])["result"]["digest"])


def _pin(env: AuthEnv, who: str, args: dict[str, Any]) -> dict[str, Any]:
    """Send a policy_pin command as ``who`` with a step-up and the given args."""
    return send(env, "policy_pin", args, actor=who, roles=("lead",), extra=SignOpts(stepup=True))


def _reason(env: AuthEnv, cmd: dict[str, Any]) -> str:
    """Return the rejection reason recorded for ``cmd``, or an empty string."""
    return (rejected_reason(env.root, cmd["id"]) or "").strip()


def test_normalize_actor_folds_case_and_whitespace() -> None:
    """Actor names differing only in case or whitespace normalise to the same value."""
    assert actor.normalize_actor("  Alice   Smith ") == "alice smith"
    assert actor.normalize_actor("ALICE") == actor.normalize_actor("alice")


def test_create_pin_refuses_case_variant_self_approval(tmp_path: Path) -> None:
    """A pin cannot be created when the approver differs from the author only in case."""
    policy_path = _policy_file(tmp_path)
    with pytest.raises(policy_pin.PinError, match="author_equals_approver"):
        policy_pin.create_pin(policy_path, KEY, policy_pin.PinSigners("Alice", " alice "), NOW)


def test_verify_pin_refuses_resigned_case_variant_self_approval(tmp_path: Path) -> None:
    """A validly signed pin naming the same person in two spellings fails verification."""
    policy_path = _policy_file(tmp_path)
    _signed_pin(policy_path, author="alice", approver="Alice")
    with pytest.raises(policy_pin.PinError, match="author_equals_approver"):
        policy_pin.verify_pin(policy_path, KEY)


def test_install_writes_policy_and_verifiable_pin(tmp_path: Path) -> None:
    """Installing a document writes it as the policy file and a pin that verifies."""
    policy_path = tmp_path / "policy.json"
    document = _doc(("FIC102.SP",))
    pin_doc = policy_pin.install_policy_with_pin(_request(policy_path, document))
    assert json.loads(policy_path.read_text(encoding="utf-8")) == document
    assert policy_pin.verify_pin(policy_path, KEY) == pin_doc["digest"]
    assert (pin_doc["author"], pin_doc["approver"]) == ("alice", "bob")


def test_install_refuses_case_variant_self_approval_and_writes_nothing(tmp_path: Path) -> None:
    """A refused install leaves the existing policy file and its absent pin untouched."""
    policy_path = _policy_file(tmp_path)
    before = policy_path.read_bytes()
    signers = policy_pin.PinSigners("Alice", "alice")
    request = _request(policy_path, _doc(("FIC102.SP",)), signers=signers)
    with pytest.raises(policy_pin.PinError, match="author_equals_approver"):
        policy_pin.install_policy_with_pin(request)
    assert policy_path.read_bytes() == before
    assert not policy_pin.pin_path_for(policy_path).exists()


def test_install_refuses_short_key_before_writing(tmp_path: Path) -> None:
    """A short key is refused before any file is written."""
    policy_path = tmp_path / "policy.json"
    request = _request(policy_path, _doc(), key=b"a" * 31)
    with pytest.raises(policy_pin.PinError, match="key_too_short"):
        policy_pin.install_policy_with_pin(request)
    assert not policy_path.exists()


def test_crash_during_pin_write_restores_previous_policy_and_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash while writing the pin restores the previous policy and pin bytes."""
    policy_path = _policy_file(tmp_path)
    policy_pin.create_pin(policy_path, KEY, SIGNERS, NOW)
    old_policy = policy_path.read_bytes()
    old_pin = policy_pin.pin_path_for(policy_path).read_bytes()
    _fail_pin_writes(monkeypatch)
    with pytest.raises(policy_pin.PinError):
        policy_pin.install_policy_with_pin(_request(policy_path, _doc(("FIC102.SP",))))
    assert policy_path.read_bytes() == old_policy
    assert policy_pin.pin_path_for(policy_path).read_bytes() == old_pin
    assert policy_pin.verify_pin(policy_path, KEY)
    assert not list(tmp_path.glob(".*.tmp"))


def test_crash_during_first_install_leaves_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash during the first install leaves neither a policy file nor a pin behind."""
    policy_path = tmp_path / "policy.json"
    _fail_pin_writes(monkeypatch)
    with pytest.raises(policy_pin.PinError):
        policy_pin.install_policy_with_pin(_request(policy_path, _doc()))
    assert not policy_path.exists()
    assert not policy_pin.pin_path_for(policy_path).exists()


def test_forged_draft_document_is_refused_as_bad_signature(tmp_path: Path) -> None:
    """A draft whose document was edited after signing is refused and the policy is kept."""
    env = make_env(tmp_path, pinned_policy=True)
    _save(env, policy_doc("advisory"))
    draft = _read_draft(env)
    draft["document"] = _doc(("FIC102.SP",))
    _write_draft(env, draft)
    before = env.policy_path.read_bytes()
    cmd = _pin(env, "bob", {"digest": policy_file.policy_digest(draft["document"])})
    assert _reason(env, cmd) == "draft_bad_signature"
    assert env.policy_path.read_bytes() == before


def test_forged_draft_author_is_refused_as_bad_signature(tmp_path: Path) -> None:
    """A draft whose author was changed after signing is refused as a bad signature."""
    env = make_env(tmp_path, pinned_policy=True)
    digest = _save(env, policy_doc("advisory"))
    draft = _read_draft(env)
    draft["author"] = "carol"
    _write_draft(env, draft)
    cmd = _pin(env, "bob", {"digest": digest})
    assert _reason(env, cmd) == "draft_bad_signature"


def test_unsigned_draft_is_refused_as_bad_signature(tmp_path: Path) -> None:
    """A draft without a draft_sig field is refused as a bad signature."""
    env = make_env(tmp_path, pinned_policy=True)
    digest = _save(env, policy_doc("advisory"))
    draft = _read_draft(env)
    del draft["draft_sig"]
    _write_draft(env, draft)
    cmd = _pin(env, "bob", {"digest": digest})
    assert _reason(env, cmd) == "draft_bad_signature"


def test_pin_by_case_variant_of_author_is_refused(tmp_path: Path) -> None:
    """The two-person rule holds when the approver differs from the author only in case."""
    env = make_env(tmp_path, pinned_policy=True)
    digest = _save(env, policy_doc("advisory"))
    cmd = _pin(env, "Alice", {"digest": digest})
    assert _reason(env, cmd) == "author_equals_approver"


def test_pin_with_wrong_digest_is_refused(tmp_path: Path) -> None:
    """A pin naming a digest other than the reviewed draft's is refused as draft_changed."""
    env = make_env(tmp_path, pinned_policy=True)
    _save(env, policy_doc("advisory"))
    cmd = _pin(env, "bob", {"digest": ZERO_DIGEST})
    assert _reason(env, cmd) == "draft_changed"


def test_pin_without_digest_is_refused(tmp_path: Path) -> None:
    """A pin without a digest argument is refused as draft_changed."""
    env = make_env(tmp_path, pinned_policy=True)
    _save(env, policy_doc("advisory"))
    cmd = _pin(env, "bob", {})
    assert _reason(env, cmd) == "draft_changed"


def test_pin_with_digest_of_superseded_draft_is_refused(tmp_path: Path) -> None:
    """A digest from an earlier draft no longer approves after the draft was replaced."""
    env = make_env(tmp_path, pinned_policy=True)
    old_digest = _save(env, policy_doc("advisory"))
    _save(env, _doc(("FIC102.SP",)))
    before = env.policy_path.read_bytes()
    cmd = _pin(env, "bob", {"digest": old_digest})
    assert _reason(env, cmd) == "draft_changed"
    assert env.policy_path.read_bytes() == before


def test_pin_with_current_digest_writes_the_reviewed_document(tmp_path: Path) -> None:
    """A pin naming the current draft's digest installs exactly that reviewed document."""
    env = make_env(tmp_path, pinned_policy=True)
    document = _doc(("FIC102.SP",))
    digest = _save(env, document)
    cmd = _pin(env, "bob", {"digest": digest})
    assert outbox(env.root, cmd["id"])["ok"] is True
    assert json.loads(env.policy_path.read_text(encoding="utf-8")) == document
