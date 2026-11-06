"""Tests of the tuning proposal routes (ADR 014 step 6): lifecycle, roles, refusals, races.

The gateway is a fake that behaves like the real one where it matters (see tuning_fakes); the
real GatewayService is covered in test_tuning_proposal_live. The report is a fixed model report
(SIMC: gain 1.25, ti 100 s) so the tests need no data windows.
"""

from __future__ import annotations

import ast
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from crosscut_api import tuning_build, tuning_gateway, tuning_proposal_routes, tuning_store
from crosscut_api.gateway_client import _error_for
from fastapi.testclient import TestClient
from tuning_fakes import (
    BODY,
    KP,
    LOOP,
    START_VALUES,
    TI,
    FakeGateway,
    Session,
    World,
    build_world,
    patch_report,
    write_runtime,
)

PROPOSE = f"/loops/{LOOP}/tuning/proposals"


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """A mini app with auth enabled over a fake gateway, and a fixed model report."""
    patch_report(monkeypatch)
    return build_world(tmp_path, FakeGateway())


def record_file(world: World, proposal_id: str) -> dict[str, Any]:
    """The stored record as written on disk."""
    path = world.root / "_tuning" / "proposals" / f"{proposal_id}.json"
    stored: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return stored


def propose(world: World, user: str = "eng1", **changes: Any) -> dict[str, Any]:
    """Create a proposal as ``user`` and return the response body (expects 201)."""
    response = Session(world, user).call("POST", PROPOSE, {**BODY, **changes})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def approve(world: World, proposal_id: str, user: str = "eng2") -> Any:
    """Approve as ``user`` and return the response."""
    return Session(world, user).call("POST", f"/tuning/proposals/{proposal_id}/approve")


# --- lifecycle -------------------------------------------------------------------------------


def test_propose_approve_roll_back_lifecycle(world: World) -> None:
    created = propose(world)
    assert created["status"] == "queued" and created["created_by"] == "eng1"
    assert created["decision"] == {"accepted": True, "reason_code": "queued", "clamped_value": None}
    assert len(created["gateway_key"]) == 64 and created["review"] is None
    gain, ti = created["items"]
    assert (gain["from"], gain["to"]) == (0.5, pytest.approx(1.25))
    assert (ti["from"], ti["to"]) == (200.0, pytest.approx(100.0))
    sent = world.gateway.sent[0]
    assert sent["proposer"] == "eng1" and sent["rollback_of"] is None
    assert sent["items"][0]["vendor_form"] == "siemens_pid_compact"
    assert record_file(world, created["id"])["status"] == "queued"

    approved = approve(world, created["id"])
    assert approved.status_code == 200, approved.text
    applied = approved.json()["applied"]
    assert approved.json()["status"] == "applied" and applied["approver"] == "eng2"
    assert applied["from_read"] == START_VALUES
    assert applied["to_read"] == {KP: pytest.approx(1.25), TI: pytest.approx(100.0)}
    assert world.gateway.apply_count == 1

    back = Session(world, "eng1").call("POST", f"/tuning/proposals/{created['id']}/rollback")
    assert back.status_code == 201, back.text
    assert back.json()["rollback_of"] == created["id"] and back.json()["status"] == "queued"
    assert back.json()["source"]["method"] == "rollback"
    assert approve(world, back.json()["id"], "lead1").status_code == 200
    assert world.gateway.values == START_VALUES


def test_list_and_get_filter_by_loop_and_status(world: World) -> None:
    first = propose(world)
    second = propose(world)
    approve(world, second["id"])
    session = Session(world, "view1")
    everything = session.call("GET", "/tuning/proposals").json()
    assert {r["id"] for r in everything} == {first["id"], second["id"]}
    queued = session.call("GET", "/tuning/proposals?status=queued").json()
    assert [r["id"] for r in queued] == [first["id"]]
    assert session.call("GET", f"/tuning/proposals?loop_id={LOOP}").json() == everything
    assert session.call("GET", "/tuning/proposals?loop_id=other").json() == []
    assert session.call("GET", f"/tuning/proposals/{second['id']}").json()["status"] == "applied"


def test_unknown_and_malformed_ids_are_404(world: World) -> None:
    session = Session(world, "eng1")
    for path in (
        "/tuning/proposals/not-a-uuid",
        f"/tuning/proposals/{'1' * 8}-{'1' * 4}-{'1' * 4}-{'1' * 4}-{'1' * 12}",
    ):
        assert session.call("GET", path).status_code == 404
        assert session.call("POST", f"{path}/approve").status_code == 404
        assert session.call("POST", f"{path}/reject").status_code == 404
        assert session.call("POST", f"{path}/rollback").status_code == 404


