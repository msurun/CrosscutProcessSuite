"""Tests for the runtime HTTP endpoints (Phase 1, #44).

The API is a thin layer over the runtime state files under ``<root>/_runtime/``:
status merges state.json with the site catalogue, and the job routes edit jobs.json.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.runtime_routes import build_runtime_router
from crosscut_connectors.site import save_site
from crosscut_runtime.store import RuntimeStore
from fastapi import FastAPI
from fastapi.testclient import TestClient

SITE_DOCUMENT: dict[str, Any] = {
    "schema_version": 1,
    "site": {"name": "t"},
    "tags": [{"id": "t.pv"}, {"id": "t.sp"}, {"id": "t.out"}, {"id": "t.mode"}],
    "loops": [{"id": "L1", "pv": "t.pv", "sp": "t.sp", "out": "t.out", "mode": "t.mode"}],
    "sources": [{"id": "s1", "driver": "opcua", "endpoint": "opc.tcp://127.0.0.1:4840"}],
}

VALID_JOB: dict[str, Any] = {
    "id": "j1",
    "kind": "loop_kpi",
    "source": "s1",
    "loops": ["L1"],
    "period_s": 5,
    "window_s": 300,
    "enabled": True,
}

STALE_AFTER_S = 30


def _client_with_site(root: Path) -> TestClient:
    """An app exposing only the runtime router over a freshly saved site."""
    save_site(root, SITE_DOCUMENT)
    app = FastAPI()
    app.include_router(build_runtime_router(root))
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """A client over a site with one source ``s1`` and one loop ``L1``."""
    return _client_with_site(tmp_path)


def _save_running_state(root: Path, updated_at_utc: str) -> None:
    """Mark the service running and report one finished run of job ``j1``."""
    state = {
        "service": "running",
        "updated_at_utc": updated_at_utc,
        "jobs": {
            "j1": {
                "status": "ok",
                "last_run_utc": None,
                "error": None,
                "samples": 10,
                "kpi": None,
            },
        },
    }
    RuntimeStore(root).save_state(state)


def test_status_without_runtime(client: TestClient) -> None:
    response = client.get("/runtime/status")

    assert response.status_code == 200
    body = response.json()
    assert body["service"]["running"] is False
    assert body["service"]["updated_at_utc"] is None
    assert body["jobs"] == []


def test_status_merges_fresh_state(tmp_path: Path) -> None:
    client = _client_with_site(tmp_path)
    client.post("/runtime/jobs", json=VALID_JOB)
    _save_running_state(tmp_path, datetime.now(UTC).isoformat())

    response = client.get("/runtime/status")

    assert response.status_code == 200
    body = response.json()
    assert body["service"]["running"] is True
    job_entry = next(job for job in body["jobs"] if job["id"] == "j1")
    assert job_entry["status"] == "ok"
    assert job_entry["samples"] == 10


def test_status_stale_state_is_not_running(tmp_path: Path) -> None:
    client = _client_with_site(tmp_path)
    client.post("/runtime/jobs", json=VALID_JOB)
    stale_moment = datetime.now(UTC) - timedelta(seconds=60)
    _save_running_state(tmp_path, stale_moment.isoformat())

    response = client.get("/runtime/status")

    assert response.status_code == 200
    assert response.json()["service"]["running"] is False


def test_create_job_writes_valid_file(tmp_path: Path) -> None:
    client = _client_with_site(tmp_path)

    response = client.post("/runtime/jobs", json=VALID_JOB)

    assert response.status_code == 200
    stored_jobs = RuntimeStore(tmp_path).load_jobs()
    assert any(job["id"] == "j1" for job in stored_jobs["jobs"])
    listed = client.get("/runtime/jobs").json()
    assert any(job["id"] == "j1" for job in listed["jobs"])


def test_create_job_rejects_unknown_source(client: TestClient) -> None:
    bad_job = {**VALID_JOB, "source": "nope"}

    response = client.post("/runtime/jobs", json=bad_job)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any("nope" in message for message in detail)


def test_create_job_rejects_loop_kpi_without_loops(client: TestClient) -> None:
    bad_job = {**VALID_JOB, "loops": []}

    response = client.post("/runtime/jobs", json=bad_job)

    assert response.status_code == 422


def test_create_job_rejects_unknown_loop(client: TestClient) -> None:
    bad_job = {**VALID_JOB, "loops": ["zz"]}

    response = client.post("/runtime/jobs", json=bad_job)

    assert response.status_code == 422


def test_create_duplicate_job_conflicts(client: TestClient) -> None:
    client.post("/runtime/jobs", json=VALID_JOB)

    response = client.post("/runtime/jobs", json=VALID_JOB)

    assert response.status_code == 409


def test_start_stop_toggle_enabled(client: TestClient) -> None:
    client.post("/runtime/jobs", json=VALID_JOB)

    stop_response = client.post("/runtime/jobs/j1/stop")
    start_response = client.post("/runtime/jobs/j1/start")

    assert stop_response.status_code == 200
    assert _job_enabled(stop_response.json()) is False
    assert start_response.status_code == 200
    assert _job_enabled(start_response.json()) is True


def _job_enabled(document: dict[str, Any]) -> bool:
    """The ``enabled`` flag of job ``j1`` in a jobs document."""
    return next(job for job in document["jobs"] if job["id"] == "j1")["enabled"]


def test_patch_updates_period_and_rejects_unknown_field(tmp_path: Path) -> None:
    client = _client_with_site(tmp_path)
    client.post("/runtime/jobs", json=VALID_JOB)

    patch_response = client.patch("/runtime/jobs/j1", json={"period_s": 10})
    bogus_response = client.patch("/runtime/jobs/j1", json={"bogus": 1})
    missing_response = client.patch("/runtime/jobs/nope", json={"period_s": 10})

    assert patch_response.status_code == 200
    stored_jobs = RuntimeStore(tmp_path).load_jobs()
    stored_job = next(job for job in stored_jobs["jobs"] if job["id"] == "j1")
    assert stored_job["period_s"] == 10
    assert bogus_response.status_code == 422
    assert missing_response.status_code == 404


def test_delete_job(tmp_path: Path) -> None:
    client = _client_with_site(tmp_path)
    client.post("/runtime/jobs", json=VALID_JOB)

    delete_response = client.delete("/runtime/jobs/j1")
    second_delete_response = client.delete("/runtime/jobs/j1")

    assert delete_response.status_code == 200
    stored_jobs = RuntimeStore(tmp_path).load_jobs()
    assert stored_jobs["jobs"] == []
    assert second_delete_response.status_code == 404


def test_log_returns_appended_lines(tmp_path: Path) -> None:
    client = _client_with_site(tmp_path)
    RuntimeStore(tmp_path).append_log("info", "hello runtime")

    response = client.get("/runtime/log")

    assert response.status_code == 200
    assert "hello runtime" in "\n".join(response.json()["lines"])


def test_variables_empty_without_runtime(client: TestClient) -> None:
    response = client.get("/runtime/variables")

    assert response.status_code == 200
    assert response.json() == {"controllers": {}}


def test_variables_returns_written_statuses(tmp_path: Path) -> None:
    from crosscut_runtime.store import write_variable_status
    from crosscut_runtime.variable_status import VariableStatus

    client = _client_with_site(tmp_path)
    status = VariableStatus("cv1", "t.pv", "bad", ("stale",), 1.5, None)
    write_variable_status(tmp_path, "c1", [status])

    body = client.get("/runtime/variables").json()

    assert body["controllers"]["c1"][0]["reasons"] == ["stale"]
