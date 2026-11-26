"""Tests of the loop template routes: list, read, save and site overrides.

A site copy lives under ``<data root>/_loop_templates`` and shadows the packaged template of
the same key; invalid documents are refused with 422 and never written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.loop_template_routes import build_loop_template_router
from crosscut_loops.loop_templates import load_loop_templates
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """A client on an app with only the loop template router and ``tmp_path`` as root."""
    app = FastAPI()
    app.include_router(build_loop_template_router(tmp_path))
    return TestClient(app)


@pytest.fixture
def flow_template() -> dict[str, Any]:
    """A fresh copy of the packaged flow template."""
    return json.loads(json.dumps(load_loop_templates()["flow"]))


def test_list_returns_every_builtin_template(client: TestClient) -> None:
    response = client.get("/loop-templates")
    assert response.status_code == 200
    templates = response.json()["templates"]
    assert {one["key"] for one in templates} == set(load_loop_templates())
    assert {one["origin"] for one in templates} == {"builtin"}


def test_get_returns_one_builtin_template(client: TestClient) -> None:
    response = client.get("/loop-templates/level_averaging")
    assert response.status_code == 200
    assert response.json()["key"] == "level_averaging"
    assert response.json()["origin"] == "builtin"


def test_get_unknown_template_is_404(client: TestClient) -> None:
    response = client.get("/loop-templates/no_such_loop")
    assert response.status_code == 404


def test_put_saves_a_site_copy_and_list_marks_it(
    client: TestClient, tmp_path: Path, flow_template: dict[str, Any]
) -> None:
    flow_template["tests"]["default_step_pct"] = 2.5
    response = client.put("/loop-templates/flow", json=flow_template)
    assert response.status_code == 200
    assert response.json()["origin"] == "site"

    stored = tmp_path / "_loop_templates" / "flow.json"
    assert json.loads(stored.read_text(encoding="utf-8"))["tests"]["default_step_pct"] == 2.5
    listed = {one["key"]: one for one in client.get("/loop-templates").json()["templates"]}
    assert listed["flow"]["origin"] == "site"
    assert listed["flow"]["tests"]["default_step_pct"] == 2.5


def test_put_rejects_an_invalid_template_without_writing(
    client: TestClient, tmp_path: Path, flow_template: dict[str, Any]
) -> None:
    flow_template["tuning"]["rule"] = "ziegler"
    response = client.put("/loop-templates/flow", json=flow_template)
    assert response.status_code == 422
    assert any("tuning" in problem for problem in response.json()["detail"])
    assert not (tmp_path / "_loop_templates" / "flow.json").exists()


def test_put_rejects_a_body_key_that_differs_from_the_route(
    client: TestClient, flow_template: dict[str, Any]
) -> None:
    flow_template["key"] = "temperature"
    response = client.put("/loop-templates/flow", json=flow_template)
    assert response.status_code == 422
    assert "does not match" in response.json()["detail"][0]


def test_custom_file_whose_name_differs_from_its_key_is_refused(
    client: TestClient, tmp_path: Path, flow_template: dict[str, Any]
) -> None:
    folder = tmp_path / "_loop_templates"
    folder.mkdir()
    (folder / "temperature.json").write_text(json.dumps(flow_template), encoding="utf-8")
    response = client.get("/loop-templates")
    assert response.status_code == 422
    assert "file name" in response.json()["detail"][0]


def test_a_site_copy_shadows_the_builtin_of_the_same_key(
    client: TestClient, tmp_path: Path, flow_template: dict[str, Any]
) -> None:
    flow_template["label"] = "Site flow"
    folder = tmp_path / "_loop_templates"
    folder.mkdir()
    (folder / "flow.json").write_text(json.dumps(flow_template), encoding="utf-8")
    response = client.get("/loop-templates/flow")
    assert response.json()["label"] == "Site flow"
    assert response.json()["origin"] == "site"
