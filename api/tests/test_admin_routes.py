"""Admin routes (issue #170): permissions, health payload, log export and its audit entry."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, login, seed_users, stepup
from crosscut_api.app import create_app
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import auth_dir
from fastapi.testclient import TestClient

RANGE = {"start": "2026-11-26T10:00:00Z", "end": "2026-11-26T11:00:00Z"}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    seed_users(tmp_path, DEFAULT_USERS)
    logs = tmp_path / "_logs"
    logs.mkdir()
    (logs / "api.log").write_text(
        "2026-11-26T10:30:00Z INFO x token=sekret123 done\n", encoding="utf-8")
    return tmp_path


def _client(root: Path, user: str, step_up: bool = True) -> TestClient:
    client = TestClient(create_app(root, auth_config=TEST_CONFIG))
    payload = login(client, user)
    if step_up:
        stepup(client, payload)
    return client


def _export_records(root: Path) -> list[dict[str, str]]:
    records = AuthAudit(auth_dir(root) / AUDIT_FILE, lambda: 0.0).records()
    return [r for r in records if r["event"] == "log_export"]


def test_health_is_readable_by_a_viewer(root: Path) -> None:
    body = _client(root, "view1").get("/admin/health").json()
    assert body["status"] in {"ok", "warning", "error"}
    ids = {item["id"] for item in body["items"]}
    assert {"runtime", "gateway", "audit", "disk", "versions"} <= ids
    assert all(item["status"] in {"ok", "warning", "error"} for item in body["items"])


def test_health_needs_a_session(root: Path) -> None:
    client = TestClient(create_app(root, auth_config=TEST_CONFIG))
    assert client.get("/admin/health").status_code == 401


@pytest.mark.parametrize("user", ["view1", "op1", "eng1"])
def test_log_export_is_forbidden_without_users_manage(root: Path, user: str) -> None:
    assert _client(root, user).get("/admin/logs/export", params=RANGE).status_code == 403
    assert _export_records(root) == []


def test_admin_exports_scrubbed_logs_and_the_export_is_audited(root: Path) -> None:
    response = _client(root, "admin1").get("/admin/logs/export", params=RANGE)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        text = archive.read("_logs/api.log").decode()
    assert "sekret123" not in text and "done" in text
    records = _export_records(root)
    assert len(records) == 1
    assert records[0]["actor"] == "admin1" and records[0]["files"] == "_logs/api.log"
    assert AuthAudit(auth_dir(root) / AUDIT_FILE, lambda: 0.0).verify()


def test_bad_range_is_422_and_leaves_no_audit_entry(root: Path) -> None:
    client = _client(root, "admin1")
    reversed_range: dict[str, Any] = {"start": RANGE["end"], "end": RANGE["start"]}
    assert client.get("/admin/logs/export", params=reversed_range).status_code == 422
    assert client.get("/admin/logs/export", params={"start": "nope"}).status_code == 422
    assert _export_records(root) == []


def test_default_range_is_the_last_day(root: Path) -> None:
    assert _client(root, "admin1").get("/admin/logs/export").status_code == 200


def test_export_without_step_up_is_428_and_not_audited(root: Path) -> None:
    client = _client(root, "admin1", step_up=False)
    response = client.get("/admin/logs/export", params=RANGE)
    assert response.status_code == 428
    assert _export_records(root) == []


def test_range_over_the_cap_is_422(root: Path) -> None:
    params = {"start": "2026-01-01T00:00:00Z", "end": "2026-11-01T00:00:00Z"}
    assert _client(root, "admin1").get("/admin/logs/export", params=params).status_code == 422