# --- roles -----------------------------------------------------------------------------------


def test_operator_cannot_propose_or_approve_but_can_reject(world: World) -> None:
    operator = Session(world, "op1")
    assert operator.call("POST", PROPOSE, BODY).status_code == 403
    created = propose(world)
    assert operator.call("POST", f"/tuning/proposals/{created['id']}/approve").status_code == 403
    assert operator.call("POST", f"/tuning/proposals/{created['id']}/rollback").status_code == 403
    rejected = operator.call("POST", f"/tuning/proposals/{created['id']}/reject")
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert world.gateway.pending == {}
    assert world.gateway.apply_count == 0


def test_viewer_may_read_only(world: World) -> None:
    created = propose(world)
    viewer = Session(world, "view1")
    assert viewer.call("GET", "/tuning/proposals").status_code == 200
    assert viewer.call("GET", f"/tuning/proposals/{created['id']}").status_code == 200
    assert viewer.call("POST", PROPOSE, BODY).status_code == 403
    for action in ("approve", "rollback"):
        assert viewer.call("POST", f"/tuning/proposals/{created['id']}/{action}").status_code == 403
    assert viewer.call("POST", f"/tuning/proposals/{created['id']}/reject").status_code == 200


def test_self_approval_is_refused_and_a_second_engineer_or_lead_approves(world: World) -> None:
    created = propose(world)
    own = approve(world, created["id"], "eng1")
    assert own.status_code == 403 and own.json()["detail"] == "self_approval"
    assert record_file(world, created["id"])["status"] == "queued"
    assert world.gateway.apply_count == 0
    second = propose(world)
    assert approve(world, created["id"], "lead1").status_code == 200
    assert approve(world, second["id"], "eng2").status_code == 409  # the first one retuned it


def test_auth_disabled_mode_behaves_like_other_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_report(monkeypatch)
    world = build_world(tmp_path, FakeGateway(), auth=False)
    client = TestClient(world.app)
    created = client.post(PROPOSE, json=BODY)
    assert created.status_code == 201 and created.json()["created_by"] == "local-dev"
    again = client.post(f"/tuning/proposals/{created.json()['id']}/approve")
    assert again.status_code == 403 and again.json()["detail"] == "self_approval"
    assert client.get("/tuning/proposals").status_code == 200


def test_gateway_permission_refusal_is_403_and_closes_the_draft(world: World) -> None:
    assert isinstance(_error_for("service_cannot_propose_tuning"), PermissionError)

    def refuse(args: dict, actor: object = None) -> dict:
        raise PermissionError("service_cannot_propose_tuning")

    world.gateway.propose_params = refuse  # type: ignore[method-assign]
    assert post_as_engineer(world).status_code == 403
    stored = Session(world, "view1").call("GET", "/tuning/proposals").json()
    assert [r["status"] for r in stored] == ["refused:forbidden"]


# --- refusals before anything is sent ----------------------------------------------------------


def post_as_engineer(world: World, body: dict[str, Any] | None = None) -> Any:
    """POST the standard proposal body as an engineer."""
    return Session(world, "eng1").call("POST", PROPOSE, BODY if body is None else body)


def test_no_running_kpi_job_is_409(world: World) -> None:
    write_runtime(world.root, jobs=False)
    response = post_as_engineer(world)
    assert response.status_code == 409 and response.json()["detail"] == "no_kpi_job"
    write_runtime(world.root, running=False)
    assert post_as_engineer(world).json()["detail"] == "no_kpi_job"
    write_runtime(world.root, status="error")
    assert post_as_engineer(world).json()["detail"] == "no_kpi_job"
    assert world.gateway.sent == []


def test_live_values_unavailable_is_409(world: World) -> None:
    world.connector.fail = True
    response = post_as_engineer(world)
    assert response.status_code == 409 and response.json()["detail"] == "no_live_values"
    world.connector.fail, world.connector.quality = False, 2
    assert post_as_engineer(world).json()["detail"] == "no_live_values"
    world.connector.quality, world.connector.values = 0, {KP: 0.5}
    assert post_as_engineer(world).json()["detail"] == "no_live_values"
    assert world.gateway.sent == [] and not (world.root / "_tuning" / "proposals").exists()


def test_loop_without_parameter_targets_is_409(world: World) -> None:
    world.gateway.live_policy = lambda: {"document": {"targets": {}}, "pin": {}}  # type: ignore[method-assign]
    assert post_as_engineer(world).json()["detail"] == "no_param_targets"


