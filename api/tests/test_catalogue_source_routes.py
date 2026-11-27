"""Tests for the catalogue-from-source routes: rule tester, preview, import and its audit line.

Runs against a CSV source with synthetic tag columns in a temp data root. Covers the happy
path (preview, import into site.json, idempotent re-import), rule and source errors, and the
auth gate (viewer refused, engineer allowed) with the same enforcer stack as the trend tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, FakeClock, csrf, login, seed_users
from crosscut_api import catalogue_source_routes as routes
from crosscut_api.app import create_app
from crosscut_api.auth.deps import AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.catalogue_source_routes import build_catalogue_source_router
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

HEADER = "timestamp,FIC-101.PV,FIC-101.SP,FIC-101.OP,200-PP-101-CURRENT"


def _seed(root: Path) -> Path:
    """Write the CSV source and the site file that points at it; return the CSV folder."""
    csvdir = root / "csvsrc"
    csvdir.mkdir()
    (csvdir / "plant.csv").write_text(f"{HEADER}\n2026-01-01T00:00:00Z,1,2,3,4\n", encoding="utf-8")
    site_dir = root / "_site"
    site_dir.mkdir()
    site = {
        "schema_version": 1,
        "site": {"name": "Demo"},
        "tags": [],
        "sources": [{"id": "s1", "driver": "csv", "endpoint": str(csvdir)}],
    }
    (site_dir / "site.json").write_text(json.dumps(site), encoding="utf-8")
    return csvdir


def _rules() -> list[dict[str, Any]]:
    """The two presets the engineer typically accepts, concatenated in order."""
    presets = TestClient(create_app(Path.cwd(), auth_enabled=False)).get(
        "/catalogue/naming/presets"
    ).json()["presets"]
    return presets["isa_suffix"] + presets["area_equipment_signal"]


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Open app (auth off) over a seeded data root."""
    _seed(tmp_path)
    return TestClient(create_app(tmp_path, auth_enabled=False))


