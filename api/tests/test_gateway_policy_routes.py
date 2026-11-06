"""Contract tests for the policy editor routes: live policy, draft read/write and pin.

The router runs without the app-level enforcer (roles are covered in test_gateway_roles);
the file client is checked against hand-written draft and state files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.gateway_client import FileGatewayClient
from crosscut_api.gateway_routes import build_gateway_router, policy_digest
from crosscut_gateway import policy_file
from fastapi import FastAPI
from fastapi.testclient import TestClient

DOC: dict[str, Any] = {"version": 1, "mode": "advisory", "targets": {"Ünï.SP": {"max_step": 1}}}
PIN = {"digest": "a" * 64, "author": "eng1", "approver": "lead1", "approved_at": "t0"}


class PolicyFake:
    """In-memory gateway offering only the policy operations."""

    def __init__(self) -> None:
        """Start with no draft and no pinned policy."""
        self.draft: dict[str, Any] | None = None
        self.live: dict[str, Any] | None = None
        self.refuse: str | None = None
        self.calls: list[str] = []

    def draft_policy(self) -> dict[str, Any] | None:
        """Return the stored draft record."""
        return self.draft

    def live_policy(self) -> dict[str, Any] | None:
        """Return the live policy."""
        return self.live

    def policy_draft(self, document: dict[str, Any], actor: object = None) -> None:
        """Store the draft or refuse with the configured message."""
        if self.refuse:
            raise ValueError(self.refuse)
        self.draft = {"document": document, "author": "eng1", "saved_at": "2026-01-01T00:00:00Z"}

    def policy_pin(self, digest: str, actor: object = None) -> None:
        """Record the pin."""
        self.calls.append(f"pin:{digest}")

    def policy_reload(self, actor: object = None) -> None:
        """Record the reload or refuse with the configured message."""
        if self.refuse:
            raise ValueError(self.refuse)
        self.calls.append("reload")


@pytest.fixture
def fake() -> PolicyFake:
    """A fresh policy fake."""
    return PolicyFake()


@pytest.fixture
def client(fake: PolicyFake) -> TestClient:
    """The gateway router over the fake, without enforcement."""
    app = FastAPI()
    app.include_router(build_gateway_router(lambda: fake))  # type: ignore[arg-type]
    return TestClient(app)


def test_digest_equals_the_gateway_digest() -> None:
    """The API's local digest function matches the gateway's for the same document."""
    for document in (DOC, {"b": 1, "a": [1, 2], "ü": "é"}, {}):
        assert policy_digest(document) == policy_file.policy_digest(document)


def test_get_draft_is_404_without_a_draft(client: TestClient) -> None:
    """With no stored draft the route answers 404 no draft."""
    response = client.get("/gateway/policy/draft")
    assert response.status_code == 404
    assert response.json() == {"detail": "no draft"}


def test_put_then_get_draft_round_trips_with_digest(client: TestClient) -> None:
    """PUT stores the draft and returns its digest; GET returns record plus the same digest."""
    put = client.put("/gateway/policy/draft", json=DOC)
    assert put.status_code == 200
    assert put.json() == {"ok": True, "digest": policy_file.policy_digest(DOC)}
    got = client.get("/gateway/policy/draft").json()
    assert got == {
        "document": DOC,
        "author": "eng1",
        "saved_at": "2026-01-01T00:00:00Z",
        "digest": put.json()["digest"],
    }


def test_put_draft_refusal_is_422_with_the_message(client: TestClient, fake: PolicyFake) -> None:
    """A schema or semantic refusal comes back as 422 with the gateway's message."""
    fake.refuse = "Target 'FIC1.SP': limits[0] (5.0) > limits[1] (1.0)"
    response = client.put("/gateway/policy/draft", json=DOC)
    assert response.status_code == 422
    assert response.json() == {"detail": fake.refuse}
    assert fake.draft is None


def test_get_policy_is_all_null_without_a_pinned_policy(client: TestClient) -> None:
    """Without a verified live policy every field is null."""
    response = client.get("/gateway/policy")
    assert response.status_code == 200
    assert response.json() == {"document": None, "pin": None, "mode_cap": None, "digest": None}


def test_get_policy_returns_document_pin_mode_cap_and_digest(
    client: TestClient, fake: PolicyFake
) -> None:
    """The live policy carries its pin, the mode cap and the canonical digest."""
    fake.live = {"document": DOC, "pin": PIN}
    assert client.get("/gateway/policy").json() == {
        "document": DOC,
        "pin": PIN,
        "mode_cap": "advisory",
        "digest": policy_file.policy_digest(DOC),
    }


def test_pin_with_the_reviewed_digest_reaches_the_gateway(
    client: TestClient, fake: PolicyFake
) -> None:
    """Pinning the digest of the stored draft succeeds."""
    client.put("/gateway/policy/draft", json=DOC)
    digest = policy_digest(DOC)
    assert client.post("/gateway/policy/pin", json={"digest": digest}).json() == {"ok": True}
    assert fake.calls == [f"pin:{digest}"]


def test_pin_after_the_draft_changed_is_409_draft_changed(
    client: TestClient, fake: PolicyFake
) -> None:
    """A draft replaced after review makes the old digest fail with 409 draft_changed."""
    client.put("/gateway/policy/draft", json=DOC)
    reviewed = policy_digest(DOC)
    client.put("/gateway/policy/draft", json={**DOC, "mode": "off"})
    response = client.post("/gateway/policy/pin", json={"digest": reviewed})
    assert response.status_code == 409
    assert response.json() == {"detail": "draft_changed"}
    assert fake.calls == []


def test_pin_without_a_draft_is_409(client: TestClient) -> None:
    """Pinning with no stored draft is refused with 409 no_draft."""
    response = client.post("/gateway/policy/pin", json={"digest": "0" * 64})
    assert (response.status_code, response.json()["detail"]) == (409, "no_draft")


def test_reload_ok_and_refusal_is_409(client: TestClient, fake: PolicyFake) -> None:
    """Reload answers ok, and a gateway refusal becomes 409."""
    assert client.post("/gateway/policy/reload").json() == {"ok": True}
    fake.refuse = "reload_requires_off_or_advisory"
    response = client.post("/gateway/policy/reload")
    assert (response.status_code, response.json()["detail"]) == (
        409,
        "reload_requires_off_or_advisory",
    )


def test_file_client_reads_draft_without_signature_and_live_from_state(tmp_path: Path) -> None:
    """The file client drops draft_sig and returns the state.json policy view."""
    gateway_dir = tmp_path / "_gateway"
    gateway_dir.mkdir()
    saved = {"document": DOC, "author": "eng1", "saved_at": "t", "draft_sig": "x"}
    (gateway_dir / "policy-draft.json").write_text(json.dumps(saved), encoding="utf-8")
    state = {"policy": {"document": DOC, "pin": PIN}}
    (gateway_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    client = FileGatewayClient(tmp_path)
    assert client.draft_policy() == {"document": DOC, "author": "eng1", "saved_at": "t"}
    assert client.live_policy() == state["policy"]
    (gateway_dir / "state.json").write_text(json.dumps({"policy": None}), encoding="utf-8")
    assert client.live_policy() is None
