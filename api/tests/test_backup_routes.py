"""Backup and restore routes (#167): admin only, step-up, audit lines, dry run and round trip."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, FakeClock, csrf, login, seed_users, stepup
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.deps import AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.backup_routes import build_backup_router
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

Headers = dict[str, str]
ZIP = {"content-type": "application/zip"}


@pytest.fixture
def world(tmp_path: Path) -> tuple[FastAPI, Path]:
    """An app with the enforcer, the auth router and the backup router over a seeded root."""
    seed_users(tmp_path, DEFAULT_USERS)
    (tmp_path / "_fuzzy").mkdir()
    (tmp_path / "_fuzzy" / "f1.json").write_text('{"id": "original"}', encoding="utf-8")
    clock = FakeClock()
    ctx = build_auth_context(tmp_path, TEST_CONFIG, clock)
    app = FastAPI(dependencies=[Depends(make_enforcer(AuthGuards(ctx), ctx))])
    app.include_router(build_auth_router_for(ctx))
    app.include_router(build_backup_router(tmp_path, clock=clock))
    return app, tmp_path


def as_user(app: FastAPI, name: str, *, step_up: bool = True) -> tuple[TestClient, Headers]:
    """A logged-in client (optionally with a fresh step-up) and its CSRF header."""
    client = TestClient(app)
    payload = login(client, name)
    if step_up:
        stepup(client, payload)
    return client, csrf(payload)


def _audit_events(root: Path) -> list[str]:
    """Event names of the auth audit, after checking the hash chain is intact."""
    audit = AuthAudit(root / "_auth" / "auth-audit.jsonl")
    assert audit.verify()
    return [record["event"] for record in audit.records()]


def _download(client: TestClient) -> bytes:
    """A backup zip fetched through the API."""
    response = client.get("/admin/backup")
    assert response.status_code == 200, response.text
    return response.content


def test_download_is_a_zip_without_secrets_and_is_audited(world: tuple[FastAPI, Path]) -> None:
    """The admin gets a zip with a manifest; the audit has a backup_created line."""
    app, root = world
    client, _ = as_user(app, "admin1")
    response = client.get("/admin/backup")
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert "manifest.json" in names
    assert "_fuzzy/f1.json" in names
    assert "_auth/users.json" in names
    assert not any(n.startswith(("_secrets", "_backup")) for n in names)
    assert "backup_created" in _audit_events(root)


@pytest.mark.parametrize("user", ["op1", "eng1", "view1"])
def test_only_admins_may_use_the_routes(world: tuple[FastAPI, Path], user: str) -> None:
    """Operators, engineers and viewers get 403 on all three routes."""
    app, _ = world
    client, headers = as_user(app, user)
    assert client.get("/admin/backup").status_code == 403
    assert client.post("/admin/backup/inspect", content=b"x", headers=headers).status_code == 403
    restore = client.post("/admin/backup/restore?confirm=x", content=b"x", headers=headers)
    assert restore.status_code == 403


def test_download_and_restore_need_a_fresh_step_up(world: tuple[FastAPI, Path]) -> None:
    """Without a step-up the download and restore answer 428."""
    app, _ = world
    client, headers = as_user(app, "admin1", step_up=False)
    assert client.get("/admin/backup").status_code == 428
    response = client.post("/admin/backup/restore?confirm=x", content=b"x", headers=headers)
    assert response.status_code == 428


def test_restore_round_trip_with_dry_run_and_audit(world: tuple[FastAPI, Path]) -> None:
    """Back up, change, dry run shows the change, restore brings the original back."""
    app, root = world
    client, headers = as_user(app, "admin1")
    data = _download(client)
    (root / "_fuzzy" / "f1.json").write_text('{"id": "changed"}', encoding="utf-8")
    report = client.post("/admin/backup/inspect", content=data, headers={**headers, **ZIP}).json()
    assert report["ok"]
    actions = {c["path"]: c["action"] for c in report["changes"]}
    assert actions["_fuzzy/f1.json"] == "replace"
    assert json.loads((root / "_fuzzy" / "f1.json").read_text()) == {"id": "changed"}
    url = f"/admin/backup/restore?confirm={report['archive_sha256']}"
    response = client.post(url, content=data, headers={**headers, **ZIP})
    assert response.status_code == 200, response.text
    assert json.loads((root / "_fuzzy" / "f1.json").read_text()) == {"id": "original"}
    events = _audit_events(root)
    assert events.index("backup_created") < events.index("backup_restored")


def test_restore_needs_the_confirmation_of_the_inspected_archive(
    world: tuple[FastAPI, Path],
) -> None:
    """A confirm hash that is not the uploaded archive is refused with 409."""
    app, root = world
    client, headers = as_user(app, "admin1")
    data = _download(client)
    response = client.post("/admin/backup/restore?confirm=deadbeef", content=data, headers=headers)
    assert response.status_code == 409
    assert "backup_restored" not in _audit_events(root)


def test_tampered_archive_is_reported_and_restore_is_422(world: tuple[FastAPI, Path]) -> None:
    """A flipped byte shows in the dry run and the restore is refused; no restore audit line."""
    app, root = world
    client, headers = as_user(app, "admin1")
    source = zipfile.ZipFile(io.BytesIO(_download(client)))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for name in source.namelist():
            body = b'{"id": "evil"}' if name == "_fuzzy/f1.json" else source.read(name)
            target.writestr(name, body)
    bad = out.getvalue()
    report = client.post("/admin/backup/inspect", content=bad, headers=headers).json()
    assert not report["ok"]
    assert any("hash" in problem for problem in report["problems"])
    url = f"/admin/backup/restore?confirm={report['archive_sha256']}"
    assert client.post(url, content=bad, headers=headers).status_code == 422
    assert "backup_restored" not in _audit_events(root)
    assert json.loads((root / "_fuzzy" / "f1.json").read_text()) == {"id": "original"}


def test_newer_backup_is_refused_by_inspect(world: tuple[FastAPI, Path]) -> None:
    """A manifest with a newer format version fails the dry run."""
    app, _ = world
    client, headers = as_user(app, "admin1")
    source = zipfile.ZipFile(io.BytesIO(_download(client)))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for name in source.namelist():
            body = source.read(name)
            if name == "manifest.json":
                body = json.dumps({**json.loads(body), "format_version": 99}).encode()
            target.writestr(name, body)
    report = client.post("/admin/backup/inspect", content=out.getvalue(), headers=headers).json()
    assert not report["ok"]
    assert "newer" in report["problems"][0]
