"""Tests of the site catalogue routes: round trip, reference and unit validation.

Covers the full example document, unknown tags, equipment parent cycles,
unconvertible lab units and the import settings endpoint.
"""

from __future__ import annotations

import copy
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
SECTIONS = ("equipment", "loops", "labs", "modes", "signals")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """A client on an app with only the site router and ``tmp_path`` as data root."""
    app = FastAPI()
    app.include_router(build_site_router(tmp_path))
    return TestClient(app)


@pytest.fixture
def base_doc() -> dict[str, Any]:
    """A valid site document loaded from the example JSON."""
    doc: dict[str, Any] = json.loads(BASE_SITE_JSON_PATH.read_text(encoding="utf-8"))
    return doc


def _detail_text(response_json: dict[str, Any]) -> str:
    """Joins the validator messages of a 422 response into one searchable string."""
    detail = response_json["detail"]
    return "\n".join(detail) if isinstance(detail, list) else str(detail)


def test_put_then_get_round_trips_example(client: TestClient, base_doc: dict[str, Any]) -> None:
    """PUT of the full example returns 200 and GET returns the same sections."""
    response = client.put("/site", json=base_doc)
    assert response.status_code == 200

    stored = client.get("/site")
    assert stored.status_code == 200
    got = stored.json()
    for section in SECTIONS:
        assert got[section] == base_doc[section], section
    assert got == base_doc


def test_put_rejects_loop_with_unknown_tag(
    client: TestClient, tmp_path: Path, base_doc: dict[str, Any]
) -> None:
    """A loop whose pv names a missing tag is refused and nothing new is stored."""
    assert client.put("/site", json=base_doc).status_code == 200
    stored_path = tmp_path / "_site" / "site.json"
    before = stored_path.read_bytes()

    doc = copy.deepcopy(base_doc)
    doc["loops"][0]["pv"] = "NO.SUCH.TAG"
    response = client.put("/site", json=doc)

    assert response.status_code == 422
    assert "unknown tag" in _detail_text(response.json())
    assert stored_path.read_bytes() == before


def test_put_rejects_equipment_parent_cycle(client: TestClient, base_doc: dict[str, Any]) -> None:
    """Two unit entries that point at each other as parents are refused."""
    doc = copy.deepcopy(base_doc)
    doc["equipment"].append({"id": "LOOP_A", "level": "unit", "parent": "LOOP_B"})
    doc["equipment"].append({"id": "LOOP_B", "level": "unit", "parent": "LOOP_A"})

    response = client.put("/site", json=doc)

    assert response.status_code == 422
    assert "cycle" in _detail_text(response.json())


def test_put_rejects_unconvertible_lab_unit(client: TestClient, base_doc: dict[str, Any]) -> None:
    """Without unit conversions a lab in another unit than its tag is refused."""
    doc = copy.deepcopy(base_doc)
    doc["units"].pop("conversions", None)
    doc["labs"][0]["unit"] = "mm"

    response = client.put("/site", json=doc)

    assert response.status_code == 422
    assert "cannot be converted" in _detail_text(response.json())


def test_import_settings_available_after_example_put(
    client: TestClient, base_doc: dict[str, Any]
) -> None:
    """GET /site/import-settings answers with the defaults after a valid PUT."""
    assert client.put("/site", json=base_doc).status_code == 200

    response = client.get("/site/import-settings")

    assert response.status_code == 200
    assert isinstance(response.json(), dict)
