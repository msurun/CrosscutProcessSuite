"""Tests of the site catalogue routes: read, replace, and import settings.

Covers error handling for missing, invalid, or corrupt site files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.site_routes import build_site_router  # type: ignore[import-untyped,unused-ignore]
from fastapi import FastAPI
from fastapi.testclient import TestClient

BASE_SITE_JSON_PATH = (
    Path(__file__).resolve().parents[2] / "docs/examples/generic_concentrator/_site/site.json"
)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """A client on an app with only the site router and ``tmp_path`` as data root."""
    app = FastAPI()
    app.include_router(build_site_router(tmp_path))
    return TestClient(app)


@pytest.fixture
def base_doc(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    """A valid site document loaded from the example JSON."""
    doc: dict[str, Any] = json.loads(BASE_SITE_JSON_PATH.read_text(encoding="utf-8"))
    return doc


def test_get_site_returns_404_when_no_file_exists(client: TestClient) -> None:
    response = client.get("/site")
    assert response.status_code == 404
    assert response.json()["detail"] == "no site file"


def test_put_site_saves_and_returns_document(
    client: TestClient, tmp_path: Path, base_doc: dict[str, Any]
) -> None:
    response = client.put("/site", json=base_doc)
    assert response.status_code == 200
    assert response.json() == base_doc

    # Verify file exists on disk
    stored_path = tmp_path / "_site" / "site.json"
    assert stored_path.is_file()
    assert json.loads(stored_path.read_text()) == base_doc

    # Verify GET returns the same
    get_response = client.get("/site")
    assert get_response.status_code == 200
    assert get_response.json() == base_doc


def test_put_site_rejects_invalid_dtype_with_422(
    client: TestClient, tmp_path: Path, base_doc: dict[str, Any]
) -> None:
    invalid_doc = base_doc.copy()
    # Create a copy of the tags list to avoid mutating the fixture
    invalid_tags = [tag.copy() for tag in invalid_doc["tags"]]
    invalid_tags[0]["dtype"] = "XX"
    invalid_doc["tags"] = invalid_tags

    response = client.put("/site", json=invalid_doc)
    assert response.status_code == 422
    # The error detail is a list of strings from the validator
    errors = response.json()["detail"]
    assert any("tags.0.dtype" in err for err in errors)

    # Verify no file was written
    assert not (tmp_path / "_site" / "site.json").exists()


def test_put_site_rejects_duplicate_tag_ids(
    client: TestClient, tmp_path: Path, base_doc: dict[str, Any]
) -> None:
    invalid_doc = base_doc.copy()
    invalid_tags = [tag.copy() for tag in invalid_doc["tags"]]
    # Duplicate the first tag's ID into the second tag
    invalid_tags[1]["id"] = invalid_tags[0]["id"]
    invalid_doc["tags"] = invalid_tags

    response = client.put("/site", json=invalid_doc)
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any("duplicate id" in err for err in errors)


def test_get_import_settings_returns_404_without_file(client: TestClient) -> None:
    response = client.get("/site/import-settings")
    assert response.status_code == 404


def test_get_import_settings_returns_correct_structure(
    client: TestClient, base_doc: dict[str, Any]
) -> None:
    client.put("/site", json=base_doc)
    response = client.get("/site/import-settings")
    assert response.status_code == 200

    data = response.json()
    expected_keys = {"missing_codes", "decimal_comma", "delimiter", "time_names"}
    assert set(data.keys()) == expected_keys
    assert data["missing_codes"] == []
    assert data["decimal_comma"] is False
    assert data["delimiter"] == ","
    assert "timestamp" in data["time_names"]
    assert data["time_names"] == sorted(data["time_names"])


def test_import_settings_reflect_updated_values(
    client: TestClient, base_doc: dict[str, Any]
) -> None:
    client.put("/site", json=base_doc)

    updated_doc = base_doc.copy()
    updated_import = updated_doc["import"].copy()
    updated_import["missing_codes"] = [-999]
    updated_import["delimiter"] = ";"
    updated_import["decimal_comma"] = True
    updated_doc["import"] = updated_import

    client.put("/site", json=updated_doc)

    response = client.get("/site/import-settings")
    assert response.status_code == 200
    data = response.json()
    assert data["missing_codes"] == [-999.0]
    assert data["delimiter"] == ";"
    assert data["decimal_comma"] is True


def test_get_site_returns_422_on_corrupt_json(client: TestClient, tmp_path: Path) -> None:
    site_dir = tmp_path / "_site"
    site_dir.mkdir(parents=True)
    site_file = site_dir / "site.json"
    site_file.write_text("not valid json {", encoding="utf-8")

    response = client.get("/site")
    assert response.status_code == 422
    assert len(response.json()["detail"]) > 0
