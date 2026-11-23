"""Source management routes (#208): site.json entries, OS secret store and step-up.

Every test runs on a MemoryStore installed through ``use_store``; the real OS keyring is never
touched. Checks validation, secret handling (never echoed, never audited), 409/404/503 paths and
the permission and step-up rules of the real app-level enforcer.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, FakeClock, csrf, login, seed_users, stepup
from crosscut_api.auth.deps import AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.source_admin_routes import build_source_admin_router
from crosscut_connectors.secret_store import MemoryStore, SecretStoreError, use_store
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

SECRET = "user:S3cr3t-pw!"
PI: dict[str, Any] = {
    "driver": "piwebapi",
    "base_url": "https://pi.example/piwebapi",
    "auth": {"kind": "basic", "credential_env": "PI_CRED"},
}


class DownStore:
    """A secret store whose writes and deletes fail like an unavailable OS store."""

    def get(self, ref: str) -> str | None:
        """Nothing is readable."""
        return None

    def set(self, ref: str, value: str) -> None:
        """Refuse the write."""
        raise SecretStoreError("secret store refused the write: KeyringError")

    def delete(self, ref: str) -> None:
        """Refuse the delete."""
        raise SecretStoreError("secret store refused the delete: KeyringError")


@pytest.fixture
def store() -> Iterator[MemoryStore]:
    """An in-memory secret store installed as the default; the previous one is restored."""
    memory = MemoryStore()
    previous = use_store(memory)
    yield memory
    use_store(previous)


@pytest.fixture
def open_client(tmp_path: Path, store: MemoryStore) -> TestClient:
    """A client on an app without authentication (local actor, all permissions)."""
    app = FastAPI()
    app.include_router(build_source_admin_router(tmp_path))
    return TestClient(app)


@pytest.fixture
def world(tmp_path: Path, store: MemoryStore) -> tuple[FastAPI, Path]:
    """A mini app: enforcer, auth router and source admin router over a data root."""
    seed_users(tmp_path, DEFAULT_USERS)
    clock = FakeClock()
    ctx = build_auth_context(tmp_path, TEST_CONFIG, clock)
    app = FastAPI(dependencies=[Depends(make_enforcer(AuthGuards(ctx), ctx))])
    app.include_router(build_auth_router_for(ctx))
    app.include_router(build_source_admin_router(tmp_path, clock=clock))
    return app, tmp_path


def as_user(app: FastAPI, name: str) -> tuple[TestClient, dict[str, str]]:
    """A logged-in client and its CSRF header."""
    client = TestClient(app)
    return client, csrf(login(client, name))


def _site(root: Path) -> dict[str, Any]:
    """The site.json document under the data root."""
    found = list(root.rglob("site.json"))
    assert len(found) == 1, found
    doc: dict[str, Any] = json.loads(found[0].read_text(encoding="utf-8"))
    return doc


def _audit_text(root: Path) -> str:
    """The raw auth audit file ('' when none was written)."""
    path = root / "_auth" / "auth-audit.jsonl"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _add_pi(client: TestClient, headers: dict[str, str] | None = None) -> None:
    """Create the ``pi1`` source and assert success."""
    response = client.put("/sources/pi1", json=PI, headers=headers)
    assert response.status_code == 200, response.text


def test_put_source_creates_entry_without_secret(open_client: TestClient, tmp_path: Path) -> None:
    """A new source is saved to site.json and reports no stored secret."""
    response = open_client.put("/sources/pi1", json=PI)
    assert response.status_code == 200
    assert response.json()["secret_stored"] is False
    assert _site(tmp_path)["sources"][0]["id"] == "pi1"


def test_put_source_path_id_wins_over_body(open_client: TestClient, tmp_path: Path) -> None:
    """The id in the path replaces any id in the body."""
    response = open_client.put("/sources/pi1", json={**PI, "id": "other"})
    assert response.json()["id"] == "pi1"
    assert [s["id"] for s in _site(tmp_path)["sources"]] == ["pi1"]


def test_put_invalid_driver_is_422_and_not_saved(open_client: TestClient, tmp_path: Path) -> None:
    """An unknown driver is rejected with 422 and leaves no site file entry."""
    response = open_client.put("/sources/bad", json={"driver": "nope"})
    assert response.status_code == 422
    assert not list(tmp_path.rglob("site.json"))


def test_put_secret_stores_value_and_points_auth_at_it(
    open_client: TestClient, store: MemoryStore, tmp_path: Path
) -> None:
    """The secret goes to the store and site.json only carries a reference."""
    _add_pi(open_client)
    response = open_client.put("/sources/pi1/secret", json={"value": SECRET})
    assert response.status_code == 200
    assert response.json() == {"source": "pi1", "stored": True}
    assert store.get("source.pi1") == SECRET
    assert _site(tmp_path)["sources"][0]["auth"] == {
        "kind": "basic",
        "credential_ref": "source.pi1",
    }
    assert open_client.get("/sources/pi1/secret").json() == {"source": "pi1", "stored": True}


def test_secret_status_false_before_set(open_client: TestClient) -> None:
    """Before a secret is stored the status says so."""
    _add_pi(open_client)
    assert open_client.get("/sources/pi1/secret").json()["stored"] is False


def test_delete_secret_forgets_value(open_client: TestClient, store: MemoryStore) -> None:
    """DELETE of the secret removes it from the store."""
    _add_pi(open_client)
    open_client.put("/sources/pi1/secret", json={"value": SECRET})
    response = open_client.delete("/sources/pi1/secret")
    assert response.json() == {"source": "pi1", "stored": False}
    assert store.get("source.pi1") is None


@pytest.mark.parametrize("auth", [{"kind": "kerberos"}, None])
def test_secret_for_kerberos_or_no_auth_is_409(
    open_client: TestClient, store: MemoryStore, auth: dict[str, Any] | None
) -> None:
    """Only basic and bearer sources can hold a secret."""
    source = {k: v for k, v in PI.items() if k != "auth"}
    if auth is not None:
        source["auth"] = auth
    assert open_client.put("/sources/pi1", json=source).status_code == 200
    response = open_client.put("/sources/pi1/secret", json={"value": SECRET})
    assert response.status_code == 409
    assert store.get("source.pi1") is None


def test_empty_secret_is_422(open_client: TestClient) -> None:
    """An empty value is refused by the request model."""
    _add_pi(open_client)
    assert open_client.put("/sources/pi1/secret", json={"value": ""}).status_code == 422


def test_unknown_source_is_404_on_secret_routes_and_delete(open_client: TestClient) -> None:
    """Secret routes and DELETE answer 404 for a source that does not exist."""
    assert open_client.get("/sources/ghost/secret").status_code == 404
    assert open_client.put("/sources/ghost/secret", json={"value": SECRET}).status_code == 404
    assert open_client.delete("/sources/ghost/secret").status_code == 404
    assert open_client.delete("/sources/ghost").status_code == 404


def test_delete_source_removes_entry_and_secret(
    open_client: TestClient, store: MemoryStore, tmp_path: Path
) -> None:
    """Deleting a source drops its entry and its stored secret."""
    _add_pi(open_client)
    open_client.put("/sources/pi1/secret", json={"value": SECRET})
    response = open_client.delete("/sources/pi1")
    assert response.json() == {"deleted": "pi1"}
    assert store.get("source.pi1") is None
    assert _site(tmp_path)["sources"] == []


def test_delete_source_in_use_is_409_and_keeps_everything(
    open_client: TestClient, store: MemoryStore, tmp_path: Path
) -> None:
    """A source read by a catalogue tag is not deleted and keeps its secret."""
    _add_pi(open_client)
    open_client.put("/sources/pi1/secret", json={"value": SECRET})
    path = next(tmp_path.rglob("site.json"))
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["tags"] = [{"id": "t.pv", "source": "pi1"}]
    path.write_text(json.dumps(doc), encoding="utf-8")
    response = open_client.delete("/sources/pi1")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "source_in_use"
    assert store.get("source.pi1") == SECRET
    assert [s["id"] for s in _site(tmp_path)["sources"]] == ["pi1"]


def test_unavailable_store_on_secret_write_is_503_and_site_unchanged(
    open_client: TestClient, tmp_path: Path
) -> None:
    """When the store refuses the write, nothing changes in site.json."""
    _add_pi(open_client)
    before = _site(tmp_path)
    previous = use_store(DownStore())
    try:
        response = open_client.put("/sources/pi1/secret", json={"value": SECRET})
    finally:
        use_store(previous)
    assert response.status_code == 503
    assert _site(tmp_path) == before
    assert SECRET not in response.text


def test_unavailable_store_on_delete_is_503(open_client: TestClient) -> None:
    """When the store refuses the delete, secret and source deletion answer 503."""
    _add_pi(open_client)
    previous = use_store(DownStore())
    try:
        assert open_client.delete("/sources/pi1/secret").status_code == 503
        assert open_client.delete("/sources/pi1").status_code == 503
    finally:
        use_store(previous)


def test_test_draft_connects_csv_and_reports_capabilities(
    open_client: TestClient, tmp_path: Path
) -> None:
    """A draft csv source over an existing folder reports ok and its capabilities."""
    folder = tmp_path / "csvdata"
    folder.mkdir()
    body = {"id": "x", "driver": "csv", "endpoint": str(folder)}
    response = open_client.post("/sources/test-draft", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["capabilities"]


def test_test_draft_invalid_is_422(open_client: TestClient) -> None:
    """A draft with an unknown driver is a validation error."""
    response = open_client.post("/sources/test-draft", json={"id": "x", "driver": "nope"})
    assert response.status_code == 422


def test_no_response_or_audit_contains_the_secret(open_client: TestClient, tmp_path: Path) -> None:
    """Neither any response body nor the audit file ever carries the secret value."""
    texts = [open_client.put("/sources/pi1", json=PI).text]
    texts.append(open_client.put("/sources/pi1/secret", json={"value": SECRET}).text)
    texts.append(open_client.get("/sources/pi1/secret").text)
    texts.append(open_client.delete("/sources/pi1/secret").text)
    texts.append(open_client.delete("/sources/pi1").text)
    assert all(SECRET not in text for text in texts)
    audit = _audit_text(tmp_path)
    assert "source_secret_set" in audit and SECRET not in audit
    assert SECRET not in json.dumps(_site(tmp_path))


@pytest.mark.parametrize("user", ["view1", "op1"])
def test_viewer_and_operator_cannot_edit_sources(world: tuple[FastAPI, Path], user: str) -> None:
    """config.edit is an engineer permission; lower roles get 403 on every edit route."""
    app, _ = world
    client, headers = as_user(app, user)
    assert client.put("/sources/pi1", json=PI, headers=headers).status_code == 403
    assert client.delete("/sources/pi1", headers=headers).status_code == 403
    assert client.get("/sources/pi1/secret").status_code == 403
    assert client.delete("/sources/pi1/secret", headers=headers).status_code == 403


def test_engineer_can_edit_sources(world: tuple[FastAPI, Path]) -> None:
    """An engineer may add a source."""
    app, _ = world
    client, headers = as_user(app, "eng1")
    assert client.put("/sources/pi1", json=PI, headers=headers).status_code == 200


def test_put_secret_needs_fresh_stepup(world: tuple[FastAPI, Path], store: MemoryStore) -> None:
    """Storing a secret is refused with 428 until the engineer re-verifies the password."""
    app, root = world
    client = TestClient(app)
    payload = login(client, "eng1")
    headers = csrf(payload)
    _add_pi(client, headers)
    refused = client.put("/sources/pi1/secret", json={"value": SECRET}, headers=headers)
    assert refused.status_code == 428
    assert store.get("source.pi1") is None
    stepup(client, payload)
    allowed = client.put("/sources/pi1/secret", json={"value": SECRET}, headers=headers)
    assert allowed.status_code == 200
    assert store.get("source.pi1") == SECRET
    audit = _audit_text(root)
    assert "source_secret_set" in audit and "eng1" in audit and SECRET not in audit


def test_test_draft_needs_connector_use(world: tuple[FastAPI, Path], tmp_path: Path) -> None:
    """The viewer role has no connector.use; the engineer may try a draft."""
    app, _ = world
    folder = tmp_path / "csvdata"
    folder.mkdir()
    body = {"id": "x", "driver": "csv", "endpoint": str(folder)}
    viewer, viewer_headers = as_user(app, "view1")
    assert viewer.post("/sources/test-draft", json=body, headers=viewer_headers).status_code == 403
    engineer, engineer_headers = as_user(app, "eng1")
    response = engineer.post("/sources/test-draft", json=body, headers=engineer_headers)
    assert response.status_code == 200, response.text
