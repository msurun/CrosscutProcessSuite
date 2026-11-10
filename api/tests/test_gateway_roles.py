"""Role-by-permission tests for the Write Gateway routes behind the real app-level enforcer.

The mini app wires the auth router and the gateway router to an in-memory fake gateway.
Gateway behaviour is covered elsewhere; these tests check only who may call what.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from auth_support import (
    DEFAULT_USERS,
    TEST_CONFIG,
    FakeClock,
    csrf,
    login,
    seed_users,
    stepup,
)
from crosscut_api.auth.actor import ActorContext
from crosscut_api.auth.deps import AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.gateway_routes import build_gateway_router, policy_digest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from httpx import Response

DRAFT_DOC: dict[str, Any] = {"version": 1, "mode": "advisory", "targets": {}}
DRAFT_DIGEST = policy_digest(DRAFT_DOC)


class FakeGateway:
    """In-memory stand-in for the Write Gateway client that records each call."""

    def __init__(self) -> None:
        """Start in advisory mode with no recorded calls."""
        self.current_mode = "advisory"
        self.calls: list[tuple[str, str | None]] = []
        self.last_actor: ActorContext | None = None

    def _record(self, name: str, actor: ActorContext | None) -> None:
        """Remember one call together with the name of the actor that made it."""
        self.calls.append((name, actor.actor if actor else None))
        self.last_actor = actor

    def mode(self) -> str:
        """Return the current operating mode."""
        return self.current_mode

    def status(self) -> dict[str, str]:
        """Return one target on hold and one stopped by a kill."""
        return {"T_HOLD": "hold_off", "T_STOP": "stopped:kill"}

    def pending(self) -> list[dict[str, str | float | int]]:
        """Return no pending proposals."""
        return []

    def approve(self, key: str, actor: ActorContext | None = None) -> dict[str, object]:
        """Record an approval and report it accepted."""
        self._record("approve", actor)
        return {"accepted": True}

    def reject(self, key: str, actor: ActorContext | None = None) -> None:
        """Record a rejection."""
        self._record("reject", actor)

    def mv_availability(
        self, targets: list[str], actor: ActorContext | None = None
    ) -> dict[str, dict[str, Any]]:
        """Record the query and report every target available."""
        self._record("mv_availability", actor)
        return {t: {"available": True, "reasons": []} for t in targets}

    def kill(self, actor: ActorContext | None = None) -> None:
        """Record an emergency kill."""
        self._record("kill", actor)

    def kill_reset(self, actor: ActorContext | None = None) -> None:
        """Record a kill reset."""
        self._record("kill_reset", actor)

    def re_enable(self, tag: str, actor: ActorContext | None = None) -> None:
        """Record a re-enable of one target."""
        self._record("re_enable", actor)

    def set_mode(self, mode: str, actor: ActorContext | None = None) -> None:
        """Record a mode change and apply it."""
        self._record("set_mode", actor)
        self.current_mode = mode

    def audit(self, limit: int) -> dict[str, object]:
        """Return an empty audit page with an intact chain."""
        return {"records": [], "chain_ok": True}

    def draft_policy(self) -> dict[str, Any] | None:
        """Return a stored draft record."""
        return {"document": DRAFT_DOC, "author": "eng1", "saved_at": "2026-01-01T00:00:00+00:00"}

    def live_policy(self) -> dict[str, Any] | None:
        """Return a pinned live policy."""
        pin = {"digest": "f" * 64, "author": "eng1", "approver": "lead1", "approved_at": "t"}
        return {"document": DRAFT_DOC, "pin": pin}

    def policy_draft(self, document: dict[str, Any], actor: ActorContext | None = None) -> None:
        """Record a draft policy store."""
        self._record("policy_draft", actor)

    def policy_pin(self, digest: str, actor: ActorContext | None = None) -> None:
        """Record a policy pin."""
        self._record("policy_pin", actor)

    def policy_reload(self, actor: ActorContext | None = None) -> None:
        """Record a policy reload."""
        self._record("policy_reload", actor)


class _Provider:
    """Hand out the fake gateway, or None while the gateway is marked down."""

    def __init__(self, fake: FakeGateway) -> None:
        """Bind the provider to the fake gateway and mark it as running."""
        self.fake = fake
        self.up = True

    def __call__(self) -> FakeGateway | None:
        """Return the fake gateway while it is up."""
        return self.fake if self.up else None


@dataclass
class World:
    """The mini app together with its fake gateway, clock and gateway provider."""

    app: FastAPI
    fake: FakeGateway
    clock: FakeClock
    provider: _Provider


def _build_world(root: Path) -> World:
    """Seed the users, then wire the enforcer, auth router and gateway router together."""
    seed_users(root, {**DEFAULT_USERS, "lead1": ["lead"]})
    clock = FakeClock()
    ctx = build_auth_context(root, TEST_CONFIG, clock)
    guards = AuthGuards(ctx)
    fake = FakeGateway()
    provider = _Provider(fake)
    app = FastAPI(dependencies=[Depends(make_enforcer(guards, ctx))])
    app.include_router(build_auth_router_for(ctx))
    app.include_router(build_gateway_router(provider))
    return World(app=app, fake=fake, clock=clock, provider=provider)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> World:
    """Build the mini app once for this module."""
    return _build_world(tmp_path_factory.mktemp("gateway_roles"))


def client_as(
    world: World, username: str, mode: str = "advisory"
) -> tuple[TestClient, dict[str, Any]]:
    """Log ``username`` in on a fresh client and reset the fake to ``mode`` with no calls."""
    world.fake.calls.clear()
    world.fake.current_mode = mode
    client = TestClient(world.app)
    return client, login(client, username)


def send(
    client: TestClient, payload: dict[str, Any], route: str, body: Any = None
) -> Response:
    """Send a ``"METHOD /path"`` request with the session's CSRF header and return the response."""
    method, path = route.split(" ", 1)
    return client.request(method, path, json=body, headers=csrf(payload))


