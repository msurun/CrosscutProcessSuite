"""Gateway refusals reach the HTTP caller at once, with the right status, not as a 504 timeout.

A real GatewayService thread (auth on, signed commands, pinned policy file) runs behind the
real gateway router and FileGatewayClient with a small timeout. Commands refused before the
sender is trusted (bad signature) get no reply, so the client keeps its timeout for those.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from auth_support import write_key_file
from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.gateway_client import FileGatewayClient, StepUpRequired, _error_for
from crosscut_api.gateway_routes import build_gateway_router, policy_digest
from crosscut_gateway import policy_pin
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.service import GatewayService, ServiceOptions, serve
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_gateway_client import POLICY, TAG, SimPlant

CLIENT_TIMEOUT_S = 3.0
PROMPT_S = 1.5
SERVICE_INTERVAL_S = 0.02
DOC: dict[str, Any] = {
    "version": 1,
    "mode": "advisory",
    "targets": {
        TAG: {
            "limits": [0.0, 100.0],
            "max_step": 10.0,
            "max_rate_per_s": 5.0,
            "min_interval_s": 1.0,
            "allowed_loop_modes": ["CAS"],
            "hold_off_s": 60.0,
            "watchdog_s": 5.0,
            "readback_tolerance": 0.5,
        }
    },
}


def _actor(name: str, roles: tuple[str, ...], *, stepup: bool = True) -> ActorContext:
    """Return a request actor with the given roles; the router enforcer is not under test."""
    return ActorContext(
        actor=name,
        roles=roles,
        session="0123456789abcdef",
        source_ip="127.0.0.1",
        stepup=stepup,
        permissions=None,
    )


@dataclass
class Live:
    """A running gateway, the API over it, and the actor the next request is made as."""

    root: Path
    http: TestClient
    client: FileGatewayClient
    actor: list[ActorContext]

    def act_as(self, name: str, roles: tuple[str, ...], *, stepup: bool = True) -> None:
        """Make the following requests as this actor."""
        self.actor[0] = _actor(name, roles, stepup=stepup)


def _write_pinned_policy(root: Path, key: bytes) -> Path:
    """Write a live policy file with a valid two-person pin and return its path."""
    path = root / "policy" / "write-policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DOC, indent=2), encoding="utf-8")
    policy_pin.create_pin(
        path, key, policy_pin.PinSigners("author1", "approver1"), datetime.now(UTC)
    )
    return path


def _start(root: Path, *, with_policy: bool) -> tuple[Live, threading.Event, threading.Thread]:
    """Start the gateway thread on root and build the API over it."""
    key = os.urandom(32)
    key_file = root / "_secrets" / "gateway-hmac.key"
    write_key_file(key_file, key)
    policy_path = _write_pinned_policy(root, key) if with_policy else None
    options = ServiceOptions(auth_required=True, key_path=key_file, policy_path=policy_path)
    service = GatewayService(
        root, WriteGateway(SimPlant(), {TAG: POLICY}, "confirm"), options=options
    )
    service.poll_once()
    stop = threading.Event()
    thread = threading.Thread(target=serve, args=(service, SERVICE_INTERVAL_S, stop), daemon=True)
    thread.start()
    client = FileGatewayClient(root, timeout_s=CLIENT_TIMEOUT_S, poll_s=0.01)
    app = FastAPI()
    app.include_router(build_gateway_router(lambda: client))
    holder = [_actor("alice", ("lead",))]
    app.dependency_overrides[actor_of] = lambda: holder[0]
    return Live(root, TestClient(app), client, holder), stop, thread


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Live]:
    """A gateway in confirm mode with a pinned policy file."""
    monkeypatch.delenv("CROSSCUT_SECRETS_DIR", raising=False)
    running, stop, thread = _start(tmp_path, with_policy=True)
    yield running
    stop.set()
    thread.join(timeout=3.0)


@pytest.fixture
def bare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Live]:
    """A gateway without any policy file configured."""
    monkeypatch.delenv("CROSSCUT_SECRETS_DIR", raising=False)
    running, stop, thread = _start(tmp_path, with_policy=False)
    yield running
    stop.set()
    thread.join(timeout=3.0)


def _prompt(call: Any) -> Any:
    """Run an HTTP call and require it to answer well within the client timeout."""
    started = time.monotonic()
    response = call()
    assert time.monotonic() - started < PROMPT_S, "refusal was not answered promptly"
    return response


def _save_draft(live: Live) -> str:
    """Store DOC as the draft (as the current actor) and return its digest."""
    response = live.http.put("/gateway/policy/draft", json=DOC)
    assert response.status_code == 200
    return policy_digest(DOC)


def test_self_pin_is_403(live: Live) -> None:
    """The author pinning their own draft is refused with 403, not a 504."""
    digest = _save_draft(live)
    response = _prompt(lambda: live.http.post("/gateway/policy/pin", json={"digest": digest}))
    assert response.status_code == 403
    assert response.json()["detail"] == "author_equals_approver"


def test_reload_in_confirm_mode_is_409(live: Live) -> None:
    """policy_reload while the gateway is in confirm mode is a 409 conflict."""
    response = _prompt(lambda: live.http.post("/gateway/policy/reload"))
    assert response.status_code == 409
    assert response.json()["detail"] == "reload_requires_off_or_advisory"


def test_pin_without_stepup_is_428(live: Live) -> None:
    """A pin by a second person without step-up is refused with 428."""
    digest = _save_draft(live)
    live.act_as("bob", ("lead",), stepup=False)
    response = _prompt(lambda: live.http.post("/gateway/policy/pin", json={"digest": digest}))
    assert response.status_code == 428
    assert response.json()["detail"] == "step_up_required"


def test_pin_of_tampered_draft_is_409(live: Live) -> None:
    """A draft changed after saving fails its signature: 409 draft_bad_signature."""
    digest = _save_draft(live)
    path = live.root / "_gateway" / "policy-draft.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["author"] = "mallory"
    path.write_text(json.dumps(record), encoding="utf-8")
    live.act_as("bob", ("lead",))
    response = _prompt(lambda: live.http.post("/gateway/policy/pin", json={"digest": digest}))
    assert response.status_code == 409
    assert response.json()["detail"] == "draft_bad_signature"


@pytest.mark.parametrize(
    ("code", "exc"), [("no_draft", "no_draft"), ("draft_changed", "draft_changed")]
)
def test_client_pin_without_matching_draft_raises_conflict(
    live: Live, code: str, exc: str
) -> None:
    """The client maps no_draft and draft_changed answers to a 409-class error."""
    if code == "draft_changed":
        _save_draft(live)
    started = time.monotonic()
    with pytest.raises(ValueError) as caught:
        live.client.policy_pin("e" * 64, actor=_actor("bob", ("lead",)))
    assert time.monotonic() - started < PROMPT_S
    assert str(caught.value) == exc


@pytest.mark.parametrize("route", ["pin", "reload"])
def test_policy_commands_without_policy_file_are_409(bare: Live, route: str) -> None:
    """Without a configured policy file pin and reload answer 409 policy_path_not_configured."""
    digest = _save_draft(bare)
    bare.act_as("bob", ("lead",))
    if route == "pin":
        response = _prompt(lambda: bare.http.post("/gateway/policy/pin", json={"digest": digest}))
    else:
        response = _prompt(lambda: bare.http.post("/gateway/policy/reload"))
    assert response.status_code == 409
    assert response.json()["detail"] == "policy_path_not_configured"


def test_draft_without_permission_is_403(live: Live) -> None:
    """A role without policy.edit gets 403 for the draft at once."""
    live.act_as("vera", ("viewer",))
    response = _prompt(lambda: live.http.put("/gateway/policy/draft", json=DOC))
    assert response.status_code == 403


def test_kill_reset_without_permission_is_403(live: Live) -> None:
    """An operator cannot reset the kill: 403 at once."""
    live.act_as("olga", ("operator",))
    response = _prompt(lambda: live.http.post("/gateway/kill/reset"))
    assert response.status_code == 403


def test_self_approval_is_403(live: Live) -> None:
    """The proposer approving their own proposal is answered 403."""
    live.client._send_command(
        "propose",
        {
            "target_tag": TAG,
            "value": 55.0,
            "proposer": "alice",
            "t_ns": time.time_ns(),
            "reason": "t",
        },
        _actor("alice", ("engineer",)),
    )
    deadline = time.monotonic() + 3.0
    while not live.client.pending() and time.monotonic() < deadline:
        time.sleep(0.05)
    key = str(live.client.pending()[0]["key"])
    response = _prompt(lambda: live.http.post(f"/gateway/pending/{key}/approve"))
    assert response.status_code == 403


def test_unverified_command_is_not_answered(live: Live) -> None:
    """A command with a bad signature gets no reply: the client keeps its timeout."""
    short = FileGatewayClient(live.root, timeout_s=0.4, poll_s=0.01)
    cmd_id = f"{time.time_ns()}-badsig"
    envelope = short._envelope(cmd_id, "kill_reset", {}, _actor("alice", ("lead",)))
    envelope["sig"] = "0" * 64
    inbox = live.root / "_gateway" / "inbox"
    (inbox / f"{cmd_id}.tmp").write_text(json.dumps(envelope), encoding="utf-8")
    os.replace(inbox / f"{cmd_id}.tmp", inbox / f"{cmd_id}.json")
    with pytest.raises(TimeoutError):
        short._await_answer(cmd_id)


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        ("self_pin", PermissionError),
        ("author_is_approver", PermissionError),
        ("author_equals_approver", PermissionError),
        ("self_approval", PermissionError),
        ("missing_permission:policy.pin", PermissionError),
        ("step_up_required", StepUpRequired),
        ("stepup_required", StepUpRequired),
        ("unknown_key", KeyError),
        ("unknown key: abc", KeyError),
        ("wrong_mode_for_reload", ValueError),
        ("reload_requires_off_or_advisory", ValueError),
        ("no_draft", ValueError),
        ("draft_changed", ValueError),
        ("draft_bad_signature", ValueError),
        ("key_missing", ValueError),
        ("key_too_short", ValueError),
        ("policy_path_not_configured", ValueError),
        ("invalid_args", ValueError),
    ],
)
def test_error_code_maps_to_exception_class(code: str, kind: type[Exception]) -> None:
    """Every stable gateway error code becomes the exception class the routes translate."""
    assert isinstance(_error_for(code), kind)


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("self_pin", 403),
        ("author_is_approver", 403),
        ("missing_permission:policy.pin", 403),
        ("step_up_required", 428),
        ("stepup_required", 428),
        ("unknown_key", 404),
        ("wrong_mode_for_reload", 409),
        ("no_draft", 409),
        ("draft_changed", 409),
        ("draft_bad_signature", 409),
        ("key_missing", 409),
        ("key_too_short", 409),
        ("policy_path_not_configured", 409),
    ],
)
def test_route_status_per_code(code: str, status: int) -> None:
    """The reload and draft routes answer the documented HTTP status for each code."""

    class Refusing:
        """Gateway stand-in whose policy commands are refused with one code."""

        def policy_reload(self, actor: object = None) -> None:
            """Refuse with the configured code."""
            raise _error_for(code)

        def policy_draft(self, document: dict[str, Any], actor: object = None) -> None:
            """Refuse with the configured code."""
            raise _error_for(code)

    app = FastAPI()
    app.include_router(build_gateway_router(lambda: Refusing()))  # type: ignore[arg-type]
    app.dependency_overrides[actor_of] = lambda: replace(_actor("a", ("lead",)))
    http = TestClient(app)
    assert http.post("/gateway/policy/reload").status_code == status
    assert http.put("/gateway/policy/draft", json=DOC).status_code == status
