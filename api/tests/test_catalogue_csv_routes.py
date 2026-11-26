"""Tests of the catalogue CSV routes: export, dry run, apply and permissions.

Covers the tag CSV download, a dry run that reports errors without saving,
a clean import that saves, a refused import that leaves the site as it was,
and the permission table entries of both routes.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.auth.route_permissions import ROUTE_PERMISSIONS  # type: ignore[import-untyped,unused-ignore]
from crosscut_api.catalogue_csv_routes import build_catalogue_csv_router  # type: ignore[import-untyped,unused-ignore]
from crosscut_api.site_routes import build_site_router  # type: ignore[import-untyped,unused-ignore]
from crosscut_connectors.site import load_site  # type: ignore[import-untyped,unused-ignore]
from fastapi import FastAPI
from fastapi.testclient import TestClient

BASE_SITE_JSON_PATH = (
    Path(__file__).resolve().parents[2] / "docs/examples/generic_concentrator/_site/site.json"
)


@pytest.fixture
def base_doc() -> dict[str, Any]:
    """A valid site document loaded from the example JSON."""
    doc: dict[str, Any] = json.loads(BASE_SITE_JSON_PATH.read_text(encoding="utf-8"))
    return doc


@pytest.fixture
def client(tmp_path: Path, base_doc: dict[str, Any]) -> TestClient:
    """A client on the site and CSV routers, with the example site saved under ``tmp_path``."""
    app = FastAPI()
    app.include_router(build_site_router(tmp_path))
    app.include_router(build_catalogue_csv_router(tmp_path))
    test_client = TestClient(app)
    assert test_client.put("/site", json=base_doc).status_code == 200
    return test_client


def _edit_first_tag(csv_text: str, column: str, value: str) -> str:
    """The CSV text with one cell of the first tag row replaced."""
    rows = list(csv.reader(io.StringIO(csv_text)))
    rows[1][rows[0].index(column)] = value
    stream = io.StringIO()
    csv.writer(stream, lineterminator="\n").writerows(rows)
    return stream.getvalue()


def test_export_returns_csv_with_header(client: TestClient) -> None:
    """GET /site/tags.csv answers text/csv as a download whose first row is the header."""
    response = client.get("/site/tags.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    header = response.text.splitlines()[0].split(",")
    assert header[0] == "id"


def test_dry_run_reports_errors_and_keeps_site(
    client: TestClient, tmp_path: Path, base_doc: dict[str, Any]
) -> None:
    """A dry run with a bad cell answers the errors and leaves the stored site unchanged."""
    bad = _edit_first_tag(client.get("/site/tags.csv").text, "dtype", "not-a-dtype")

    response = client.post("/site/tags.csv?dry_run=true", content=bad.encode("utf-8"))

    assert response.status_code == 200
    body = response.json()
    assert body["errors"]
    assert body["applied"] is False
    assert load_site(tmp_path) == base_doc


def test_apply_valid_csv_changes_site(
    client: TestClient, tmp_path: Path, base_doc: dict[str, Any]
) -> None:
    """A clean CSV with one changed cell is saved and reported as applied."""
    text = client.get("/site/tags.csv").text
    rows = list(csv.reader(io.StringIO(text)))
    old = rows[1][rows[0].index("dtype")]
    new = "string" if old != "string" else "float"
    edited = _edit_first_tag(text, "dtype", new)

    response = client.post("/site/tags.csv?dry_run=false", content=edited.encode("utf-8"))

    assert response.status_code == 200
    assert response.json()["applied"] is True
    assert load_site(tmp_path) != base_doc
    assert load_site(tmp_path)["tags"][0]["dtype"] == new


def test_apply_with_errors_returns_422_and_keeps_site(
    client: TestClient, tmp_path: Path, base_doc: dict[str, Any]
) -> None:
    """An import with errors is refused with 422 and the stored site is unchanged."""
    bad = _edit_first_tag(client.get("/site/tags.csv").text, "dtype", "not-a-dtype")

    response = client.post("/site/tags.csv?dry_run=false", content=bad.encode("utf-8"))

    assert response.status_code == 422
    assert response.json()["errors"]
    assert response.json()["applied"] is False
    assert load_site(tmp_path) == base_doc


def test_permission_table_has_both_routes() -> None:
    """GET needs data.view and POST needs config.edit on /site/tags.csv."""
    assert ROUTE_PERMISSIONS[("GET", "/site/tags.csv")] == "data.view"
    assert ROUTE_PERMISSIONS[("POST", "/site/tags.csv")] == "config.edit"
