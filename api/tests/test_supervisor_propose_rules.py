"""Safety rules of supervisor setpoint proposals, with a fake gateway client (ADR 014 section 7).

Covers the live setpoint, mode x gateway mode x role matrix, advice age, dedupe, bounded manual
moves, error mapping, and that dataset replay and analysis.run can never reach the gateway.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest
from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.gateway_client import GatewayConflict, StepUpRequired
from crosscut_api.supervisor_routes import build_supervisor_router
from crosscut_connectors.base import LiveValue
from crosscut_connectors.site import save_site
from crosscut_supervisor.audit import AuditLog
from fastapi import FastAPI
from fastapi.testclient import TestClient

TAG = "FIC101.SP"
LOOP = "mill_feed"
SID = "mill-feed"
NS = 1_000_000_000
PERMS = {
    "operator": frozenset({"analysis.run"}),
    "engineer": frozenset({"analysis.run", "gw.propose"}),
    "lead": frozenset({"analysis.run", "gw.propose", "gw.mode.up.supervised"}),
}
CONFIG: dict[str, Any] = {
    "schema_version": "1.0.0", "id": SID, "fuzzy_system_id": "mill_feed_supervisor",
    "output_id": "feed_change", "target_loop": LOOP, "target_tag": TAG, "mode": "confirm",
    "gates": [], "silent_band": 0.0, "min_activation": 0.0, "min_interval_s": 0,
    "display_clamp": [-10, 10], "max_step": 10.0,
}


class FakeGateway:
    """Records proposals; answers with a canned decision or raises a canned error."""

    def __init__(self, mode: str = "confirm") -> None:
        self.mode_value = mode
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None
        self.decision: dict[str, Any] = {"accepted": True, "reason_code": "queued"}

    def mode(self) -> str:
        return self.mode_value

    def propose(self, args: dict[str, Any], actor: ActorContext | None = None) -> dict[str, Any]:
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.decision


@dataclass
class World:
    root: Path
    client: TestClient
    gateway: FakeGateway
    live: dict[str, float]
    role: dict[str, str] = field(default_factory=lambda: {"name": "engineer"})

    def as_role(self, name: str) -> None:
        self.role["name"] = name

    def advice(self, advice_id: str = "a1", **changes: Any) -> str:
        """Append an advice record (fresh, +2 on mill_feed unless changed); return its id."""
        record: dict[str, Any] = {
            "kind": "advice", "advice_id": advice_id, "t_ns": time.time_ns(),
            "target_loop": LOOP, "direction": "increase", "magnitude": 2.0, "activation": 1.0,
            "explanation": [{"rule_id": "r", "sentence": "feed is low", "weight": 1.0}],
        }
        record.update(changes)
        record = {k: v for k, v in record.items() if v is not None}
        AuditLog(self.root / "_advisory" / SID / "log.jsonl").append(record)
        return advice_id

    def propose(self, **body: Any) -> Any:
        return self.client.post(f"/supervisors/{SID}/propose", json=body)

    def set_config(self, **changes: Any) -> None:
        doc = {k: v for k, v in {**CONFIG, **changes}.items() if v is not None}
        assert self.client.put(f"/supervisors/{SID}", json=doc).status_code == 200


def _no_dataset(_dataset_id: str) -> Any:
    raise AssertionError("dataset must not be read")


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    live = {TAG: 150.0}

    class Connector:
        def read_live(self, tags: list[str]) -> dict[str, LiveValue]:
            return {t: LiveValue(live[t], 0, "now") for t in tags if t in live}

    monkeypatch.setattr(
        "crosscut_api.supervisor_live.connector_from_source", lambda _source: Connector()
    )
    save_site(tmp_path, {
        "schema_version": 1, "site": {"name": "t"},
        "tags": [{"id": t} for t in (TAG, "FIC101.PV", "FIC101.OUT")],
        "loops": [{"id": LOOP, "pv": "FIC101.PV", "sp": TAG, "out": "FIC101.OUT"}],
        "sources": [{"id": "dcs", "driver": "opcua", "endpoint": "opc.tcp://x"}],
    })
    gateway = FakeGateway()
    app = FastAPI()
    app.include_router(build_supervisor_router(
            tmp_path, _no_dataset, _no_dataset, cast(Any, lambda: gateway)
        ))
    role = {"name": "engineer"}
    app.dependency_overrides[actor_of] = lambda: ActorContext(
        "tester", (role["name"],), "s" * 16, "127.0.0.1", True, PERMS[role["name"]]
    )
    built = World(tmp_path, TestClient(app), gateway, live, role)
    built.set_config()
    return built


# --- defect 1: live setpoint only -------------------------------------------------------------


def test_new_setpoint_is_live_sp_plus_delta(world: World) -> None:
    world.advice("a1", magnitude=2.0)
    body = world.propose(advice_id="a1").json()
    assert body["proposal"]["value"] == 152.0
    assert world.gateway.calls[0]["value"] == 152.0


def test_decrease_moves_down_from_live_sp(world: World) -> None:
    world.advice("a1", direction="decrease", magnitude=3.0)
    assert world.propose(advice_id="a1").json()["proposal"]["value"] == 147.0


def test_missing_live_sp_is_refused_not_zero(world: World) -> None:
    world.live.clear()
    world.advice("a1")
    resp = world.propose(advice_id="a1")
    assert (resp.status_code, resp.json()["detail"]) == (409, "no_live_sp")
    assert world.gateway.calls == []


def test_no_site_means_no_live_sp(world: World) -> None:
    (world.root / "_site" / "site.json").unlink()
    world.advice("a1")
    resp = world.propose(advice_id="a1")
    assert (resp.status_code, resp.json()["detail"]) == (409, "no_live_sp")


def test_body_current_sp_and_target_tag_are_rejected(world: World) -> None:
    world.advice("a1")
    assert world.propose(advice_id="a1", current_sp=0.0).status_code == 422
    assert world.propose(advice_id="a1", target_tag="OTHER.SP").status_code == 422
    assert world.gateway.calls == []


def test_target_tag_comes_from_site_catalog_when_config_has_none(world: World) -> None:
    world.set_config(target_tag=None)
    world.advice("a1")
    assert world.propose(advice_id="a1").json()["proposal"]["target_tag"] == TAG


def test_no_target_tag_anywhere_is_refused(world: World) -> None:
    world.set_config(target_tag=None)
    (world.root / "_site" / "site.json").write_text(
        json.dumps({"schema_version": 1, "site": {"name": "t"}, "tags": [], "loops": []}),
        encoding="utf-8",
    )
    world.advice("a1")
    resp = world.propose(advice_id="a1")
    assert (resp.status_code, resp.json()["detail"]) == (409, "no_target_tag")


def test_delta_above_max_step_is_refused(world: World) -> None:
    world.advice("a1", magnitude=10.5)
    resp = world.propose(advice_id="a1")
    assert (resp.status_code, resp.json()["detail"]) == (409, "delta_too_large")
    assert world.gateway.calls == []


def test_missing_max_step_is_refused(world: World) -> None:
    world.set_config(max_step=None)
    world.advice("a1")
    resp = world.propose(advice_id="a1")
    assert (resp.status_code, resp.json()["detail"]) == (409, "max_step_unset")


def test_sign_mismatch_is_refused(world: World) -> None:
    world.live[TAG] = 1e18  # +2 is lost in rounding: the move would not go the advised way
    world.advice("a1")
    resp = world.propose(advice_id="a1")
    assert (resp.status_code, resp.json()["detail"]) == (409, "sign_mismatch")
    assert world.gateway.calls == []


def test_advice_for_another_loop_is_refused(world: World) -> None:
    world.advice("a1", target_loop="other_loop")
    resp = world.propose(advice_id="a1")
    assert (resp.status_code, resp.json()["detail"]) == (409, "advice_loop_mismatch")


# --- defect 3: mode x gateway mode x role matrix ----------------------------------------------


def _expected(sup: str, gw: str, role: str) -> int:
    """Status the rule gives: role first, then supervisor mode, then gateway mode."""
    if role == "operator":
        return 403
    if sup in ("off", "advisory"):
        return 409
    if sup == "supervised" and role != "lead":
        return 403
    return 200 if gw == sup else 409


@pytest.mark.parametrize("role", ["operator", "engineer", "lead"])
@pytest.mark.parametrize("gw_mode", ["confirm", "supervised"])
@pytest.mark.parametrize("sup_mode", ["off", "advisory", "confirm", "supervised"])
def test_mode_matrix(world: World, sup_mode: str, gw_mode: str, role: str) -> None:
    world.set_config(mode=sup_mode)
    world.gateway.mode_value = gw_mode
    world.as_role(role)
    world.advice("a1")
    resp = world.propose(advice_id="a1")
    assert resp.status_code == _expected(sup_mode, gw_mode, role), resp.text
    assert len(world.gateway.calls) == (1 if resp.status_code == 200 else 0)


def test_matrix_refusal_codes(world: World) -> None:
    world.advice("a1")
    world.set_config(mode="advisory")
    assert world.propose(advice_id="a1").json()["detail"] == "mode_advisory_only"
    world.set_config(mode="off")
    assert "mode is off" in world.propose(advice_id="a1").json()["detail"]
    world.set_config(mode="confirm")
    world.gateway.mode_value = "supervised"
    assert world.propose(advice_id="a1").json()["detail"] == "gateway_mode_mismatch"


def test_confirm_response_says_it_queues_for_human_approval(world: World) -> None:
    world.advice("a1")
    body = world.propose(advice_id="a1").json()
    assert body["mode"] == "confirm" and body["queues_for_approval"] is True


def test_supervised_response_does_not_claim_queueing(world: World) -> None:
    world.set_config(mode="supervised")
    world.gateway.mode_value = "supervised"
    world.as_role("lead")
    world.advice("a1")
    assert world.propose(advice_id="a1").json()["queues_for_approval"] is False


# --- defect 4: advice age ---------------------------------------------------------------------


def test_stale_advice_is_refused(world: World) -> None:
    world.advice("a1", t_ns=time.time_ns() - 301 * NS)
    resp = world.propose(advice_id="a1")
    assert (resp.status_code, resp.json()["detail"]) == (409, "advice_stale")
    assert world.gateway.calls == []


def test_configured_age_limit_is_used(world: World) -> None:
    world.set_config(max_advice_age_s=10)
    world.advice("a1", t_ns=time.time_ns() - 11 * NS)
    assert world.propose(advice_id="a1").json()["detail"] == "advice_stale"
    world.advice("a2", t_ns=time.time_ns() - 5 * NS)
    assert world.propose(advice_id="a2").status_code == 200


def test_advice_without_timestamp_is_refused(world: World) -> None:
    world.advice("a1", t_ns=None)
    resp = world.propose(advice_id="a1")
    assert (resp.status_code, resp.json()["detail"]) == (409, "advice_stale")


def test_advice_from_the_future_is_refused(world: World) -> None:
    world.advice("a1", t_ns=time.time_ns() + 3600 * NS)
    assert world.propose(advice_id="a1").json()["detail"] == "advice_stale"


# --- defect 5: dedupe and audit link ----------------------------------------------------------


def test_same_advice_is_proposed_once(world: World) -> None:
    world.advice("a1")
    first = world.propose(advice_id="a1")
    second = world.propose(advice_id="a1")
    assert first.status_code == 200
    detail = second.json()["detail"]
    assert second.status_code == 409 and detail["code"] == "already_proposed"
    assert detail["previous"]["decision"] == world.gateway.decision
    assert len(world.gateway.calls) == 1
    stored = json.loads((world.root / "_supervisor" / "proposed.json").read_text("utf-8"))
    assert stored["a1"]["status"] == "sent"


def test_proposed_json_is_not_listed_as_a_supervisor(world: World) -> None:
    world.advice("a1")
    world.propose(advice_id="a1")
    assert world.client.get("/supervisors").json() == [SID]
    assert world.client.get("/supervisors/proposed").status_code == 404


def test_reason_links_the_gateway_audit_to_the_advice(world: World) -> None:
    world.advice("a1")
    world.propose(advice_id="a1")
    assert world.gateway.calls[0]["reason"] == "advice:a1 feed is low"


def test_t_ns_is_the_real_send_time(world: World) -> None:
    world.advice("a1", t_ns=time.time_ns() - 100 * NS)
    before = time.time_ns()
    world.propose(advice_id="a1")
    assert before <= world.gateway.calls[0]["t_ns"] <= time.time_ns()


def test_refused_send_releases_the_advice_id(world: World) -> None:
    world.advice("a1")
    world.gateway.error = GatewayConflict("above_cap")
    assert world.propose(advice_id="a1").status_code == 409
    world.gateway.error = None
    assert world.propose(advice_id="a1").status_code == 200


# --- defect 6: manual path --------------------------------------------------------------------


def test_manual_move_is_bounded_by_max_step(world: World) -> None:
    resp = world.propose(direction="increase", magnitude=10.5)
    assert (resp.status_code, resp.json()["detail"]) == (409, "delta_too_large")
    assert world.gateway.calls == []


def test_manual_negative_or_zero_magnitude_is_rejected(world: World) -> None:
    assert world.propose(direction="increase", magnitude=-5).status_code == 422
    assert world.propose(direction="increase", magnitude=0).status_code == 422
    assert world.propose(direction="hold", magnitude=1).status_code == 422
    assert world.propose(direction="increase").status_code == 422


def test_manual_reason_is_prefixed_and_capped(world: World) -> None:
    resp = world.propose(direction="increase", magnitude=1.0, reason="r" * 201)
    assert resp.status_code == 422
    world.propose(direction="increase", magnitude=1.0, reason="trim the feed")
    reason = world.gateway.calls[0]["reason"]
    assert "operator-supplied: trim the feed" in reason and "Supervisor" not in reason


def test_manual_move_uses_live_sp(world: World) -> None:
    assert world.propose(direction="decrease", magnitude=4.0).json()["proposal"]["value"] == 146.0


# --- defect 7: error mapping ------------------------------------------------------------------


def test_timeout_is_504_outcome_unknown_without_retry_hint(world: World) -> None:
    world.advice("a1")
    world.gateway.error = TimeoutError("gateway did not answer")
    resp = world.propose(advice_id="a1")
    assert resp.status_code == 504 and resp.json()["detail"] == "outcome_unknown_check_audit"
    assert "retry-after" not in {k.lower() for k in resp.headers}
    world.gateway.error = None
    assert world.propose(advice_id="a1").json()["detail"]["code"] == "already_proposed"


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PermissionError("forbidden"), 403),
        (StepUpRequired("step_up_required"), 428),
        (GatewayConflict("above_cap"), 409),
        (ValueError("bad"), 422),
        (KeyError("unknown key"), 404),
    ],
)
def test_gateway_errors_keep_their_real_codes(world: World, error: Exception, status: int) -> None:
    world.advice("a1")
    world.gateway.error = error
    assert world.propose(advice_id="a1").status_code == status


# --- defect 2: dataset replay and analysis.run never reach the gateway --------------------------


def test_advise_on_dataset_cannot_propose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from crosscut_sim.run import main as run_simulation
    from open_app import create_app_without_auth

    argv = ["--plant", "mill_circuit", "--duration", "1h", "--sample-period", "10"]
    assert run_simulation([*argv, "--out", str(tmp_path)]) == 0
    client = TestClient(create_app_without_auth(tmp_path))
    dataset = client.get("/datasets").json()[0]["id"]
    client.put(f"/supervisors/{SID}", json=CONFIG)
    resp = client.post(f"/datasets/{dataset}/supervisor/{SID}/advise", json={"propose": True})
    assert resp.status_code == 422
    plain = client.post(f"/datasets/{dataset}/supervisor/{SID}/advise", json={})
    assert plain.status_code == 200 and "proposal" not in plain.json()


def test_propose_route_requires_gw_propose_in_the_route_table() -> None:
    from crosscut_api.auth.route_permissions import ROUTE_PERMISSIONS

    assert ROUTE_PERMISSIONS[("POST", "/supervisors/{sid}/propose")] == "gw.propose"
    advise = ROUTE_PERMISSIONS[("POST", "/datasets/{dataset_id}/supervisor/{sid}/advise")]
    assert advise == "analysis.run"


def test_analysis_run_alone_cannot_propose(world: World) -> None:
    world.as_role("operator")
    world.advice("a1")
    assert world.propose(advice_id="a1").status_code == 403
    assert world.gateway.calls == []


