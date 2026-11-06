"""Actor name normalisation, and self-approval refused across spellings of the proposer.

The normalisation must match the gateway's normalize_actor, so the API never lets a proposer
approve their own record by writing the name differently.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest
from crosscut_api.auth.actor_names import normalize_actor, same_actor
from test_tuning_proposal_routes import approve, propose, record_file
from tuning_fakes import FakeGateway, World, build_world, patch_report

NFD_NAME = unicodedata.normalize("NFD", "Zoë")
NFC_NAME = unicodedata.normalize("NFC", "Zoë")


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """A mini app with auth enabled over a fake gateway, and a fixed model report."""
    patch_report(monkeypatch)
    return build_world(tmp_path, FakeGateway())


@pytest.mark.parametrize(
    "spelling",
    ["Alice", " alice ", "ＡＬＩＣＥ", "ａｌｉｃｅ", "\t Alice \n"],
)
def test_spellings_normalise_to_one_name(spelling: str) -> None:
    assert normalize_actor(spelling) == "alice"
    assert same_actor(spelling, "Alice")


def test_nfd_and_nfc_compare_equal() -> None:
    assert NFD_NAME != NFC_NAME
    assert same_actor(NFD_NAME, NFC_NAME)
    assert normalize_actor(NFD_NAME) == normalize_actor(NFC_NAME)


def test_different_people_stay_different() -> None:
    assert not same_actor("alice", "alicia")
    assert not same_actor("eng1", "eng2")


@pytest.mark.parametrize("claimed", ["eng1", " ENG1 ", "ｅｎｇ１", "E N G 1"])
def test_self_approval_refused_across_spellings(world: World, claimed: str) -> None:
    created = propose(world)
    record = record_file(world, created["id"])
    _rewrite_proposer(world, created["id"], {**record, "created_by": claimed})
    res = approve(world, created["id"], "eng1")
    assert res.status_code == 403 and res.json()["detail"] == "self_approval"


def test_a_different_user_may_approve(world: World) -> None:
    created = propose(world)
    assert approve(world, created["id"], "eng2").status_code == 200


def _rewrite_proposer(world: World, proposal_id: str, record: dict[str, object]) -> None:
    """Store the record with a rewritten proposer, as a claimed spelling would be stored."""
    path = world.root / "_tuning" / "proposals" / f"{proposal_id}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
