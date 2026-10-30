"""Tests of the schema and config routes: schema listing, schema loading and config round trips.

Covers validation errors, unknown kinds and ids, and the site document's fixed config id.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.schema_routes import build_schema_router  # type: ignore[import-untyped,unused-ignore]
from fastapi import FastAPI
from fastapi.testclient import TestClient

BASE_SITE_JSON_PATH = (
    Path(__file__).resolve().parents[2] / "docs/examples/generic_concentrator/_site/site.json"
)
EXPECTED_SCHEMAS = ("anomaly", "site", "softsensor", "supervisor")
VALID_ANOMALY_DOC: dict[str, Any] = {
    "schema_version": "1.0.0",
    "id": "a1",
    "tags": ["t1", "t2", "t3"],
    "mode": "advisory",
}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """A client on an app with only the schema router and ``tmp_path`` as config root."""
    app = FastAPI()
    app.include_router(build_schema_router(tmp_path))
    return TestClient(app)


@pytest.fixture
def base_site_doc() -> dict[str, Any]:
    """A valid site document loaded from the example JSON."""
    doc: dict[str, Any] = json.loads(BASE_SITE_JSON_PATH.read_text(encoding="utf-8"))
    return doc


def _detail_text(response_json: dict[str, Any]) -> str:
    """Joins the validator messages of a 422 response into one searchable string."""
    detail = response_json["detail"]
    return "\n".join(detail) if isinstance(detail, list) else str(detail)


def test_get_schemas_lists_expected_names(client: TestClient) -> None:
    """GET /schemas returns 200 and a sorted list that includes the four known schemas."""
    response = client.get("/schemas")

    assert response.status_code == 200
    names = response.json()["schemas"]
    assert names == sorted(names)
    for expected in EXPECTED_SCHEMAS:
        assert expected in names, expected


def test_get_schema_anomaly_returns_parsed_document(client: TestClient) -> None:
    """GET /schemas/anomaly returns the parsed PCA anomaly schema with its title."""
    response = client.get("/schemas/anomaly")

    assert response.status_code == 200
    assert response.json()["title"] == "PCA anomaly detection configuration"


def test_get_unknown_schema_returns_404(client: TestClient) -> None:
    """GET /schemas/nope is refused with 404."""
    response = client.get("/schemas/nope")

    assert response.status_code == 404


def test_get_config_unknown_kind_returns_404(client: TestClient) -> None:
    """GET /config/unknown/x is refused with 404."""
    response = client.get("/config/unknown/x")

    assert response.status_code == 404


def test_get_config_missing_file_returns_404(client: TestClient) -> None:
    """GET /config/anomaly/a1 on an empty root is refused with 404."""
    response = client.get("/config/anomaly/a1")

    assert response.status_code == 404


def test_put_anomaly_writes_file_and_get_returns_it(
    client: TestClient, tmp_path: Path
) -> None:
    """PUT of a valid anomaly doc returns 200, writes the file, and GET reads it back."""
    response = client.put("/config/anomaly/a1", json=VALID_ANOMALY_DOC)

    assert response.status_code == 200
    assert response.json() == VALID_ANOMALY_DOC
    stored_path = tmp_path / "_anomaly" / "a1.json"
    assert stored_path.is_file()
    assert json.loads(stored_path.read_text(encoding="utf-8")) == VALID_ANOMALY_DOC
    stored = client.get("/config/anomaly/a1")
    assert stored.status_code == 200
    assert stored.json() == VALID_ANOMALY_DOC


def test_put_anomaly_without_mode_is_refused(client: TestClient, tmp_path: Path) -> None:
    """An anomaly doc missing ``mode`` is refused with 422 and no file is created."""
    doc = copy.deepcopy(VALID_ANOMALY_DOC)
    doc.pop("mode")

    response = client.put("/config/anomaly/a1", json=doc)

    assert response.status_code == 422
    assert "mode" in _detail_text(response.json())
    assert not (tmp_path / "_anomaly" / "a1.json").exists()


def test_put_anomaly_with_single_tag_is_refused(client: TestClient, tmp_path: Path) -> None:
    """An anomaly doc with only one tag is refused with 422 and no file is created."""
    doc = copy.deepcopy(VALID_ANOMALY_DOC)
    doc["tags"] = ["t1"]

    response = client.put("/config/anomaly/a1", json=doc)

    assert response.status_code == 422
    assert "tags" in _detail_text(response.json())
    assert not (tmp_path / "_anomaly" / "a1.json").exists()


def test_put_anomaly_with_mismatched_id_is_refused(client: TestClient) -> None:
    """An anomaly doc whose ``id`` differs from the URL id is refused with 422."""
    doc = copy.deepcopy(VALID_ANOMALY_DOC)
    doc["id"] = "other"

    response = client.put("/config/anomaly/a1", json=doc)

    assert response.status_code == 422
    assert "does not match" in _detail_text(response.json())


def test_put_config_unknown_kind_returns_404(client: TestClient) -> None:
    """PUT /config/unknown/x is refused with 404."""
    response = client.put("/config/unknown/x", json={"id": "x"})

    assert response.status_code == 404


def test_put_site_writes_file_and_get_returns_it(
    client: TestClient, tmp_path: Path, base_site_doc: dict[str, Any]
) -> None:
    """PUT of the example site document returns 200, writes the file, and GET reads it back."""
    response = client.put("/config/site/site", json=base_site_doc)

    assert response.status_code == 200
    assert (tmp_path / "_site" / "site.json").is_file()
    stored = client.get("/config/site/site")
    assert stored.status_code == 200
    assert stored.json() == base_site_doc


def test_put_site_with_unknown_tag_is_refused(
    client: TestClient, base_site_doc: dict[str, Any]
) -> None:
    """A site document whose first loop names a missing tag is refused with 422."""
    doc = copy.deepcopy(base_site_doc)
    doc["loops"][0]["pv"] = "NO.SUCH.TAG"

    response = client.put("/config/site/site", json=doc)

    assert response.status_code == 422
    assert "unknown tag" in _detail_text(response.json())


def test_put_site_with_other_id_returns_404(
    client: TestClient, base_site_doc: dict[str, Any]
) -> None:
    """PUT /config/site/other is refused with 404 because the site config id is fixed."""
    response = client.put("/config/site/other", json=base_site_doc)

    assert response.status_code == 404
