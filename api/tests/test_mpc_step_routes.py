"""Step-test planner routes (MPC 7.1a): preview, confirm, advance, abort and permissions.

A fake gateway stands in for the mailbox: it records every proposal and queues it as pending, so
the tests prove that steps leave only as ``propose`` commands in confirm mode and that any
refusal, rejection or takeover stops the remaining plan. Roles run through the real enforcer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, FakeClock, csrf, login, seed_users
from crosscut_api.auth.actor import ActorContext
from crosscut_api.auth.audit import read_records
from crosscut_api.auth.deps import AUDIT_FILE, AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth.store import auth_dir
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.mpc_step_routes import build_step_plan_router
from crosscut_connectors.site import save_site
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

NS = 1_000_000_000
SITE: dict[str, Any] = {
    "schema_version": 1,
    "site": {"name": "t"},
    "tags": [{"id": f"{loop}.{kind}"} for loop in "ab" for kind in ("sp", "pv", "out", "mode")]
    + [{"id": "cv"}],
    "loops": [
        {"id": "LA", "pv": "a.pv", "sp": "a.sp", "out": "a.out", "mode": "a.mode"},
        {"id": "LB", "pv": "b.pv", "sp": "b.sp", "out": "b.out", "mode": "b.mode"},
    ],
    "sources": [{"id": "s1", "driver": "opcua", "endpoint": "opc.tcp://127.0.0.1:4840"}],
    "controllers": [{
        "id": "C1", "type": "fuzzy",
        "variables": [
            {"id": "mva", "role": "MV", "binding": {"loop": "LA"},
             "limits": {"eng": {"lo": 0, "hi": 100}, "operator": {"lo": 10, "hi": 90},
                        "move_max": 4}},
            {"id": "mvb", "role": "MV", "binding": {"loop": "LB"},
             "limits": {"eng": {"lo": 0, "hi": 100}}},
            {"id": "cv1", "role": "CV", "binding": {"tag": "cv"}},
        ],
    }],
}
POLICY = {"targets": {
    "a.sp": {"limits": [0, 100], "max_step": 10, "min_interval_s": 60},
    "b.sp": {"limits": [20, 100], "max_step": 10, "min_interval_s": 60},
}}


class FakeGateway:
    """Queues proposals as pending (confirm mode) and records every command."""

    def __init__(self) -> None:
        self.mode_value = "confirm"
        self.calls: list[dict[str, Any]] = []
        self.rejected: list[str] = []
        self.pending_rows: list[dict[str, Any]] = []
        self.refuse_with: str | None = None

    def mode(self) -> str:
        return self.mode_value

    def live_policy(self) -> dict[str, Any]:
        return {"document": POLICY, "pin": {}}

    def propose(self, args: dict[str, Any], actor: ActorContext | None = None) -> dict[str, Any]:
        self.calls.append(args)
        if self.refuse_with:
            return {"accepted": False, "reason_code": self.refuse_with}
        self.pending_rows.append({**args, "key": f"k{len(self.calls)}"})
        return {"accepted": True, "reason_code": "queued"}

    def pending(self) -> list[dict[str, Any]]:
        return list(self.pending_rows)

    def reject(self, key: str, actor: ActorContext | None = None) -> None:
        self.rejected.append(key)
        self.pending_rows = [p for p in self.pending_rows if p["key"] != key]


class World:
    """App, fake gateway, live setpoints and a manual clock."""

    def __init__(self, root: Path) -> None:
        save_site(root, SITE)
        seed_users(root, DEFAULT_USERS)
        self.root, self.gateway = root, FakeGateway()
        self.live = {"a.sp": 50.0, "b.sp": 60.0}
        self.now = 1_000 * NS
        ctx = build_auth_context(root, TEST_CONFIG, FakeClock())
        self.app = FastAPI(dependencies=[Depends(make_enforcer(AuthGuards(ctx), ctx))])
        self.app.include_router(build_auth_router_for(ctx))
        self.app.include_router(build_step_plan_router(
            root, lambda: self.gateway, self.live.__getitem__, lambda: self.now))  # type: ignore[arg-type]
        self.client = TestClient(self.app)
        self.headers: dict[str, str] = {}

    def as_user(self, name: str) -> None:
        self.client = TestClient(self.app)
        self.headers = csrf(login(self.client, name))

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.client.post(f"/mpc/step-plans{path}", json=body or {}, headers=self.headers)

    def approve_pending(self) -> None:
        """What the operator's approval does: the setpoint moves and the entry leaves pending."""
        for row in self.gateway.pending_rows:
            self.live[row["target_tag"]] = row["value"]
        self.gateway.pending_rows = []


