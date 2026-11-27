"""Dependency tracking over the API (#166): stale list, needs-relearn gate, audited re-confirm."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.auth.actor import ActorContext
from crosscut_api.dependency_hooks import register_dependent, stale_problem
from crosscut_api.dependency_routes import build_dependency_router
from crosscut_api.runtime_routes import build_runtime_router
from crosscut_api.site_versions import publish_document
from crosscut_connectors.dependency_index import load_index
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/generic_concentrator/_site/site.json"
TAGS = ["CR1.CSS.PV", "CR1.CSS.SP"]


def _app(root: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(build_dependency_router(root))
    app.include_router(build_runtime_router(root))

    @app.middleware("http")
    async def stamp(request: Request, call_next: Any) -> Any:
        request.state.actor = ActorContext("eng1", ("engineer",), "s", "127.0.0.1", False, None)
        return await call_next(request)

    return app


@pytest.fixture
def base() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return document


@pytest.fixture
def root(tmp_path: Path, base: dict[str, Any]) -> Path:
    publish_document(tmp_path, base, "eng1", "base")
    (tmp_path / "_anomaly").mkdir()
    (tmp_path / "_anomaly" / "m1.json").write_text(json.dumps({"tags": TAGS}), encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(root: Path) -> TestClient:
    return TestClient(_app(root))


def _publish_unit_change(root: Path, base: dict[str, Any]) -> None:
    doc = copy.deepcopy(base)
    next(t for t in doc["tags"] if t["id"] == "CR1.CSS.PV")["address"] = "ns=2;s=MOVED"
    publish_document(root, doc, "eng1", "unit")


def _anomaly_job() -> dict[str, Any]:
    return {"id": "scan", "kind": "anomaly_scan", "source": "sim", "tags": TAGS, "period_s": 1,
            "window_s": 60, "enabled": True, "anomaly_id": "m1"}


def test_nothing_is_stale_after_a_fit_and_an_unrelated_publish(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    register_dependent(root, "anomaly", "m1")
    doc = copy.deepcopy(base)
    doc["site"]["name"] = "Renamed"
    publish_document(root, doc, "eng1", "rename")
    body = client.get("/dependencies").json()
    assert body["items"] == [] and body["tracked"] >= 1 and body["published_version"] == 2


def test_publish_marks_model_needs_relearn_with_reason(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    register_dependent(root, "anomaly", "m1")
    _publish_unit_change(root, base)
    items = {i["key"]: i for i in client.get("/dependencies").json()["items"]}
    model = items["anomaly:m1"]
    assert model["needs_relearn"] and model["built_on_version"] == 1
    assert model["stale_since_version"] == 2 and model["actions"] == ["relearn", "reconfirm"]
    assert model["reasons"][0]["tag"] == "CR1.CSS.PV"
    assert model["reasons"][0]["kind"] == "remapped"


def test_stale_model_cannot_be_deployed_until_relearned(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    register_dependent(root, "anomaly", "m1")
    _publish_unit_change(root, base)
    refused = client.post("/runtime/jobs", json=_anomaly_job())
    assert refused.status_code == 422 and "needs relearn" in json.dumps(refused.json())
    register_dependent(root, "anomaly", "m1")  # what a fit does
    assert stale_problem(root, "anomaly:m1") is None
    assert client.post("/runtime/jobs", json=_anomaly_job()).status_code == 200


def test_reconfirm_needs_a_note_is_audited_and_clears(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    register_dependent(root, "anomaly", "m1")
    _publish_unit_change(root, base)
    assert client.post("/dependencies/confirm", json={"key": "anomaly:m1"}).status_code == 422
    unknown = client.post("/dependencies/confirm", json={"key": "nope:x", "note": "n"})
    assert unknown.status_code == 404
    done = client.post("/dependencies/confirm", json={"key": "anomaly:m1", "note": "checked"})
    assert done.status_code == 200 and done.json()["confirmed"]["by"] == "eng1"
    assert client.get("/dependencies").json()["items"] == []
    audit = (root / "_site" / "versions" / "audit.jsonl").read_text(encoding="utf-8")
    assert "dependency_confirm" in audit and "anomaly:m1" in audit
    assert load_index(root)["items"]["anomaly:m1"]["confirmed"]["note"] == "checked"
    assert client.post("/runtime/jobs", json=_anomaly_job()).status_code == 200


def test_deployed_job_is_listed_with_edit_config_action(
    client: TestClient, root: Path, base: dict[str, Any]
) -> None:
    job = {"id": "kpi", "kind": "loop_kpi", "source": "sim", "loops": ["CR1.CSS"], "period_s": 1,
           "window_s": 60, "enabled": False}
    assert client.post("/runtime/jobs", json=job).status_code == 200
    _publish_unit_change(root, base)
    items = {i["key"]: i for i in client.get("/dependencies").json()["items"]}
    assert items["job:kpi"]["actions"] == ["edit_config", "reconfirm"]
    refused = client.post("/runtime/jobs/kpi/start")
    assert refused.status_code == 422 and "remapped" in json.dumps(refused.json())
    client.post("/dependencies/confirm", json={"key": "job:kpi", "note": "unit ok"})
    assert client.post("/runtime/jobs/kpi/start").status_code == 200


def test_corrupt_index_blocks_deploy_and_listing(client: TestClient, root: Path) -> None:
    register_dependent(root, "anomaly", "m1")
    (root / "_site" / "dependencies.json").write_text("{broken", encoding="utf-8")
    assert "dependency_index_unreadable" in (stale_problem(root, "anomaly:m1") or "")
    refused = client.post("/runtime/jobs", json=_anomaly_job())
    assert refused.status_code == 422
    assert "dependency_index_unreadable" in json.dumps(refused.json())
    listing = client.get("/dependencies")
    assert listing.status_code == 409 and "dependency_index_unreadable" in listing.json()["detail"]


def test_unreadable_catalogue_is_a_problem_not_a_pass(root: Path) -> None:
    (root / "_site" / "site.json").write_text("{broken", encoding="utf-8")
    assert stale_problem(root, "anomaly:m1") == "catalogue_unreadable"


def test_no_catalogue_at_all_is_not_a_problem(tmp_path: Path) -> None:
    assert stale_problem(tmp_path, "anomaly:m1") is None


def test_register_retries_a_busy_index(
    root: Path, base: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import crosscut_api.dependency_hooks as hooks
    from crosscut_connectors.dependency_index import DependencyError

    register_dependent(root, "anomaly", "m1")
    _publish_unit_change_address(root, base)
    assert stale_problem(root, "anomaly:m1")
    real, calls = hooks.register, []

    def flaky(*args: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise DependencyError("busy")
        return real(*args)

    monkeypatch.setattr(hooks, "register", flaky)
    monkeypatch.setattr(hooks, "REGISTER_WAIT_S", 0.0)
    register_dependent(root, "anomaly", "m1")
    assert len(calls) == 2 and stale_problem(root, "anomaly:m1") is None


def _publish_unit_change_address(root: Path, base: dict[str, Any]) -> None:
    _publish_unit_change(root, base)
