"""Backup and restore core (#167): content, exclusions, hashes, dry run, tampering, versions.

Runs on a temporary data root filled with one file of every kind that is in scope and one of every
kind that must stay out (Parquet history, runtime records, secrets).
"""

from __future__ import annotations

import io
import json
import os
import stat
import zipfile
from pathlib import Path

import crosscut_api.backup as backup
import pytest
from crosscut_api.backup import (
    BackupError,
    build_backup,
    inspect_backup,
    restore_backup,
    sha256_hex,
)

NOW = "2026-11-26T10:00:00Z"
PI_SOURCE = {
    "id": "pi1",
    "driver": "piwebapi",
    "auth": {"kind": "basic", "credential_ref": "source.pi1"},
}
SITE = {"schema_version": 1, "site": {"name": "A"}, "tags": [], "sources": [PI_SOURCE]}
INCLUDED = {
    "_site/site.json": SITE,
    "_anomaly/a1.json": {"schema_version": "1.0.0", "id": "a1"},
    "_anomaly/equipment/e1.model.json": {"model": 1},
    "_softsensor/s1.json": {"id": "s1"},
    "_fuzzy/f1.json": {"id": "f1"},
    "_supervisor/v1.json": {"id": "v1"},
    "_trends/charts/abcdefghijkl.json": {"schema_version": 1, "id": "abcdefghijkl"},
    "_gateway/policy/write-policy.json": {"mode": "advisory"},
    "_gateway/policy/policy.pin.json": {"signature": "x"},
    "_auth/users.json": {"version": 1, "users": []},
    "_auth/roles.json": {"version": 1, "roles": {}},
    "plant-map.json": {"targets": []},
}
EXCLUDED = (
    "ds1/dataset.json", "ds1/data.parquet", "_site/cache.parquet", "_anomaly/x.tmp",
    "_runtime/kpi/L1.jsonl", "_advisory/log.jsonl", "_uploads/up.csv", "_secrets/gateway-hmac.key",
    "_gateway/state.json", "_gateway/inbox/c1.json", "_tuning/proposals/p1.json",
)  # fmt: skip
EVIDENCE = {"_auth/auth-audit.jsonl": '{"seq":"0"}\n', "_gateway/audit.jsonl": '{"seq":"0"}\n'}
HISTORY = "SECRET-OR-HISTORY"


def _write(root: Path, rel: str, text: str) -> None:
    """Create a file with parents."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A data root with in-scope, evidence and excluded files."""
    for rel, doc in INCLUDED.items():
        _write(tmp_path, rel, json.dumps(doc))
    for rel, text in EVIDENCE.items():
        _write(tmp_path, rel, text)
    for rel in EXCLUDED:
        _write(tmp_path, rel, HISTORY)
    return tmp_path


def _manifest(data: bytes) -> dict[str, object]:
    """The parsed manifest of a backup."""
    manifest: dict[str, object] = json.loads(
        zipfile.ZipFile(io.BytesIO(data)).read("manifest.json")
    )
    return manifest


def _rebuild(
    data: bytes, edit: dict[str, bytes], manifest_edit: dict[str, object] | None = None
) -> bytes:
    """A copy of a backup with members replaced and top-level manifest fields changed."""
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for name in source.namelist():
            body = edit.get(name, source.read(name))
            if name == "manifest.json" and manifest_edit:
                body = json.dumps({**json.loads(body), **manifest_edit}).encode()
            target.writestr(name, body)
    return out.getvalue()


def test_backup_holds_scope_and_excludes_history_and_secrets(root: Path) -> None:
    """Every in-scope file is in, every history, runtime and secret file is out."""
    names = set(zipfile.ZipFile(io.BytesIO(build_backup(root, NOW))).namelist())
    assert names == {*INCLUDED, *EVIDENCE, "manifest.json"}
    assert not names & set(EXCLUDED)


def test_manifest_lists_hashes_version_exclusions_and_secrets_to_reenter(root: Path) -> None:
    """The manifest carries version, time, sha256 per file, the exclusions and the secrets list."""
    manifest = _manifest(build_backup(root, NOW))
    assert (manifest["format_version"], manifest["created_utc"]) == (1, NOW)
    by_path = {f["path"]: f for f in manifest["files"]}  # type: ignore[attr-defined]
    assert by_path["plant-map.json"]["sha256"] == sha256_hex((root / "plant-map.json").read_bytes())
    assert by_path["_auth/auth-audit.jsonl"]["kind"] == "evidence"
    assert by_path["_site/site.json"]["schema_version"] == 1
    assert any("Parquet" in line for line in manifest["excluded"])  # type: ignore[attr-defined]
    kinds = {(m["kind"], m.get("ref")) for m in manifest["must_reenter"]}  # type: ignore[attr-defined]
    assert ("source_secret", "source.pi1") in kinds
    assert ("gateway_key", None) in kinds
    assert HISTORY not in json.dumps(manifest)