@pytest.fixture
def world(tmp_path: Path) -> World:
    w = World(tmp_path)
    w.as_user("eng1")
    return w


SEQUENTIAL: dict[str, Any] = {
    "plan_type": "sequential", "duration_s": 120, "gap_s": 60,
    "mvs": [{"controller_id": "C1", "variable_id": "mva", "amplitude": 3},
            {"controller_id": "C1", "variable_id": "mvb", "amplitude": -2}],
}


def confirm(w: World, body: dict[str, Any] | None = None) -> Any:
    """Preview, then confirm with the previewed digest."""
    body = body or SEQUENTIAL
    preview = w.post("/preview", body).json()
    return w.post("", {**body, "digest": preview["digest"]})


def step(w: World, seconds: float = 0.0) -> dict[str, Any]:
    """Advance the clock and the plan once; the single plan id is read from the list."""
    w.now += int(seconds * NS)
    plan_id = w.client.get("/mpc/step-plans").json()["plans"][0]["id"]
    return w.post(f"/{plan_id}/advance").json()


def test_preview_returns_schedule_and_sends_nothing(world: World) -> None:
    body = world.post("/preview", SEQUENTIAL).json()
    assert body["ok"] and len(body["steps"]) == 4 and body["gateway_mode"] == "confirm"
    assert [s["value"] for s in body["steps"]] == [53, 50, 58, 60]
    assert world.gateway.calls == []


def test_preview_uses_the_narrowest_bounds_and_names_refusals(world: World) -> None:
    too_big = {**SEQUENTIAL, "mvs": [{"controller_id": "C1", "variable_id": "mva", "amplitude": 5}]}
    body = world.post("/preview", too_big).json()  # move_max 4 beats policy max_step 10
    assert not body["ok"] and body["digest"] is None and body["steps"] == []
    assert body["refusals"][0]["code"] == "amplitude_exceeds_max_step"
    low = {**SEQUENTIAL, "mvs": [{"controller_id": "C1", "variable_id": "mvb", "amplitude": -2}]}
    world.live["b.sp"] = 21.0  # policy low limit 20: 21 - 2 = 19
    assert world.post("/preview", low).json()["refusals"][0]["code"] == "value_below_limit"


def test_short_interval_is_refused_against_policy(world: World) -> None:
    body = world.post("/preview", {**SEQUENTIAL, "duration_s": 30}).json()
    assert {r["code"] for r in body["refusals"]} == {"interval_below_min"}


def test_unknown_and_non_mv_variables_are_refused(world: World) -> None:
    bad = {**SEQUENTIAL, "mvs": [{"controller_id": "C1", "variable_id": "cv1", "amplitude": 1}]}
    assert world.post("/preview", bad).status_code == 422
    bad["mvs"][0]["variable_id"] = "nope"
    assert world.post("/preview", bad).status_code == 404


def test_confirm_proposes_only_the_first_step_and_audits(world: World) -> None:
    record = confirm(world).json()
    assert record["status"] == "running"
    assert [(c["target_tag"], c["value"]) for c in world.gateway.calls] == [("a.sp", 53.0)]
    assert world.gateway.calls[0]["proposer"]
    events = [r["event"] for r in read_records(auth_dir(world.root) / AUDIT_FILE)]
    assert "mpc_step_plan_confirmed" in events and "mpc_step_proposed" in events


def test_confirm_requires_confirm_mode_and_a_matching_digest(world: World) -> None:
    preview = world.post("/preview", SEQUENTIAL).json()
    world.gateway.mode_value = "supervised"
    refused = world.post("", {**SEQUENTIAL, "digest": preview["digest"]})
    assert (refused.status_code, refused.json()["detail"]) == (409, "gateway_not_confirm")
    world.gateway.mode_value = "confirm"
    stale = world.post("", {**SEQUENTIAL, "digest": "0" * 64})
    assert (stale.status_code, stale.json()["detail"]) == (409, "plan_changed")
    assert world.gateway.calls == []


