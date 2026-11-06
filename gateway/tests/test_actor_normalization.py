"""Actor-name normalisation and validation: self-approval cannot be respelled around.

Covers normalize_actor (NFKC, strip, casefold), is_valid_actor_name (control, format and
mixed-script names refused as malformed), the engine-level self-approval check, the policy
author != approver paths, and that audit records keep the claimed spelling.
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import pytest
from auth_helpers import make_env, policy_doc, rejected_reason, send
from crosscut_gateway import policy_pin
from crosscut_gateway.actor import ActorContext, is_valid_actor_name, normalize_actor
from crosscut_gateway.policy import proposal_key
from test_engine_hardening import make
from test_gateway_scenarios import SimPlant, proposal
from test_policy_pin_hardening import KEY, _pin, _policy_file, _reason, _save

NFC = unicodedata.normalize("NFC", "rené")
NFD = unicodedata.normalize("NFD", "rené")
SPELLINGS = ("alice", "Alice", "ALICE", " alice", "alice ", "\u2003alice\t", "\uff41lice")


@pytest.mark.parametrize("spelling", SPELLINGS)
def test_normalize_actor_maps_spellings_to_one_form(spelling: str) -> None:
    """Case, surrounding whitespace and compatibility forms all normalise to 'alice'."""
    assert normalize_actor(spelling) == "alice"


def test_normalize_actor_unifies_nfc_and_nfd() -> None:
    """Canonically equivalent Unicode spellings compare equal."""
    assert NFC != NFD
    assert normalize_actor(NFC) == normalize_actor(NFD)


@pytest.mark.parametrize(
    "name", ["alice", "Alice Smith", "rené", NFD, "o.perator-1", "Иван", "\u0391lice"[1:]]
)
def test_valid_actor_names_are_accepted(name: str) -> None:
    """Ordinary single-script names are valid."""
    assert is_valid_actor_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "ali\x00ce",
        "ali\nce",
        "ali\u200bce",
        "ali\u202ece",
        "\ufeffalice",
        "ali\u2028ce",
        "ali\ud800ce",
        "ali\ue000ce",
        "\u0430dmin",
        "adm\u0456n",
        "\u03b1lice",
    ],
)
def test_malformed_actor_names_are_refused(name: str) -> None:
    """Control, zero-width, bidi, private-use and mixed-script lookalike names are invalid."""
    assert not is_valid_actor_name(name)


def test_non_string_actor_is_invalid() -> None:
    """Only strings can be actor names."""
    assert not is_valid_actor_name(None)
    assert not is_valid_actor_name(7)


@pytest.mark.parametrize("bad", ["ali\u200bce", "\u0430dmin", "ali\x07ce"])
def test_gate_refuses_envelope_with_malformed_actor(tmp_path: Path, bad: str) -> None:
    """A correctly signed envelope with a malformed actor is refused as malformed."""
    env = make_env(tmp_path, mode="confirm")
    cmd = send(env, "set_mode", {"mode": "off"}, actor=bad, roles=("lead",))
    assert rejected_reason(env.root, cmd["id"]) == "malformed"


@pytest.mark.parametrize(
    ("proposer", "approver"),
    [("alice", "ALICE"), ("alice", "\uff41lice"), ("Alice", " alice\t"), (NFC, NFD)],
)
def test_engine_refuses_self_approval_in_any_spelling(proposer: str, approver: str) -> None:
    """The engine itself (defence in depth) refuses a respelled self-approval."""
    plant = SimPlant()
    gw = make("confirm", plant)
    gw.tick(0)
    queued = proposal(55.0)
    gw.propose(queued, actor_ctx=ActorContext(actor=proposer, roles=("engineer",)))
    decision = gw.approve(
        proposal_key(queued), actor_ctx=ActorContext(actor=approver, roles=("lead",))
    )
    assert decision.reason_code == "self_approval"
    assert plant.writes == []
    recorded = [r["actor"] for r in gw.audit_records() if r["event"] == "self_approval"]
    assert recorded == [approver]


def test_engine_still_allows_a_different_person_to_approve() -> None:
    """Normalisation must not merge distinct people."""
    plant = SimPlant()
    gw = make("confirm", plant)
    gw.tick(0)
    queued = proposal(55.0)
    gw.propose(queued, actor_ctx=ActorContext(actor="alice", roles=("engineer",)))
    decision = gw.approve(proposal_key(queued), actor_ctx=ActorContext(actor="alicia"))
    assert decision.accepted
    assert len(plant.writes) == 1


@pytest.mark.parametrize("approver", ["Alice", "alice ", "\uff21lice"])
def test_policy_pin_command_refuses_author_respelling(tmp_path: Path, approver: str) -> None:
    """policy_pin by a respelling of the draft author is refused."""
    env = make_env(tmp_path, pinned_policy=True)
    digest = _save(env, policy_doc("advisory"))
    assert _reason(env, _pin(env, approver, {"digest": digest})) == "author_equals_approver"


def test_pin_signers_refuse_nfkc_equivalent_names(tmp_path: Path) -> None:
    """create_pin refuses author and approver that are NFKC-equivalent."""
    policy_path = _policy_file(tmp_path)
    signers = policy_pin.PinSigners(NFC, NFD)
    with pytest.raises(policy_pin.PinError, match="author_equals_approver"):
        policy_pin.create_pin(policy_path, KEY, signers, datetime.now(UTC))
