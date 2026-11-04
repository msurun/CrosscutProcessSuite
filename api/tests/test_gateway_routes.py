"""Integration tests for Write Gateway HTTP API routes (Phase 2, #46).

Tests cover every endpoint, 503 service unavailable states, 404/409/422 error codes,
and confirm-mode approval semantics verifying exactly-once writing to the control system.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import cast

from crosscut_api.gateway_routes import build_gateway_router
from crosscut_gateway.audit import verify_chain
from crosscut_gateway.engine import Mode, WriteGateway
from crosscut_gateway.interfaces import WritePolicy, WriteProposal
from crosscut_gateway.policy import proposal_key
from fastapi import FastAPI
from fastapi.testclient import TestClient

TAG = "FIC101.SP"
ONE_SECOND_NS = 1_000_000_000


class SimPlant:
    """Minimal deterministic simulated control system for API route testing."""

    def __init__(self, watchdog_s: float = 5.0) -> None:
        self.now_ns = 0
        self.watchdog_ns = int(watchdog_s * ONE_SECOND_NS)
        self.values = {TAG: 50.0}
        self.modes = {TAG: "CAS"}
        self.remote = False
        self.last_hb_ns: int | None = None
        self.writes: list[tuple[int, str, float]] = []
        self.refuse = False
        self.readback_offset = 0.0

    def read(self, tag: str) -> float:
        return self.values[tag] + self.readback_offset

    def write(self, tag: str, value: float) -> bool:
        if self.refuse or self.modes.get(tag) != "CAS":
            return False
        self.values[tag] = value
        self.remote = True
        self.writes.append((self.now_ns, tag, value))
        return True

    def send_heartbeat(self) -> None:
        self.last_hb_ns = self.now_ns

    def loop_mode(self, tag: str) -> str:
        return self.modes[tag]

    def setpoint_source(self, tag: str) -> str:
        return "remote" if self.remote else "local"

    def release(self, tag: str) -> None:
        self.remote = False


def _make_policy() -> WritePolicy:
    """Return standard test policy for FIC101.SP."""
    return WritePolicy(
        limits=(0.0, 100.0),
        max_step=10.0,
        max_rate_per_s=5.0,
        min_interval_s=1.0,
        allowed_loop_modes=("CAS",),
        hold_off_s=60.0,
        watchdog_s=5.0,
        readback_tolerance=0.5,
    )


class GatewayAdapter:
    """Expose an in-process WriteGateway through the GatewayClient interface."""

    def __init__(self, gw: WriteGateway) -> None:
        self._gw = gw

    def mode(self) -> str:
        # The engine has no public mode accessor; _mode is read here for tests only.
        return str(self._gw._mode)

    def status(self) -> dict[str, str]:
        return self._gw.status()

    def pending(self) -> list[dict[str, str | float | int]]:
        return [
            {
                "key": proposal_key(p),
                "target_tag": p.target_tag,
                "value": p.value,
                "proposer": p.proposer,
                "t_ns": p.t_ns,
                "reason": p.reason,
            }
            for p in self._gw.pending()
        ]

    def approve(self, key: str, actor: object = None) -> dict[str, object]:
        decision = self._gw.approve(key)
        return {
            "accepted": decision.accepted,
            "reason_code": decision.reason_code,
            "clamped_value": decision.clamped_value,
        }

    def reject(self, key: str, actor: object = None) -> None:
        self._gw.reject(key)

    def kill(self, actor: object = None) -> None:
        self._gw.kill()

    def re_enable(self, tag: str, actor: object = None) -> None:
        self._gw.re_enable(tag)

    def set_mode(self, mode: str, actor: object = None) -> None:
        self._gw.set_mode(cast(Mode, mode))

    def audit(self, limit: int) -> dict[str, object]:
        records = self._gw.audit_records()
        return {"records": records[-limit:], "chain_ok": verify_chain(records)}


def _make_app(gw: WriteGateway | None) -> TestClient:
    """Build a TestClient wrapping an app with the gateway router."""
    app = FastAPI()
    app.include_router(
        build_gateway_router(lambda: GatewayAdapter(gw) if gw is not None else None)
    )
    return TestClient(app)


def test_routes_return_503_when_gateway_not_running() -> None:
    """All endpoints return 503 when the gateway provider returns None."""
    client = _make_app(None)
    assert client.get("/gateway/status").status_code == 503
    assert client.get("/gateway/pending").status_code == 503
    assert client.post("/gateway/pending/abc/approve").status_code == 503
    assert client.post("/gateway/pending/abc/reject").status_code == 503
    assert client.post("/gateway/kill").status_code == 503
    assert client.post(f"/gateway/targets/{TAG}/re-enable").status_code == 503
    assert client.put("/gateway/mode", json={"mode": "confirm"}).status_code == 503
    assert client.get("/gateway/audit").status_code == 503


def test_status_endpoint_returns_mode_and_target_states() -> None:
    """GET /gateway/status returns active mode, targets dictionary and pending count."""
    plant = SimPlant()
    gw = WriteGateway(plant, {TAG: _make_policy()}, mode="confirm")
    client = _make_app(gw)

    resp = client.get("/gateway/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "confirm"
    assert data["targets"] == {TAG: "enabled"}
    assert data["pending"] == 0


def test_pending_and_approve_writes_exactly_once() -> None:
    """Confirm mode queues proposals; approve executes write to plant exactly once."""
    plant = SimPlant()
    gw = WriteGateway(plant, {TAG: _make_policy()}, mode="confirm")
    prop = WriteProposal(TAG, 55.0, "opt_agent", ONE_SECOND_NS, "step test")
    gw.propose(prop)
    key = proposal_key(prop)

    client = _make_app(gw)
    pending_resp = client.get("/gateway/pending")
    assert pending_resp.status_code == 200
    proposals = pending_resp.json()
    assert len(proposals) == 1
    assert proposals[0]["key"] == key
    assert proposals[0]["value"] == 55.0

    approve_resp = client.post(f"/gateway/pending/{key}/approve")
    assert approve_resp.status_code == 200
    decision = approve_resp.json()
    assert decision["accepted"] is True
    assert decision["reason_code"] == "ok"

    # Exactly one write made to plant
    assert len(plant.writes) == 1
    assert plant.writes[0][1:] == (TAG, 55.0)

    # Subsequent approve returns 404
    second_approve = client.post(f"/gateway/pending/{key}/approve")
    assert second_approve.status_code == 404


def test_reject_removes_pending_without_writing() -> None:
    """Rejecting a pending proposal clears it from queue without writing to plant."""
    plant = SimPlant()
    gw = WriteGateway(plant, {TAG: _make_policy()}, mode="confirm")
    prop = WriteProposal(TAG, 55.0, "opt_agent", ONE_SECOND_NS, "step test")
    gw.propose(prop)
    key = proposal_key(prop)

    client = _make_app(gw)
    reject_resp = client.post(f"/gateway/pending/{key}/reject")
    assert reject_resp.status_code == 200
    assert reject_resp.json() == {"ok": True}
    assert len(plant.writes) == 0

    # Key is now gone, subsequent reject returns 404
    assert client.post(f"/gateway/pending/{key}/reject").status_code == 404


def test_kill_endpoint_transitions_targets_to_killed() -> None:
    """POST /gateway/kill immediately transitions targets to killed state."""
    plant = SimPlant()
    gw = WriteGateway(plant, {TAG: _make_policy()}, mode="supervised")
    client = _make_app(gw)

    resp = client.post("/gateway/kill")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    status_resp = client.get("/gateway/status")
    assert status_resp.json()["targets"][TAG] == "killed"


def test_re_enable_success_and_errors() -> None:
    """POST /gateway/targets/{tag}/re-enable returns 409 or 404 on invalid requests."""
    plant = SimPlant()
    gw = WriteGateway(plant, {TAG: _make_policy()}, mode="supervised")
    client = _make_app(gw)

    # 404 for unknown tag
    assert client.post("/gateway/targets/UNKNOWN_TAG/re-enable").status_code == 404

    # 409 when tag is already enabled
    conflict_resp = client.post(f"/gateway/targets/{TAG}/re-enable")
    assert conflict_resp.status_code == 409

    # Stop target and re-enable successfully
    plant.refuse = True
    gw.propose(WriteProposal(TAG, 55.0, "opt", ONE_SECOND_NS, "refusal"))
    assert gw.status()[TAG] == "stopped:rejected"

    re_enable_resp = client.post(f"/gateway/targets/{TAG}/re-enable")
    assert re_enable_resp.status_code == 200
    assert gw.status()[TAG] == "enabled"


def test_put_mode_updates_mode_or_returns_422() -> None:
    """PUT /gateway/mode changes operating mode and validates inputs."""
    plant = SimPlant()
    gw = WriteGateway(plant, {TAG: _make_policy()}, mode="advisory")
    client = _make_app(gw)

    # A rise of two steps (advisory -> confirm) is refused and leaves the mode alone.
    jump = client.put("/gateway/mode", json={"mode": "confirm"})
    assert jump.status_code == 409
    assert client.get("/gateway/status").json()["mode"] == "advisory"

    for step in ("dry_run", "confirm", "supervised"):
        resp = client.put("/gateway/mode", json={"mode": step})
        assert resp.status_code == 200
        assert resp.json()["mode"] == step
        assert client.get("/gateway/status").json()["mode"] == step

    # Invalid mode returns 422
    assert client.put("/gateway/mode", json={"mode": "not_a_mode"}).status_code == 422


def test_audit_endpoint_returns_records_and_chain_validity() -> None:
    """GET /gateway/audit returns records and chain_ok flag, validating limits."""
    plant = SimPlant()
    gw = WriteGateway(plant, {TAG: _make_policy()}, mode="dry_run")
    gw.propose(WriteProposal(TAG, 55.0, "opt", ONE_SECOND_NS, "dry test"))
    client = _make_app(gw)

    resp = client.get("/gateway/audit?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chain_ok"] is True
    assert len(data["records"]) > 0

    # Limit validation out of range 1..1000 returns 422
    assert client.get("/gateway/audit?limit=0").status_code == 422
    assert client.get("/gateway/audit?limit=1001").status_code == 422


def test_api_package_has_no_gateway_import() -> None:
    """gateway_routes must not import crosscut_gateway; the gateway runs as a separate process."""
    source = Path(__file__).resolve().parents[1] / "src" / "crosscut_api" / "gateway_routes.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            continue
        for module in modules:
            is_gateway = module == "crosscut_gateway" or module.startswith("crosscut_gateway.")
            assert not is_gateway, module