def test_confirm_refuses_an_invalid_plan_and_a_second_running_plan(world: World) -> None:
    bad = {**SEQUENTIAL, "duration_s": 30}
    assert world.post("", {**bad, "digest": "0" * 64}).status_code == 409
    assert confirm(world).status_code == 200
    assert confirm(world).json()["detail"] == "plan_running"


def test_plan_runs_to_completion_one_approved_step_at_a_time(world: World) -> None:
    confirm(world)
    for expected_calls in (1, 2, 3, 4):
        assert len(world.gateway.calls) == expected_calls
        step(world, 0)  # the queued step is seen pending
        world.approve_pending()
        record = step(world, 0)  # approval seen; the next step is not yet due
        assert len(world.gateway.calls) == expected_calls
        record = step(world, 130)
    assert record["status"] == "completed"
    assert [c["value"] for c in world.gateway.calls] == [53, 50, 58, 60]


def test_late_approval_slips_the_schedule_instead_of_bunching_steps(world: World) -> None:
    confirm(world)
    step(world, 0)
    world.now += 500 * NS  # approval arrives late
    world.approve_pending()
    step(world, 0)
    assert len(world.gateway.calls) == 1  # step 2 is due 120 s after the APPLIED step
    step(world, 125)
    assert len(world.gateway.calls) == 2


def test_gateway_refusal_stops_the_remaining_plan(world: World) -> None:
    confirm(world)
    step(world, 0)
    world.approve_pending()
    step(world, 0)
    world.gateway.refuse_with = "min_interval"
    record = step(world, 130)
    assert record["status"] == "aborted" and record["abort_reason"] == "step_refused:min_interval"
    assert {s["status"] for s in record["steps"][2:]} == {"skipped"}
    assert record["displaced"] == [{"tag": "a.sp", "baseline": 50.0, "last_applied": 53.0}]
    assert len(world.gateway.calls) == 2  # nothing was sent after the refusal


def test_rejected_step_aborts(world: World) -> None:
    confirm(world)
    step(world, 0)  # seen as pending
    world.gateway.pending_rows = []  # operator rejected at the gateway; SP unchanged
    record = step(world, 20)
    assert record["abort_reason"] == "step_rejected" and len(world.gateway.calls) == 1


def test_operator_takeover_aborts_before_the_next_step(world: World) -> None:
    confirm(world)
    step(world, 0)
    world.approve_pending()
    step(world, 0)
    world.live["a.sp"] = 57.0  # the operator moved the setpoint by hand
    record = step(world, 130)
    assert record["abort_reason"] == "operator_takeover" and len(world.gateway.calls) == 1


def test_gateway_leaving_confirm_mode_aborts_and_proposes_nothing(world: World) -> None:
    confirm(world)
    step(world, 0)
    world.approve_pending()
    step(world, 0)
    world.gateway.mode_value = "supervised"
    plan_id = world.client.get("/mpc/step-plans").json()["plans"][0]["id"]
    world.now += 130 * NS
    assert world.post(f"/{plan_id}/advance").status_code == 409
    record = world.client.get(f"/mpc/step-plans/{plan_id}").json()
    assert record["abort_reason"] == "gateway_mode_changed" and len(world.gateway.calls) == 1


def test_unapproved_step_times_out(world: World) -> None:
    confirm(world)
    assert step(world, 10)["status"] == "running"
    record = step(world, 700)
    assert record["abort_reason"] == "approval_timeout" and world.gateway.rejected == ["k1"]


def test_operator_abort_rejects_the_queued_step(world: World) -> None:
    plan_id = confirm(world).json()["id"]
    world.as_user("op1")
    record = world.post(f"/{plan_id}/abort").json()
    assert record["status"] == "aborted" and record["abort_reason"] == "operator_abort"
    assert world.gateway.rejected == ["k1"]
    assert world.post(f"/{plan_id}/advance").status_code == 403  # operators cannot propose