def test_viewer_kills_and_lowers_mode_but_cannot_approve_or_raise(world: World) -> None:
    """A viewer holds the invariant kill and mode-down permissions and no more."""
    client, payload = client_as(world, "view1", mode="confirm")
    assert send(client, payload, "POST /gateway/kill").status_code == 200
    assert ("kill", "view1") in world.fake.calls
    assert world.fake.last_actor is not None
    assert world.fake.last_actor.roles == ("viewer",)
    assert send(client, payload, "POST /gateway/pending/k1/approve").status_code == 403
    assert send(client, payload, "PUT /gateway/mode", {"mode": "off"}).status_code == 200
    assert world.fake.current_mode == "off"
    assert send(client, payload, "PUT /gateway/mode", {"mode": "advisory"}).status_code == 403
    assert send(client, payload, "GET /gateway/status").status_code == 200
    assert send(client, payload, "GET /gateway/audit").status_code == 200
    assert send(client, payload, "POST /gateway/targets/T_HOLD/re-enable").status_code == 403
    live = send(client, payload, "GET /gateway/policy")
    assert live.status_code == 200
    assert live.json()["digest"] == DRAFT_DIGEST
    assert send(client, payload, "GET /gateway/policy/draft").status_code == 403
    assert send(client, payload, "PUT /gateway/policy/draft", DRAFT_DOC).status_code == 403


def test_operator_approves_rejects_and_re_enables_only_held_target(world: World) -> None:
    """An operator approves and rejects proposals and re-enables only a held target."""
    client, payload = client_as(world, "op1")
    assert send(client, payload, "POST /gateway/pending/k1/approve").status_code == 200
    assert send(client, payload, "POST /gateway/pending/k1/reject").status_code == 200
    assert send(client, payload, "PUT /gateway/mode", {"mode": "dry_run"}).status_code == 403
    assert send(client, payload, "POST /gateway/targets/T_HOLD/re-enable").status_code == 200
    assert send(client, payload, "POST /gateway/targets/T_STOP/re-enable").status_code == 403
    assert send(client, payload, "PUT /gateway/policy/draft", DRAFT_DOC).status_code == 403
    assert send(client, payload, "GET /gateway/policy").status_code == 200
    assert send(client, payload, "GET /gateway/policy/draft").status_code == 403


def test_engineer_edits_draft_and_re_enables_stopped_target(world: World) -> None:
    """An engineer raises the mode one step, edits the draft, but cannot pin or reset the kill."""
    client, payload = client_as(world, "eng1")
    assert send(client, payload, "PUT /gateway/mode", {"mode": "dry_run"}).status_code == 200
    world.fake.current_mode = "confirm"
    assert send(client, payload, "PUT /gateway/mode", {"mode": "supervised"}).status_code == 403
    assert send(client, payload, "POST /gateway/targets/T_STOP/re-enable").status_code == 200
    assert send(client, payload, "PUT /gateway/policy/draft", DRAFT_DOC).status_code == 200
    draft = send(client, payload, "GET /gateway/policy/draft")
    assert draft.status_code == 200
    assert draft.json()["digest"] == DRAFT_DIGEST
    assert send(client, payload, "GET /gateway/policy").status_code == 200
    pin = send(client, payload, "POST /gateway/policy/pin", {"digest": DRAFT_DIGEST})
    assert pin.status_code == 403
    assert send(client, payload, "POST /gateway/kill/reset").status_code == 403