def _preview(client: TestClient, rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Preview the source with the given rules and return the JSON body."""
    response = client.post("/sources/s1/catalogue-preview", json={"rules": rules})
    assert response.status_code == 200, response.text
    return response.json()


def _import_body(preview: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Import body from a preview: every non-timestamp item, plus the rules."""
    items = [item for item in preview["items"] if item["name"] != "timestamp"]
    return {"tags": items, "rules": rules}


def _site_json(root: Path) -> dict[str, Any]:
    """The site draft, where imports land (#247); the published file stays as seeded."""
    return json.loads((root / "_site" / "draft.json").read_text(encoding="utf-8"))


def test_presets_endpoint_lists_the_builtin_rule_sets(client: TestClient) -> None:
    """The presets route names the isa_suffix and area_equipment_signal sets."""
    presets = client.get("/catalogue/naming/presets").json()["presets"]
    assert {"isa_suffix", "area_equipment_signal"} <= set(presets)


def test_preview_returns_items_and_naming(client: TestClient) -> None:
    """Preview walks the CSV columns and applies the rules to their names."""
    body = _preview(client, _rules())
    names = {item["name"]: item["address"] for item in body["items"]}
    assert names["FIC-101.PV"] == "plant.csv/FIC-101.PV"
    assert body["naming"]["loops"]["FIC-101"]["out"] == "FIC-101.OP"


def test_import_adds_tags_loop_and_equipment(tmp_path: Path) -> None:
    """Importing the accepted preview writes the loop, the area and the equipment tree."""
    _seed(tmp_path)
    client = TestClient(create_app(tmp_path, auth_enabled=False))
    rules = _rules()
    body = _import_body(_preview(client, rules), rules)
    response = client.post("/sources/s1/catalogue-import", json=body)
    assert response.status_code == 200, response.text
    # site, area 200, equipment PP-101, and FIC-101 as a one-loop equipment (#214).
    assert response.json()["added"] == {"tags": 4, "loops": 1, "equipment": 4}
    site = _site_json(tmp_path)
    assert site["loops"] == [
        {"id": "FIC-101", "pv": "FIC-101.PV", "sp": "FIC-101.SP", "out": "FIC-101.OP"}
    ]
    equipment = {e["id"]: e for e in site["equipment"]}
    assert equipment["200"]["parent"] == "site"
    assert equipment["PP-101"]["parent"] == "200"
    assert "200-PP-101-CURRENT" in equipment["PP-101"]["tags"]
    assert equipment["PP-101"]["signals"] == [
        {"tag": "200-PP-101-CURRENT", "kind": "current", "confirmed": False}
    ]
    assert equipment["PP-101"]["running"]["tag"] == "200-PP-101-CURRENT"
    assert equipment["FIC-101"]["loops"] == ["FIC-101"]


def test_reimport_of_the_same_preview_adds_nothing(tmp_path: Path) -> None:
    """A second identical import keeps existing ids and adds zero entries."""
    _seed(tmp_path)
    client = TestClient(create_app(tmp_path, auth_enabled=False))
    rules = _rules()
    body = _import_body(_preview(client, rules), rules)
    client.post("/sources/s1/catalogue-import", json=body)
    response = client.post("/sources/s1/catalogue-import", json=body)
    assert response.json()["added"] == {"tags": 0, "loops": 0, "equipment": 0}


def test_import_writes_the_naming_rules(tmp_path: Path) -> None:
    """The accepted rules are stored under naming.rules in site.json."""
    _seed(tmp_path)
    client = TestClient(create_app(tmp_path, auth_enabled=False))
    rules = _rules()
    client.post("/sources/s1/catalogue-import", json=_import_body(_preview(client, rules), rules))
    assert _site_json(tmp_path)["naming"]["rules"] == rules


def test_import_appends_catalogue_import_to_the_audit_file(tmp_path: Path) -> None:
    """Each import leaves a catalogue_import line in the auth audit log."""
    _seed(tmp_path)
    client = TestClient(create_app(tmp_path, auth_enabled=False))
    rules = _rules()
    client.post("/sources/s1/catalogue-import", json=_import_body(_preview(client, rules), rules))
    audit = (tmp_path / "_auth" / "auth-audit.jsonl").read_text(encoding="utf-8")
    assert "catalogue_import" in audit


def test_naming_test_reports_loops_and_unmatched(client: TestClient) -> None:
    """The rule tester classifies the given names and lists the ones no rule accepts."""
    response = client.post(
        "/catalogue/naming/test", json={"rules": _rules(), "tags": ["FIC-101.PV", "junk"]}
    )
    body = response.json()
    assert body["loops"] == {"FIC-101": {"pv": "FIC-101.PV"}}
    assert body["unmatched"] == ["junk"]


def test_invalid_rule_is_422(client: TestClient) -> None:
    """A rule with a broken regex is refused with 422 on the tester."""
    response = client.post("/catalogue/naming/test", json={"rules": [{"pattern": "("}], "tags": []})
    assert response.status_code == 422


def test_unknown_source_is_404(client: TestClient) -> None:
    """Preview and import of a source id that is not in the site are 404."""
    assert client.post("/sources/nope/catalogue-preview", json={"rules": []}).status_code == 404
    assert client.post(
        "/sources/nope/catalogue-import", json={"tags": [{"name": "x"}]}
    ).status_code == 404


class _NoBrowse:
    """A connector stand-in that offers no browse capability."""

    def capabilities(self) -> list[str]:
        """No capabilities at all."""
        return []


def test_preview_on_a_source_without_browse_is_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A connector without browse cannot be previewed: 400."""
    monkeypatch.setattr(routes, "connector_from_source", lambda source: _NoBrowse())
    response = client.post("/sources/s1/catalogue-preview", json={"rules": []})
    assert response.status_code == 400


def test_existing_site_level_entry_is_reused_as_root(tmp_path: Path) -> None:
    """An existing site-level equipment entry becomes the parent of the new areas."""
    _seed(tmp_path)
    path = tmp_path / "_site" / "site.json"
    site = json.loads(path.read_text(encoding="utf-8"))
    site["equipment"] = [{"id": "plant", "level": "site"}]
    path.write_text(json.dumps(site), encoding="utf-8")
    client = TestClient(create_app(tmp_path, auth_enabled=False))
    rules = _rules()
    client.post("/sources/s1/catalogue-import", json=_import_body(_preview(client, rules), rules))
    equipment = {e["id"]: e for e in _site_json(tmp_path)["equipment"]}
    assert equipment["200"]["parent"] == "plant"
    assert "site" not in equipment


@pytest.fixture
def auth_world(tmp_path: Path) -> tuple[FastAPI, Path]:
    """Enforcer, auth router and catalogue router over a seeded root with auth on."""
    _seed(tmp_path)
    seed_users(tmp_path, DEFAULT_USERS)
    clock = FakeClock()
    ctx = build_auth_context(tmp_path, TEST_CONFIG, clock)
    app = FastAPI(dependencies=[Depends(make_enforcer(AuthGuards(ctx), ctx))])
    app.include_router(build_auth_router_for(ctx))
    app.include_router(build_catalogue_source_router(tmp_path, clock))
    return app, tmp_path


def _import_as(app: FastAPI, username: str) -> int:
    """Log in as the user and post an import; return the status code."""
    client = TestClient(app)
    headers = csrf(login(client, username))
    body = {"tags": [{"name": "FIC-101.PV", "address": "plant.csv/FIC-101.PV"}], "rules": []}
    return client.post("/sources/s1/catalogue-import", json=body, headers=headers).status_code


def test_viewer_cannot_import_the_catalogue(auth_world: tuple[FastAPI, Path]) -> None:
    """A viewer lacks config.edit and gets 403."""
    app, _ = auth_world
    assert _import_as(app, "view1") == 403


def test_engineer_can_import_the_catalogue(auth_world: tuple[FastAPI, Path]) -> None:
    """An engineer holds config.edit and gets 200."""
    app, _ = auth_world
    assert _import_as(app, "eng1") == 200


def _node(identifier: str, name: str) -> Any:
    """A browsed variable node with a string id."""
    from crosscut_connectors.base import NodeInfo

    return NodeInfo(id=identifier, name=name, node_type="variable", has_children=False)


def test_repeated_browse_names_take_their_parent_as_prefix() -> None:
    """Pv under two loops becomes LIC301.Pv and FIC203.Pv; a unique name stays as it is."""
    nodes = [
        _node("ns=2;s=Application/Loop/LIC301/Pv", "Pv"),
        _node("ns=2;s=Application/Loop/FIC203/Pv", "Pv"),
        _node("ns=2;s=Application/System/TimeS", "TimeS"),
    ]
    names = routes.unique_names(nodes)
    assert names["ns=2;s=Application/Loop/LIC301/Pv"] == "LIC301.Pv"
    assert names["ns=2;s=Application/Loop/FIC203/Pv"] == "FIC203.Pv"
    assert names["ns=2;s=Application/System/TimeS"] == "TimeS"


def test_repeated_names_without_a_path_keep_their_browse_name() -> None:
    """Numeric node ids carry no path, so a repeated name cannot be told apart and stays."""
    nodes = [_node("i=1", "Status"), _node("i=2", "Status")]
    assert set(routes.unique_names(nodes).values()) == {"Status"}