def test_permissions_per_role(world: World) -> None:
    for user, preview_status, read_status in (("op1", 403, 200), ("view1", 403, 200)):
        world.as_user(user)
        assert world.post("/preview", SEQUENTIAL).status_code == preview_status
        assert world.post("", {**SEQUENTIAL, "digest": "0" * 64}).status_code == 403
        assert world.client.get("/mpc/step-plans").status_code == read_status
    world.as_user("view1")
    assert world.post("/xyz/abort").status_code == 404  # viewers hold gw.reject (ADR 013)
    assert world.gateway.calls == []


def test_unknown_plan_is_404(world: World) -> None:
    assert world.client.get("/mpc/step-plans/nope").status_code == 404


class FlippingGateway(FakeGateway):
    """Leaves confirm mode after a number of mode reads (mode flips between two due steps)."""

    def __init__(self, flip_after: int) -> None:
        super().__init__()
        self.reads, self.flip_after = 0, flip_after

    def mode(self) -> str:
        self.reads += 1
        return "confirm" if self.reads <= self.flip_after else "supervised"


GBN_TWO: dict[str, Any] = {
    "plan_type": "gbn", "duration_s": 600, "sample_s": 60, "switch_probability": 1.0, "seed": 3,
    "mvs": [{"controller_id": "C1", "variable_id": "mva", "amplitude": 2},
            {"controller_id": "C1", "variable_id": "mvb", "amplitude": 2}],
}


def test_mode_is_reread_before_each_propose(world: World) -> None:
    # confirm() reads the mode in preview, confirm and advance; the 4th read is before step 1,
    # the 5th (before the second simultaneous step) sees supervised.
    world.gateway = FlippingGateway(flip_after=4)
    record = confirm(world, GBN_TWO).json()
    assert len(world.gateway.calls) == 1  # type: ignore[attr-defined]
    stored = world.client.get(f"/mpc/step-plans/{record['id']}").json()
    assert stored["status"] == "aborted" and stored["abort_reason"] == "gateway_mode_changed"
    assert {s["status"] for s in stored["steps"]} <= {"queued", "rejected", "skipped",
                                                       "unresolved_check_dcs"}


def test_an_mv_cannot_be_in_two_running_plans_across_routers(world: World) -> None:
    other = World(world.root)
    other.gateway, other.live = world.gateway, world.live
    other.as_user("eng1")
    assert confirm(world).status_code == 200
    # a second process: the in-memory lock and the running-plan scan are not shared state
    from crosscut_api import mpc_step_routes
    from crosscut_api.mpc_step_exec import claim_tags
    assert claim_tags(world.root, "other", ["a.sp"]) == ["a.sp"]
    body = {**SEQUENTIAL, "mvs": SEQUENTIAL["mvs"][:1]}
    assert mpc_step_routes.build_step_plan_router  # router instances share only the disk
    preview = other.post("/preview", body).json()
    refused = other.post("", {**body, "digest": preview["digest"]})
    assert refused.status_code == 409


def test_claims_are_released_on_abort_and_stale_claims_are_taken_over(world: World) -> None:
    from crosscut_api.mpc_step_exec import claim_tags
    plan_id = confirm(world).json()["id"]
    assert claim_tags(world.root, "x", ["a.sp", "b.sp"]) == ["a.sp", "b.sp"]
    world.post(f"/{plan_id}/abort")
    assert claim_tags(world.root, "y", ["a.sp", "b.sp"]) == []  # released
    world.post("/preview", SEQUENTIAL)
    # plan "y" has no record and the claim is fresh: held; backdate it and it is stale
    assert claim_tags(world.root, "z", ["a.sp"]) == ["a.sp"]
    import os
    for claim in (world.root / "_mpc" / "claims").iterdir():
        os.utime(claim, (1, 1))
    assert claim_tags(world.root, "z", ["a.sp"]) == []


def test_future_sent_time_aborts_with_clock_skew(world: World) -> None:
    confirm(world)
    world.now -= 100 * NS  # the clock jumped backwards after the step was sent
    assert step(world, 0)["abort_reason"] == "clock_skew"


def test_small_negative_age_is_clamped_not_an_error(world: World) -> None:
    confirm(world)
    world.now -= 2 * NS
    assert step(world, 0)["status"] == "running"
