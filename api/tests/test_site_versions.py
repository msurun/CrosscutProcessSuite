"""Versioned site catalogue (#165): draft vs published, immutable versions, diff, approval, audit.

The app stamps the actor from the ``X-User`` header so two engineers can be told apart.
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.auth.actor import ActorContext
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.site_routes import build_site_router
from crosscut_connectors.site import load_site
from crosscut_connectors.site_diff import diff_sites
from crosscut_connectors.site_versions import (
    VersionCorruptError,
    VersionMissingError,
    get_version,
    publish_document,
    site_lock,
)
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/generic_concentrator/_site/site.json"
ACTIVE_LOOP = "CR1.CSS"  # MV of controller CR1.SUP in the example catalogue
QUIET_LOOP = "COND1.PH"  # bound to no controller


def _app(root: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(build_site_router(root))

    @app.middleware("http")
    async def stamp(request: Request, call_next: Any) -> Any:
        name = request.headers.get("X-User", "eng1")
        request.state.actor = ActorContext(name, ("engineer",), "s", "127.0.0.1", False, None)
        return await call_next(request)

    return app


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def client(root: Path) -> TestClient:
    return TestClient(_app(root))


@pytest.fixture
def base() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return document


def _as(client: TestClient, user: str) -> dict[str, str]:
    return {"X-User": user}


def _publish_base(client: TestClient, base: dict[str, Any]) -> None:
    assert client.put("/site", json=base).status_code == 200
    assert client.post("/site/publish", json={"note": "base"}).status_code == 200


def _controller_on(root: Path, controller_id: str = "CR1.SUP") -> None:
    folder = root / "_runtime" / "controllers"
    folder.mkdir(parents=True)
    (folder / f"{controller_id}.json").write_text(json.dumps({"state": "on"}), encoding="utf-8")


def _edit_loop(base: dict[str, Any], loop_id: str) -> dict[str, Any]:
    doc = copy.deepcopy(base)
    next(loop for loop in doc["loops"] if loop["id"] == loop_id)["type"] = "changed_type"
    return doc


def test_edit_goes_to_draft_and_runtime_reads_published(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    edited = copy.deepcopy(base)
    edited["site"]["name"] = "Renamed"
    client.put("/site", json=edited)
    assert client.get("/site").json()["site"]["name"] == "Renamed"  # working copy
    assert load_site(root)["site"]["name"] == base["site"]["name"]  # what runtime reads
    status = client.get("/site/status").json()
    assert status["has_draft"] and status["draft_changed"] and status["published_version"] == 1
    client.post("/site/publish", json={"note": "rename"})
    assert load_site(root)["site"]["name"] == "Renamed"
    assert not client.get("/site/status").json()["has_draft"]


def test_versions_are_numbered_immutable_and_carry_metadata(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    edited = _edit_loop(base, QUIET_LOOP)
    client.put("/site", json=edited)
    meta = client.post("/site/publish", json={"note": "type"}).json()
    assert meta["version"] == 2 and meta["author"] == "eng1" and meta["note"] == "type"
    assert meta["approver"] is None and len(meta["sha256"]) == 64 and meta["time"]
    versions = client.get("/site/versions").json()["versions"]
    assert [v["version"] for v in versions] == [2, 1]
    assert client.get("/site/versions/1").json()["document"] == base
    stored = root / "_site" / "versions" / "v0001.json"
    stored.write_text("{}", encoding="utf-8")  # tampering is detected, not served
    assert client.get("/site/versions/1").status_code == 409  # corrupt, not "missing"
    assert client.get("/site/versions/9").status_code == 404
    with pytest.raises(VersionCorruptError, match="sha256"):
        get_version(root, 1)
    with pytest.raises(VersionMissingError):
        get_version(root, 9)


def test_publish_needs_a_change_and_a_draft(client: TestClient, base: dict[str, Any]) -> None:
    assert client.post("/site/publish").json()["detail"] == "no_draft"
    _publish_base(client, base)
    client.put("/site", json=base)
    assert client.post("/site/publish").json()["detail"] == "no_changes"


def test_diff_lists_added_removed_and_changed_fields(
    client: TestClient, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    edited = _edit_loop(base, QUIET_LOOP)
    edited["tags"].append({**base["tags"][0], "id": "NEW.TAG"})
    assert client.put("/site", json=edited).status_code == 200
    diff = client.get("/site/diff", params={"a": "published", "b": "draft"}).json()
    loops = diff["sections"]["loops"]
    assert loops["changed"] == [
        {
            "id": QUIET_LOOP,
            "fields": [{"field": "type", "before": "ph", "after": "changed_type"}],
        }
    ]
    assert diff["sections"]["tags"]["added"] == ["NEW.TAG"]
    assert diff["sections"]["tags"]["removed"] == []
    reverse = diff_sites(edited, base)["sections"]["tags"]
    assert reverse["removed"] == ["NEW.TAG"] and reverse["added"] == []
    assert "equipment" not in diff["sections"]


def test_diff_between_versions_and_of_equal_documents(base: dict[str, Any]) -> None:
    assert diff_sites(base, copy.deepcopy(base)) == {"sections": {}, "empty": True}
    other = copy.deepcopy(base)
    other["site"]["timezone"] = "Europe/Warsaw"
    fields = diff_sites(base, other)["sections"]["site"]["fields"]
    assert fields == [{"field": "timezone", "before": "UTC", "after": "Europe/Warsaw"}]


def test_change_without_active_writes_is_published_by_one_engineer(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    _controller_on(root)
    client.put("/site", json=_edit_loop(base, QUIET_LOOP))
    assert client.post("/site/publish").status_code == 200


def test_change_to_loop_of_running_controller_needs_second_engineer(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    _controller_on(root)
    client.put("/site", json=_edit_loop(base, ACTIVE_LOOP))
    response = client.post("/site/publish", json={"note": "css"})
    assert response.status_code == 202
    assert f"loop:{ACTIVE_LOOP}" in response.json()["reasons"]
    assert load_site(root) == base and client.get("/site/status").json()["pending"]
    assert client.post("/site/publish").json()["detail"] == "pending_exists"
    own = client.post("/site/publish/approve")
    assert own.status_code == 403 and own.json()["detail"] == "self_approval"
    approved = client.post("/site/publish/approve", headers=_as(client, "eng2"))
    assert approved.status_code == 200
    assert approved.json()["author"] == "eng1" and approved.json()["approver"] == "eng2"
    assert load_site(root)["loops"][1]["type"] == "changed_type"
    assert client.get("/site/status").json()["pending"] is None


def test_same_change_is_free_while_the_controller_is_not_running(
    client: TestClient, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    client.put("/site", json=_edit_loop(base, ACTIVE_LOOP))
    assert client.post("/site/publish").status_code == 200


def test_controller_change_needs_approval_when_running(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    _controller_on(root)
    edited = copy.deepcopy(base)
    edited["controllers"][0]["variables"][0]["limits"]["move_max"] = 5
    client.put("/site", json=edited)
    response = client.post("/site/publish")
    assert response.status_code == 202 and response.json()["reasons"] == ["controller:CR1.SUP"]


def test_gateway_target_in_writing_mode_makes_a_loop_active(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    gateway = root / "_gateway"
    gateway.mkdir()
    state = {"mode": "confirm", "targets": {"COND1.PH.OUT": "enabled"}}
    (gateway / "state.json").write_text(json.dumps(state), encoding="utf-8")
    client.put("/site", json=_edit_loop(base, QUIET_LOOP))
    assert client.post("/site/publish").status_code == 202
    client.post("/site/publish/reject")
    state["mode"] = "advisory"
    (gateway / "state.json").write_text(json.dumps(state), encoding="utf-8")
    assert client.post("/site/publish").status_code == 200


def test_unreadable_gateway_state_fails_closed(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    (root / "_gateway").mkdir()
    (root / "_gateway" / "state.json").write_text("not json", encoding="utf-8")
    client.put("/site", json=_edit_loop(base, QUIET_LOOP))
    assert client.post("/site/publish").status_code == 202


def test_reject_keeps_the_draft_and_approval_of_stale_base_is_refused(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    _controller_on(root)
    client.put("/site", json=_edit_loop(base, ACTIVE_LOOP))
    client.post("/site/publish")
    rejected = client.post("/site/publish/reject", json={"reason": "no"}, headers=_as(client, "e2"))
    assert rejected.status_code == 200 and client.get("/site/status").json()["has_draft"]
    client.post("/site/publish")
    (root / "_site" / "site.json").write_text(json.dumps({**base, "site": {"name": "x"}}))
    stale = client.post("/site/publish/approve", headers=_as(client, "eng2"))
    assert stale.status_code == 409 and stale.json()["detail"] == "stale_base"


def test_every_step_is_audited_in_an_intact_chain(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    _controller_on(root)
    client.put("/site", json=_edit_loop(base, ACTIVE_LOOP))
    client.post("/site/publish", json={"note": "css"})
    client.post("/site/publish/reject", json={"reason": "later"}, headers=_as(client, "eng2"))
    client.post("/site/publish")
    client.post("/site/publish/approve", headers=_as(client, "eng2"))
    audit = AuthAudit(root / "_site" / "versions" / "audit.jsonl")
    events = [(r["event"], r["actor"]) for r in audit.records()]
    assert events == [
        ("draft_save", "eng1"),
        ("publish", "eng1"),
        ("draft_save", "eng1"),
        ("publish_requested", "eng1"),
        ("publish_rejected", "eng2"),
        ("publish_requested", "eng1"),
        ("publish", "eng2"),
        ("publish_approved", "eng2"),
    ]
    assert audit.verify()


def test_invalid_draft_is_refused_and_discard_removes_it(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    broken = _edit_loop(base, QUIET_LOOP)
    broken["loops"][0]["pv"] = "NO.SUCH.TAG"
    assert client.put("/site", json=broken).status_code == 422
    client.put("/site", json=base)
    assert client.delete("/site/draft").status_code == 200
    assert not (root / "_site" / "draft.json").exists()


def _pending_request(client: TestClient, root: Path, base: dict[str, Any]) -> dict[str, Any]:
    _publish_base(client, base)
    _controller_on(root)
    client.put("/site", json=_edit_loop(base, ACTIVE_LOOP))
    assert client.post("/site/publish").status_code == 202
    pending: dict[str, Any] = json.loads(
        (root / "_site" / "pending_publish.json").read_text(encoding="utf-8")
    )
    return pending


def test_pending_publish_is_bound_to_its_document(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    pending = _pending_request(client, root, base)
    assert len(pending["document_sha256"]) == 64
    pending["document"]["site"]["name"] = "SWAPPED"  # tampering with the file after the request
    (root / "_site" / "pending_publish.json").write_text(json.dumps(pending), encoding="utf-8")
    refused = client.post("/site/publish/approve", headers=_as(client, "eng2"))
    assert refused.status_code == 409 and refused.json()["detail"] == "pending_modified"
    assert load_site(root) == base


def test_draft_cannot_change_while_a_publish_is_pending(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _pending_request(client, root, base)
    put = client.put("/site", json=base)
    assert put.status_code == 409 and put.json()["detail"] == "pending_exists"
    assert client.put("/config/site/site", json=base).status_code in (404, 405)
    assert client.delete("/site/draft").status_code == 409


def test_renaming_the_out_tag_of_an_active_loop_needs_approval(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    _controller_on(root)
    edited = copy.deepcopy(base)
    tag = next(t for t in edited["tags"] if t["id"] == "CR1.CSS.OUT")
    tag["unit"] = "%" if tag.get("unit") != "%" else "pct"  # loop entry itself is unchanged
    assert client.put("/site", json=edited).status_code == 200
    response = client.post("/site/publish")
    assert response.status_code == 202 and "loop:CR1.CSS" in response.json()["reasons"]


def test_equipment_membership_change_reaches_the_loops_it_owns(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    _controller_on(root)
    edited = copy.deepcopy(base)
    owner = next(e for e in edited["equipment"] if "CR1.CSS.OUT" in e.get("tags", []))
    owner["name"] = "Renamed equipment"
    assert client.put("/site", json=edited).status_code == 200
    response = client.post("/site/publish")
    assert response.status_code == 202 and "loop:CR1.CSS" in response.json()["reasons"]


@pytest.mark.parametrize("content", ["not json", "[]", "{}"])
def test_unreadable_controller_record_counts_as_running(
    client: TestClient, root: Path, base: dict[str, Any], content: str
) -> None:
    _publish_base(client, base)
    folder = root / "_runtime" / "controllers"
    folder.mkdir(parents=True)
    (folder / "CR1.SUP.json").write_text(content, encoding="utf-8")
    client.put("/site", json=_edit_loop(base, ACTIVE_LOOP))
    assert client.post("/site/publish").status_code == 202


def test_orphan_version_file_does_not_block_the_next_publish(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    # an orphan document of a crashed publish
    (root / "_site" / "versions" / "v0002.json").write_text("{}", encoding="utf-8")
    client.put("/site", json=_edit_loop(base, QUIET_LOOP))
    meta = client.post("/site/publish").json()
    assert meta["version"] == 3
    assert [v["version"] for v in client.get("/site/versions").json()["versions"]] == [3, 1]


def test_a_held_lock_refuses_changes_and_concurrent_publishes_give_one_winner(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    client.put("/site", json=_edit_loop(base, QUIET_LOOP))
    with site_lock(root):
        busy = client.post("/site/publish")
        assert busy.status_code == 409 and busy.json()["detail"] == "busy"
        assert client.put("/site", json=base).status_code == 409
    codes: list[int] = []
    gate = threading.Barrier(2)

    def go() -> None:
        other = TestClient(_app(root))
        gate.wait()
        codes.append(other.post("/site/publish").status_code)

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200, 409]
    assert [v["version"] for v in client.get("/site/versions").json()["versions"]] == [2, 1]
    assert client.get("/site/status").json()["published_matches_version"] is True
    assert not (root / "_site" / ".lock").exists()


@pytest.mark.parametrize("spelling", ["ENG1", " eng1 "])
def test_other_spellings_of_the_requester_are_not_a_second_user(
    client: TestClient, root: Path, base: dict[str, Any], spelling: str
) -> None:
    _pending_request(client, root, base)
    refused = client.post("/site/publish/approve", headers=_as(client, spelling))
    assert refused.status_code == 403 and refused.json()["detail"] == "self_approval"


def test_failed_publish_is_audited_and_the_audit_is_hash_chained(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    _publish_base(client, base)
    client.put("/site", json=_edit_loop(base, QUIET_LOOP))
    (root / "_site" / "versions" / "v0002.json").write_text("{}", encoding="utf-8")
    # force a collision: next number is 3, so make publish_document itself fail on validation
    draft_path = root / "_site" / "draft.json"
    broken = json.loads(draft_path.read_text(encoding="utf-8"))
    broken["loops"][0]["pv"] = "NO.SUCH.TAG"
    draft_path.write_text(json.dumps(broken), encoding="utf-8")
    refused = client.post("/site/publish")
    assert refused.status_code == 409
    audit = AuthAudit(root / "_site" / "versions" / "audit.jsonl")
    last = audit.records()[-1]
    assert last["event"] == "publish_failed" and "unknown tag" in last["reason"]
    assert audit.verify()


def test_publish_document_refuses_to_overwrite_a_version(root: Path, base: dict[str, Any]) -> None:
    publish_document(root, base, "a", "n")
    assert publish_document(root, base, "a", "n")["version"] == 2