def test_dry_run_reports_changes_and_touches_nothing(root: Path) -> None:
    """A dry run lists add/replace/remove/keep and leaves the root as it was."""
    data = build_backup(root, NOW)
    _write(root, "_fuzzy/f1.json", '{"id": "changed"}')
    _write(root, "_fuzzy/extra.json", "{}")
    (root / "_softsensor" / "s1.json").unlink()
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    report, _ = inspect_backup(root, data)
    assert report.ok, report.problems
    actions = {c["path"]: c["action"] for c in report.changes}
    assert actions["_fuzzy/f1.json"] == "replace"
    assert actions["_fuzzy/extra.json"] == "remove"
    assert actions["_softsensor/s1.json"] == "add"
    assert actions["plant-map.json"] == "unchanged"
    assert actions["_auth/auth-audit.jsonl"] == "keep_evidence"
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_restore_returns_the_configuration_and_keeps_audit_and_history(root: Path) -> None:
    """Restore puts changed files back, removes added ones, keeps the live audit and history."""
    data = build_backup(root, NOW)
    _write(root, "_fuzzy/f1.json", '{"id": "changed"}')
    _write(root, "_fuzzy/extra.json", "{}")
    _write(root, "_auth/auth-audit.jsonl", '{"seq":"0"}\n{"seq":"1"}\n')
    restore_backup(root, data, "2026-11-26T11:00:00Z")
    assert json.loads((root / "_fuzzy/f1.json").read_text()) == {"id": "f1"}
    assert not (root / "_fuzzy/extra.json").exists()
    assert (root / "_auth/auth-audit.jsonl").read_text().count("seq") == 2
    assert (root / "ds1/data.parquet").read_text() == HISTORY
    assert (root / "_secrets/gateway-hmac.key").exists()
    assert list((root / "_backup").glob("pre-restore-*.zip"))
    assert not list((root / "_backup").glob("staging-*"))


def test_tampered_content_is_refused_and_nothing_changes(root: Path) -> None:
    """A changed file body fails its hash; restore refuses and leaves the root alone."""
    data = _rebuild(build_backup(root, NOW), {"_fuzzy/f1.json": b'{"id": "evil"}'})
    report, _ = inspect_backup(root, data)
    assert not report.ok
    assert any("_fuzzy/f1.json" in p and "hash" in p for p in report.problems)
    with pytest.raises(BackupError):
        restore_backup(root, data, NOW)
    assert json.loads((root / "_fuzzy/f1.json").read_text()) == {"id": "f1"}
    assert not (root / "_backup").exists()


def test_extra_unlisted_member_is_refused(root: Path) -> None:
    """A member the manifest does not list (smuggled in) is a problem."""
    data = build_backup(root, NOW)
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as target:
            for name in source.namelist():
                target.writestr(name, source.read(name))
            target.writestr("_auth/users2.json", "{}")
    report, _ = inspect_backup(root, out.getvalue())
    assert any("not in the manifest" in p for p in report.problems)


def test_newer_backup_format_is_refused(root: Path) -> None:
    """A backup written by a newer format version is refused."""
    data = _rebuild(build_backup(root, NOW), {}, {"format_version": 2})
    report, _ = inspect_backup(root, data)
    assert not report.ok
    assert "newer" in report.problems[0]


def test_newer_schema_version_inside_is_refused(root: Path) -> None:
    """A file with a layout version above the supported one is refused even with a valid hash."""
    data = build_backup(root, NOW)
    manifest = _manifest(data)
    body = json.dumps({**SITE, "schema_version": 2}).encode()
    for item in manifest["files"]:  # type: ignore[attr-defined]
        if item["path"] == "_site/site.json":
            item.update(sha256=sha256_hex(body), size=len(body), schema_version=2)
    edited = _rebuild(
        data, {"_site/site.json": body, "manifest.json": json.dumps(manifest).encode()}
    )
    report, _ = inspect_backup(root, edited)
    assert any("schema version 2 is newer" in p for p in report.problems)


@pytest.mark.parametrize(
    "name", ["../evil.json", "/abs.json", "_site/../x.json", "C:/x.json", "_runtime/kpi/L1.jsonl"]
)
def test_unsafe_or_out_of_scope_path_is_refused(root: Path, name: str) -> None:
    """Parent, absolute, drive paths and files outside the scope never restore."""
    data = build_backup(root, NOW)
    manifest = _manifest(data)
    manifest["files"].append(
        {"path": name, "kind": "config", "size": 2, "sha256": sha256_hex(b"{}")}
    )  # type: ignore[attr-defined]
    out = _rebuild(data, {"manifest.json": json.dumps(manifest).encode()})
    with zipfile.ZipFile(io.BytesIO(out), "a") as archive:
        archive.writestr(zipfile.ZipInfo(name), b"{}")
    report, _ = inspect_backup(root, out)
    assert not report.ok