def test_unknown_loop_is_404_and_gateway_down_is_503(world: World) -> None:
    assert (
        Session(world, "eng1").call("POST", "/loops/NOPE/tuning/proposals", BODY).status_code == 404
    )
    world.provider.up = False
    assert post_as_engineer(world).status_code == 503


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"vendor_form": "nobody"}, "unknown_vendor_form"),
        ({"method": "amigo_pid"}, "missing_target"),
    ],
)
def test_proposal_refused_is_422_with_the_code(world: World, changes: dict, code: str) -> None:
    response = post_as_engineer(world, {**BODY, **changes})
    assert response.status_code == 422 and response.json()["detail"]["code"] == code
    assert world.gateway.sent == []


def test_blocked_report_and_no_op_are_422(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_report(monkeypatch, blocked="stiction suspected")
    assert post_as_engineer(world).json()["detail"]["code"] == "blocked"
    patch_report(monkeypatch)
    world.connector.values = {KP: 1.25, TI: 100.0}
    assert post_as_engineer(world).json()["detail"]["code"] == "no_op"


def test_body_needs_exactly_one_window(world: World) -> None:
    both = {**BODY, "history": {"start": "2026-11-05T00:00:00Z", "end": "2026-11-05T06:00:00Z"}}
    assert post_as_engineer(world, both).status_code == 422
    neither = {k: v for k, v in BODY.items() if k != "dataset_id"}
    assert post_as_engineer(world, neither).status_code == 422
    assert post_as_engineer(world, {**BODY, "method": "pid"}).status_code == 422


def test_history_window_without_history_store_is_422(tmp_path: Path) -> None:
    world = build_world(tmp_path, FakeGateway())  # the real report builder, no history file
    body = {k: v for k, v in BODY.items() if k != "dataset_id"}
    body["history"] = {"start": "2026-11-05T00:00:00Z", "end": "2026-11-05T06:00:00Z"}
    response = post_as_engineer(world, body)
    assert response.status_code == 422 and response.json()["detail"] == "no_history"


# --- the gateway decides ---------------------------------------------------------------------


def test_gateway_refusal_is_kept_in_the_record(world: World) -> None:
    world.gateway.refuse_propose = "loop_busy"
    body = propose(world)
    assert body["status"] == "refused:loop_busy" and body["gateway_key"] is None
    assert body["decision"]["reason_code"] == "loop_busy"
    assert approve(world, body["id"]).status_code == 409


def test_accepted_but_not_queued_is_not_approvable(world: World) -> None:
    world.gateway.propose_params = lambda args, actor=None: {  # type: ignore[method-assign]
        "accepted": True,
        "reason_code": "dry_run",
    }
    body = propose(world)
    assert body["status"] == "refused:dry_run"
    assert approve(world, body["id"]).json()["detail"] == "not_queued"


def test_refusal_at_approve_closes_the_record_and_blocks_rollback(world: World) -> None:
    created = propose(world)
    world.gateway.values[KP] = 0.9  # someone retuned the loop meanwhile
    refused = approve(world, created["id"])
    assert refused.status_code == 409 and refused.json()["detail"] == "from_mismatch"
    assert record_file(world, created["id"])["status"] == "refused:from_mismatch"
    again = Session(world, "eng1").call("POST", f"/tuning/proposals/{created['id']}/rollback")
    assert again.status_code == 409 and again.json()["detail"] == "not_applied"


def test_key_lost_in_the_gateway_expires_the_record(world: World) -> None:
    created = propose(world)
    world.gateway.pending.clear()  # restart / kill: pending sets are lost
    response = approve(world, created["id"])
    assert response.status_code == 404
    assert record_file(world, created["id"])["status"] == "expired"


def test_queued_record_past_expiry_and_gone_from_the_gateway_expires_on_get(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_report(monkeypatch)
    skew = [0.0]
    world = build_world(tmp_path, FakeGateway(), clock=lambda: time.time() + skew[0])
    created = propose(world)
    viewer = Session(world, "view1")
    assert viewer.call("GET", f"/tuning/proposals/{created['id']}").json()["status"] == "queued"
    world.gateway.pending.clear()
    skew[0] = 9 * 3600.0
    shown = viewer.call("GET", f"/tuning/proposals/{created['id']}").json()
    assert shown["status"] == "expired"
    assert record_file(world, created["id"])["status"] == "expired"


# --- status monotonicity -----------------------------------------------------------------------


def test_statuses_never_regress_and_terminal_states_stay(world: World) -> None:
    created, other = propose(world), propose(world)
    assert approve(world, created["id"]).status_code == 200
    lead = Session(world, "lead1")
    again = approve(world, created["id"], "lead1")
    assert again.status_code == 409 and again.json()["detail"] == "not_queued"
    assert (
        lead.call("POST", f"/tuning/proposals/{created['id']}/reject").json()["detail"]
        == "not_open"
    )
    assert record_file(world, created["id"])["status"] == "applied"
    assert lead.call("POST", f"/tuning/proposals/{other['id']}/reject").status_code == 200
    assert approve(world, other["id"]).json()["detail"] == "not_queued"
    assert lead.call("POST", f"/tuning/proposals/{other['id']}/reject").status_code == 409
    assert record_file(world, other["id"])["status"] == "rejected"
    assert world.gateway.apply_count == 1


def test_concurrent_approve_applies_once(world: World) -> None:
    created = propose(world)
    world.gateway.apply_delay_s = 0.15
    sessions = [Session(world, "eng2"), Session(world, "lead1")]
    results: list[int] = []

    def go(session: Session) -> None:
        results.append(
            session.call("POST", f"/tuning/proposals/{created['id']}/approve").status_code
        )

    threads = [threading.Thread(target=go, args=(s,)) for s in sessions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert sorted(results) == [200, 409]
    assert world.gateway.apply_count == 1
    assert record_file(world, created["id"])["status"] == "applied"


# --- review file and external change ----------------------------------------------------------


def write_review(world: World, proposal_id: str, verdict: str, final: bool = True) -> None:
    """Write the review file the runtime job would write."""
    review = {"verdict": verdict, "t": "2026-11-06T12:00:00Z", "reasons": ["x"]}
    status = f"reviewed:{verdict}" if final else "reviewing"
    document = {"proposal_id": proposal_id, "version": 1, "final": final, "status": status,
                "review": review}  # fmt: skip
    path = world.root / "_tuning" / "proposals" / f"{proposal_id}.review.json"
    path.write_text(json.dumps(document), encoding="utf-8")


def test_status_is_derived_from_the_review_file_and_the_record_is_not_touched(world: World) -> None:
    created = propose(world)
    approve(world, created["id"])
    before = (world.root / "_tuning" / "proposals" / f"{created['id']}.json").read_bytes()
    viewer = Session(world, "view1")
    write_review(world, created["id"], "worse_early", final=False)
    early = viewer.call("GET", f"/tuning/proposals/{created['id']}").json()
    assert early["status"] == "reviewing" and early["rollback_recommended"] is True
    write_review(world, created["id"], "worse")
    final = viewer.call("GET", f"/tuning/proposals/{created['id']}").json()
    assert final["status"] == "reviewed:worse" and final["review"]["verdict"] == "worse"
    assert viewer.call("GET", "/tuning/proposals?status=reviewed").json()[0]["id"] == created["id"]
    listed = viewer.call("GET", "/tuning/proposals").json()
    assert listed[0]["status"] == "reviewed:worse"
    after = (world.root / "_tuning" / "proposals" / f"{created['id']}.json").read_bytes()
    assert after == before
    rolled = Session(world, "eng1").call("POST", f"/tuning/proposals/{created['id']}/rollback")
    assert rolled.status_code == 201


def test_external_change_marks_the_applied_record_invalid_on_get(world: World) -> None:
    created = propose(world)
    approve(world, created["id"])
    viewer = Session(world, "view1")
    assert (
        "invalid" not in viewer.call("GET", f"/tuning/proposals/{created['id']}").json()["applied"]
    )
    world.gateway.external_change(KP, 3.0)
    shown = viewer.call("GET", f"/tuning/proposals/{created['id']}").json()
    assert shown["applied"]["invalid"] == "param_changed_externally"
    assert shown["status"] == "applied"
    stored = record_file(world, created["id"])
    assert stored["applied"]["invalid"] == "param_changed_externally"
    assert viewer.call("GET", f"/tuning/proposals/{created['id']}").json() == shown


# --- pure helpers and guards -------------------------------------------------------------------


def test_new_modules_do_not_import_the_gateway() -> None:
    for module in (tuning_build, tuning_gateway, tuning_proposal_routes, tuning_store):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [n for n in names if n.split(".")[0] in ("crosscut_gateway", "asyncua")]


def test_status_code_mapping_of_the_decision() -> None:
    assert tuning_gateway.decision_status({"accepted": True, "reason_code": "queued"}) == "queued"
    assert tuning_gateway.decision_status({"accepted": False, "reason_code": "From-Mismatch"}) == (
        "refused:from_mismatch"
    )
    assert tuning_gateway.decision_status({"accepted": True, "reason_code": "ok"}) == (
        "refused:advisory_only"
    )