def test_lead_supervised_needs_fresh_stepup(world: World) -> None:
    """A lead cannot enter supervised mode without a step-up, and can once it is fresh."""
    client, payload = client_as(world, "lead1", mode="confirm")
    response = send(client, payload, "PUT /gateway/mode", {"mode": "supervised"})
    assert response.status_code == 428
    assert response.json()["detail"] == "step_up_required"
    assert world.fake.calls == []
    stepup(client, payload)
    assert send(client, payload, "PUT /gateway/mode", {"mode": "supervised"}).status_code == 200
    assert world.fake.current_mode == "supervised"


def test_lead_cannot_skip_a_mode_step(world: World) -> None:
    """A mode rise of two steps is refused with 409 and changes nothing."""
    client, payload = client_as(world, "lead1", mode="advisory")
    assert send(client, payload, "PUT /gateway/mode", {"mode": "confirm"}).status_code == 409
    assert world.fake.calls == []


def test_lead_kill_reset_and_pin_need_stepup_but_reload_does_not(world: World) -> None:
    """Kill reset and policy pin need a fresh step-up; policy reload does not."""
    client, payload = client_as(world, "lead1")
    assert send(client, payload, "POST /gateway/policy/reload").status_code == 200
    reset = send(client, payload, "POST /gateway/kill/reset")
    assert reset.status_code == 428
    assert reset.json()["detail"] == "step_up_required"
    pin = send(client, payload, "POST /gateway/policy/pin", {"digest": DRAFT_DIGEST})
    assert pin.status_code == 428
    stepup(client, payload)
    assert send(client, payload, "POST /gateway/kill/reset").status_code == 200
    pinned = send(client, payload, "POST /gateway/policy/pin", {"digest": DRAFT_DIGEST})
    assert pinned.status_code == 200
    assert ("policy_pin", "lead1") in world.fake.calls


def test_lead_pin_of_a_changed_draft_is_409_draft_changed(world: World) -> None:
    """A pin naming a digest other than the stored draft's is refused with 409 draft_changed."""
    client, payload = client_as(world, "lead1")
    stepup(client, payload)
    pin = send(client, payload, "POST /gateway/policy/pin", {"digest": "0" * 64})
    assert pin.status_code == 409
    assert pin.json()["detail"] == "draft_changed"
    assert ("policy_pin", "lead1") not in world.fake.calls


def test_request_without_session_is_refused(world: World) -> None:
    """A request carrying no session cookie gets 401."""
    client = TestClient(world.app)
    assert client.get("/gateway/status").status_code == 401


def test_mv_availability_route_returns_targets_for_viewer(world: World) -> None:
    """A viewer holds gw.view, so the read-only availability query succeeds."""
    client, payload = client_as(world, "view1")
    response = send(client, payload, "GET /gateway/mv-availability?targets=a&targets=b")
    assert response.status_code == 200
    assert response.json() == {t: {"available": True, "reasons": []} for t in ("a", "b")}
    assert ("mv_availability", "view1") in world.fake.calls


def test_mv_availability_route_needs_session_and_targets(world: World) -> None:
    """No session gets 401; a session without the targets query gets 422."""
    assert TestClient(world.app).get("/gateway/mv-availability?targets=a").status_code == 401
    client, payload = client_as(world, "view1")
    assert send(client, payload, "GET /gateway/mv-availability").status_code == 422


def test_kill_without_enforcer_or_stamped_actor_fails_closed() -> None:
    """With auth on and no enforcer, an unstamped request to the kill route gets 401."""
    app = FastAPI()
    app.state.auth_enabled = True
    app.include_router(build_gateway_router(_Provider(FakeGateway())))
    assert TestClient(app).post("/gateway/kill").status_code == 401


def test_unsafe_request_without_csrf_header_is_refused(world: World) -> None:
    """A session alone is not enough for an unsafe request; the CSRF header is required."""
    client, _payload = client_as(world, "op1")
    assert client.post("/gateway/kill").status_code == 403
    assert world.fake.calls == []


def test_status_is_503_while_gateway_is_down(world: World) -> None:
    """The status route reports 503 when the gateway provider has no running gateway."""
    client, payload = client_as(world, "view1")
    world.provider.up = False
    try:
        response = send(client, payload, "GET /gateway/status")
    finally:
        world.provider.up = True
    assert response.status_code == 503
