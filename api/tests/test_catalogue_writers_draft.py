"""Every catalogue writer goes through the site draft (#247, follow-up of #165).

Each writer must leave ``_site/site.json`` (the published catalogue) untouched, land its change
in ``_site/draft.json`` and be refused with 409 ``pending_exists`` while a publish waits.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.app import create_app
from crosscut_connectors.secret_store import MemoryStore, use_store
from fastapi.testclient import TestClient
from test_catalogue_source_routes import _import_body, _preview, _rules, _seed

Writer = Callable[[TestClient], Any]
PI: dict[str, Any] = {"driver": "piwebapi", "base_url": "https://pi.example/piwebapi"}
BASIC = {**PI, "auth": {"kind": "basic", "credential_env": "PI_CRED"}}
MAPPING = {
    "signals": [{"tag": "LIC1.PV", "role": "pv", "loop": "LIC1"}],
    "loops": [{"id": "LIC1", "pv": "LIC1.PV", "out": "LIC1.OUT"}],
}


@pytest.fixture(autouse=True)
def memory_secrets() -> Any:
    """Keep the OS keyring out of the secret-writing test."""
    previous = use_store(MemoryStore())
    yield
    use_store(previous)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Open app over a seeded data root with a published site of one CSV source."""
    _seed(tmp_path)
    path = tmp_path / "_site" / "site.json"
    site = json.loads(path.read_text(encoding="utf-8"))
    site["sources"].append({**BASIC, "id": "pi1"})
    path.write_text(json.dumps(site), encoding="utf-8")
    return TestClient(create_app(tmp_path, auth_enabled=False))


def _put_source(c: TestClient) -> Any:
    return c.put("/sources/pi2", json=PI)


def _delete_source(c: TestClient) -> Any:
    return c.delete("/sources/s1")


def _put_secret(c: TestClient) -> Any:
    return c.put("/sources/pi1/secret", json={"value": "user:pw"})


def _put_mapping(c: TestClient) -> Any:
    return c.put("/catalogue/mapping", json=MAPPING)


def _import(c: TestClient) -> Any:
    rules = _rules()
    return c.post("/sources/s1/catalogue-import", json=_import_body(_preview(c, rules), rules))


WRITERS: dict[str, Writer] = {
    "put_source": _put_source,
    "delete_source": _delete_source,
    "put_secret": _put_secret,
    "put_mapping": _put_mapping,
    "catalogue_import": _import,
}


def _published(root: Path) -> bytes:
    return (root / "_site" / "site.json").read_bytes()


def _draft(root: Path) -> dict[str, Any]:
    return json.loads((root / "_site" / "draft.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(WRITERS))
def test_writer_lands_in_the_draft_only(name: str, client: TestClient, tmp_path: Path) -> None:
    """The change is in draft.json; the published site.json is byte-identical."""
    before = _published(tmp_path)
    response = WRITERS[name](client)
    assert response.status_code == 200, response.text
    assert _published(tmp_path) == before
    assert (tmp_path / "_site" / "draft.json").exists()
    assert client.get("/site/status").json()["has_draft"] is True


@pytest.mark.parametrize("name", list(WRITERS))
def test_writer_is_refused_while_a_publish_waits(
    name: str, client: TestClient, tmp_path: Path
) -> None:
    """409 pending_exists, and neither the published file nor a draft changes."""
    before = _published(tmp_path)
    (tmp_path / "_site" / "pending_publish.json").write_text("{}", encoding="utf-8")
    response = WRITERS[name](client)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "pending_exists"
    assert _published(tmp_path) == before
    assert not (tmp_path / "_site" / "draft.json").exists()


def test_source_saved_to_the_draft_is_listed_and_testable_before_publish(
    client: TestClient, tmp_path: Path
) -> None:
    """The source form sees its own draft entry: the list and the source lookup read the draft."""
    client.put("/sources/pi2", json=PI)
    expected = {"s1", "pi1", "pi2"}
    assert {s["id"] for s in client.get("/sources").json()["sources"]} == expected
    assert {s["id"] for s in _draft(tmp_path)["sources"]} == expected


def test_a_second_writer_builds_on_the_draft(client: TestClient, tmp_path: Path) -> None:
    """Edits accumulate in one draft instead of each starting from the published file."""
    client.put("/sources/pi2", json=PI)
    client.put("/catalogue/mapping", json=MAPPING)
    draft = _draft(tmp_path)
    assert "pi2" in {s["id"] for s in draft["sources"]}
    assert "LIC1.PV" in {t["id"] for t in draft["tags"]}