def test_not_a_zip_is_refused(root: Path) -> None:
    """Random bytes give a problem, not an exception."""
    report, _ = inspect_backup(root, b"not a zip")
    assert not report.ok


def test_failure_during_swap_rolls_back(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the swap breaks half way the safety copy is put back."""
    data = build_backup(root, NOW)
    _write(root, "_fuzzy/f1.json", '{"id": "changed"}')
    _write(root, "_softsensor/s1.json", '{"id": "changed"}')
    real = backup.os.replace
    calls: list[str] = []

    def flaky(src: str, dst: str) -> None:
        calls.append(str(dst))
        if len(calls) == 3:
            raise OSError("disk full")
        real(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(backup.os, "replace", flaky)
        with pytest.raises(OSError, match="disk full"):
            restore_backup(root, data, "2026-11-26T12:00:00Z")
    assert json.loads((root / "_fuzzy/f1.json").read_text()) == {"id": "changed"}
    assert json.loads((root / "_softsensor/s1.json").read_text()) == {"id": "changed"}


def _bomb(root: Path) -> bytes:
    """A backup with one 5 MiB all-zero member: tiny when compressed, a high ratio."""
    data = build_backup(root, NOW)
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for name in source.namelist():
            target.writestr(name, source.read(name))
        target.writestr("_fuzzy/big.json", b"0" * (5 * 1024 * 1024))
    return out.getvalue()


def test_high_ratio_member_is_refused_before_reading(root: Path) -> None:
    """A small deflate member that inflates 1000-fold is refused with a ratio reason."""
    data = _bomb(root)
    assert len(data) < 100_000
    report, contents = inspect_backup(root, data)
    assert not report.ok
    assert "compression ratio" in report.problems[0]
    assert contents == {}


def test_total_unpacked_size_cap(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The sum of the declared sizes is capped."""
    monkeypatch.setattr(backup, "MAX_UNPACKED_BYTES", 10)
    report, _ = inspect_backup(root, build_backup(root, NOW))
    assert not report.ok
    assert "unpacked size" in report.problems[0]


def test_path_guard_refuses_a_target_outside_the_base(tmp_path: Path) -> None:
    """The write and swap guard refuses a name that resolves outside its folder."""
    with pytest.raises(BackupError, match="leaves the target folder"):
        backup._write_all(tmp_path / "stage", {"../escape.json": b"{}"})
    assert not (tmp_path / "escape.json").exists()
    with pytest.raises(BackupError):
        backup._inside(tmp_path, "_site/../../x")


def _fail_first_swap(monkeypatch: pytest.MonkeyPatch) -> None:
    """First swap fails, later swaps do nothing (a rollback that applies nothing)."""
    calls: list[int] = []

    def swap(root: Path, *_args: object) -> None:
        calls.append(1)
        if len(calls) == 1:
            (root / "_fuzzy" / "f1.json").write_text("half restored", encoding="utf-8")
            raise OSError("disk full")

    monkeypatch.setattr(backup, "_swap", swap)


def test_rollback_that_applies_nothing_raises(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A rollback that leaves files different from the safety copy is reported, not silent."""
    data = build_backup(root, NOW)
    _write(root, "_fuzzy/f1.json", '{"id": "changed"}')
    _fail_first_swap(monkeypatch)
    with pytest.raises(backup.RollbackError, match="different"):
        restore_backup(root, data, "2026-11-26T12:00:00Z")


def test_rollback_with_a_broken_safety_copy_raises(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A safety copy that fails inspection stops the rollback with a specific error."""
    data = build_backup(root, NOW)
    monkeypatch.setattr(backup, "build_backup", lambda *_a: b"junk")
    _fail_first_swap(monkeypatch)
    with pytest.raises(backup.RollbackError, match="failed inspection"):
        restore_backup(root, data, "2026-11-26T12:00:00Z")


@pytest.mark.skipif(os.name != "posix", reason="file modes exist on POSIX only")
def test_restored_auth_files_are_owner_only(root: Path) -> None:
    """users.json and roles.json come back with mode 0600."""
    data = build_backup(root, NOW)
    (root / "_auth" / "users.json").unlink()
    restore_backup(root, data, "2026-11-26T12:00:00Z")
    assert stat.S_IMODE((root / "_auth" / "users.json").stat().st_mode) == 0o600
