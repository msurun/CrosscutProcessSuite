"""Build, inspect and restore a configuration backup zip (issue #167).

A backup is a zip with ``manifest.json`` (format version, creation time, per-file sha256, secrets
that must be re-entered) and the files of ``backup_scope``. Restore first checks everything in
memory (a dry run), then stages every file next to the data root and swaps them in; a failure
during the swap puts the pre-restore safety copy back. Secrets are never exported.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crosscut_api.backup_scope import (
    EXCLUDED_NOTES,
    KIND_CONFIG,
    KIND_EVIDENCE,
    is_safe_path,
    kind_of,
    scope_files,
)

Doc = dict[str, Any]
FORMAT = "crosscut-backup"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"
BACKUP_DIR = "_backup"
KEEP_SAFETY_COPIES = 5
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024  # compressed size of the upload
MAX_UNPACKED_BYTES = 512 * 1024 * 1024  # sum of the declared sizes of all members
MAX_RATIO = 200  # declared size / compressed size of one member (zip bomb guard)
RATIO_CHECK_FROM = 1024 * 1024  # smaller members cannot hurt, so the ratio is not checked
PRIVATE_FOLDER = "_auth"  # users, roles and settings: owner-only files where the OS supports it
# Versioned files: path or prefix -> (schema file, version key).
SCHEMA_VERSIONED = (
    ("_site/site.json", "site.schema.json", "schema_version"),
    ("_trends/charts/", "trend-chart.schema.json", "schema_version"),
    ("_auth/users.json", "auth-users.schema.json", "version"),
)
GATEWAY_KEY_NOTE = (
    "_secrets/gateway-hmac.key (or CROSSCUT_SECRETS_DIR): copy it by hand, see the runbook"
)


class RollbackError(Exception):
    """The safety copy could not be put back; the data root may be half restored."""


class BackupError(Exception):
    """A backup cannot be restored; ``problems`` lists every reason, one per line."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Report:
    """The dry-run result: what the archive holds and what a restore would change."""

    ok: bool
    archive_sha256: str
    problems: list[str] = field(default_factory=list)
    created_utc: str = ""
    format_version: int = 0
    changes: list[Doc] = field(default_factory=list)
    must_reenter: list[Doc] = field(default_factory=list)

    def as_dict(self) -> Doc:
        """JSON form served by the API."""
        return {
            "ok": self.ok, "archive_sha256": self.archive_sha256, "problems": self.problems,
            "created_utc": self.created_utc, "format_version": self.format_version,
            "changes": self.changes, "must_reenter": self.must_reenter,
        }  # fmt: skip


def sha256_hex(data: bytes) -> str:
    """Lower-case hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def _schema_dir() -> Path:
    """Folder of the JSON schemas (``CROSSCUT_SCHEMAS_DIR`` overrides the repository one)."""
    override = os.environ.get("CROSSCUT_SCHEMAS_DIR")
    return Path(override) if override else Path(__file__).resolve().parents[3] / "schemas"


def _schema_entry(relative: str) -> tuple[str, str] | None:
    """(schema file, version key) for a path whose layout version is checked, else None."""
    for prefix, schema, key in SCHEMA_VERSIONED:
        if relative == prefix or (prefix.endswith("/") and relative.startswith(prefix)):
            return schema, key
    return None


def _supported_version(schema_file: str, key: str) -> int | None:
    """The layout version this build writes (the ``const`` of the schema), or None if unknown."""
    try:
        schema = json.loads((_schema_dir() / schema_file).read_text(encoding="utf-8"))
        const = schema["properties"][key]["const"]
    except (OSError, ValueError, KeyError):
        return None
    return const if isinstance(const, int) else None


def _json_version(relative: str, data: bytes) -> object:
    """The layout version stored in a versioned JSON file; None when absent or unreadable."""
    entry = _schema_entry(relative)
    if entry is None:
        return None
    try:
        doc = json.loads(data.decode("utf-8"))
    except ValueError:
        return None
    return doc.get(entry[1]) if isinstance(doc, dict) else None


def must_reenter(root: Path) -> list[Doc]:
    """The secrets a restored site needs again: source credentials and the gateway key."""
    items: list[Doc] = [{"kind": "gateway_key", "where": GATEWAY_KEY_NOTE}]
    try:
        site = json.loads((root / "_site" / "site.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return items
    for source in site.get("sources", []) if isinstance(site, dict) else []:
        ref = (source.get("auth") or {}).get("credential_ref")
        if ref:
            items.append({"kind": "source_secret", "source": source.get("id", ""), "ref": ref})
    return items


def _entry(relative: str, kind: str, data: bytes) -> Doc:
    """One manifest line for a file."""
    entry: Doc = {"path": relative, "kind": kind, "size": len(data), "sha256": sha256_hex(data)}
    version = _json_version(relative, data)
    if version is not None:
        entry["schema_version"] = version
    return entry


def build_backup(root: Path, created_utc: str) -> bytes:
    """The zip of every in-scope file of ``root`` with its manifest."""
    entries: list[Doc] = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative, kind in scope_files(root).items():
            data = (root / relative).read_bytes()
            archive.writestr(relative, data)
            entries.append(_entry(relative, kind, data))
        manifest = {
            "format": FORMAT, "format_version": FORMAT_VERSION, "created_utc": created_utc,
            "files": entries, "excluded": list(EXCLUDED_NOTES), "must_reenter": must_reenter(root),
        }  # fmt: skip
        archive.writestr(MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False))
    return buffer.getvalue()


def _manifest_of(archive: zipfile.ZipFile, problems: list[str]) -> Doc | None:
    """The parsed manifest, or None with a problem recorded."""
    try:
        manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
    except (KeyError, ValueError):
        problems.append("manifest.json is missing or unreadable")
        return None
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        problems.append("not a Crosscut backup (manifest format)")
        return None
    version = manifest.get("format_version")
    if not isinstance(version, int):
        problems.append("manifest has no integer format_version")
        return None
    if version > FORMAT_VERSION:
        problems.append(
            f"backup format {version} is newer than this version supports ({FORMAT_VERSION})"
        )
        return None
    if not isinstance(manifest.get("files"), list):
        problems.append("manifest has no file list")
        return None
    return manifest


def _check_entry(archive: zipfile.ZipFile, item: Doc, problems: list[str]) -> bytes | None:
    """Bytes of one listed file when it is safe, in scope and matches its hash; else None."""
    path = item.get("path")
    if not isinstance(path, str) or not is_safe_path(path):
        problems.append(f"unsafe path in manifest: {path!r}")
        return None
    if kind_of(path) != item.get("kind"):
        problems.append(f"{path}: not part of a backup or wrong kind")
        return None
    try:
        data = archive.read(path)
    except KeyError:
        problems.append(f"{path}: listed in the manifest but missing from the archive")
        return None
    if sha256_hex(data) != item.get("sha256") or len(data) != item.get("size"):
        problems.append(f"{path}: content does not match the manifest hash (tampered or damaged)")
        return None
    return data


def _check_schema(path: str, data: bytes, item: Doc, problems: list[str]) -> None:
    """Problems when a versioned file disagrees with the manifest, is not numbered or is too new."""
    entry = _schema_entry(path)
    if entry is None:
        return
    version = _json_version(path, data)
    if version != item.get("schema_version"):
        problems.append(f"{path}: schema version differs from the manifest")
    elif not isinstance(version, int):
        problems.append(f"{path}: schema version is missing or not a number")
    else:
        supported = _supported_version(*entry)
        if supported is not None and version > supported:
            problems.append(
                f"{path}: schema version {version} is newer than supported ({supported})"
            )


def _verify_contents(
    archive: zipfile.ZipFile, manifest: Doc, problems: list[str]
) -> dict[str, bytes]:
    """Check every listed file; return the bytes of the good ones. Unlisted members are problems."""
    contents: dict[str, bytes] = {}
    listed = [item for item in manifest["files"] if isinstance(item, dict)]
    for item in listed:
        data = _check_entry(archive, item, problems)
        if data is None:
            continue
        contents[item["path"]] = data
        _check_schema(item["path"], data, item, problems)
    names = {item.get("path") for item in listed} | {MANIFEST}
    problems += [
        f"{n}: in the archive but not in the manifest" for n in archive.namelist() if n not in names
    ]
    return contents


def _plan(root: Path, contents: dict[str, bytes], kinds: dict[str, str]) -> list[Doc]:
    """The per-file changes a restore makes on ``root``; audit logs are kept as they are."""
    live = scope_files(root)
    changes: list[Doc] = []
    for path, data in sorted(contents.items()):
        if kinds[path] == KIND_EVIDENCE:
            action = "keep_evidence"
        elif path not in live:
            action = "add"
        else:
            action = "unchanged" if (root / path).read_bytes() == data else "replace"
        changes.append({"path": path, "action": action})
    gone = [p for p, kind in live.items() if kind == KIND_CONFIG and p not in contents]
    return changes + [{"path": path, "action": "remove"} for path in gone]


def _size_problem(archive: zipfile.ZipFile) -> str | None:
    """A reason to refuse the archive before any member is read (zip bomb guard), else None."""
    infos = archive.infolist()
    if sum(info.file_size for info in infos) > MAX_UNPACKED_BYTES:
        return f"unpacked size exceeds the limit of {MAX_UNPACKED_BYTES} bytes"
    for info in infos:
        ratio = info.file_size / max(info.compress_size, 1)
        if info.file_size >= RATIO_CHECK_FROM and ratio > MAX_RATIO:
            return (
                f"{info.filename}: compression ratio {ratio:.0f} exceeds the limit of {MAX_RATIO}"
            )
    return None


def inspect_backup(root: Path, data: bytes) -> tuple[Report, dict[str, bytes]]:
    """Dry run: validate the archive and plan the restore. Nothing on disk changes."""
    report = Report(ok=False, archive_sha256=sha256_hex(data))
    if len(data) > MAX_ARCHIVE_BYTES or not zipfile.is_zipfile(io.BytesIO(data)):
        report.problems.append("the file is not a zip archive or is too large")
        return report, {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        size_problem = _size_problem(archive)
        if size_problem:
            report.problems.append(size_problem)
            return report, {}
        manifest = _manifest_of(archive, report.problems)
        if manifest is None:
            return report, {}
        contents = _verify_contents(archive, manifest, report.problems)
    report.created_utc = str(manifest.get("created_utc", ""))
    report.format_version = manifest["format_version"]
    reenter = manifest.get("must_reenter")
    report.must_reenter = reenter if isinstance(reenter, list) else []
    report.ok = not report.problems
    if report.ok:
        kinds = {path: kind_of(path) or "" for path in contents}
        report.changes = _plan(root, contents, kinds)
    return report, contents


def _inside(base: Path, relative: str) -> Path:
    """``base / relative`` after resolving links; BackupError when it would leave ``base``."""
    target = (base / relative).resolve()
    if not target.is_relative_to(base.resolve()):
        raise BackupError([f"{relative}: path leaves the target folder"])
    return target


def restrict_permissions(path: Path) -> None:
    """Owner-only mode (0600) where the OS has modes; silently nothing on Windows (ACLs)."""
    if os.name == "posix":
        os.chmod(path, 0o600)


def _write_all(base: Path, contents: dict[str, bytes]) -> None:
    """Write every file below ``base`` (the staging folder)."""
    for relative, data in contents.items():
        target = _inside(base, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _swap(root: Path, staging: Path, contents: dict[str, bytes]) -> None:
    """Move staged files into place (atomic replace each); delete live config files not kept."""
    live = scope_files(root)
    for relative in contents:
        destination = _inside(root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.copymode(destination, staging / relative)
        if relative.startswith(f"{PRIVATE_FOLDER}/"):
            restrict_permissions(staging / relative)
        os.replace(staging / relative, destination)
    for relative, kind in live.items():
        if kind == KIND_CONFIG and relative not in contents:
            (root / relative).unlink(missing_ok=True)


def _config_only(contents: dict[str, bytes]) -> dict[str, bytes]:
    """The files a restore replaces (audit logs excluded)."""
    return {path: data for path, data in contents.items() if kind_of(path) == KIND_CONFIG}


def _stamp(now_utc: str) -> str:
    """A file-name safe form of an ISO timestamp."""
    return now_utc.replace(":", "").replace("-", "")


def _apply(root: Path, files: dict[str, bytes], name: str) -> None:
    """Stage ``files`` in a folder of ``_backup`` and swap them into ``root``."""
    staging = root / BACKUP_DIR / name
    try:
        _write_all(staging, files)
        _swap(root, staging, files)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _rollback(root: Path, safety: Path, now_utc: str) -> None:
    """Put the pre-restore state back from the safety copy."""
    report, contents = inspect_backup(root, safety.read_bytes())
    if not report.ok:
        raise RollbackError(f"safety copy {safety.name} failed inspection: {report.problems}")
    expected = _config_only(contents)
    _apply(root, expected, f"rollback-{_stamp(now_utc)}")
    wrong = [p for p, data in expected.items() if _live_bytes(root, p) != data]
    if wrong:
        raise RollbackError(f"rollback left {len(wrong)} file(s) different: {wrong[:3]}")


def _live_bytes(root: Path, relative: str) -> bytes | None:
    """The bytes of a live file, or None when it is missing."""
    try:
        return (root / relative).read_bytes()
    except OSError:
        return None


def restore_backup(
    root: Path, data: bytes, now_utc: str, before_swap: Callable[[Report], None] = lambda _r: None
) -> Report:
    """Validate, stage and swap a backup in. Raises BackupError when the archive is refused.

    ``before_swap`` runs after the safety copy is written and before the first live file changes;
    when it raises nothing has changed. A failure during the swap restores the safety copy.
    """
    report, contents = inspect_backup(root, data)
    if not report.ok:
        raise BackupError(report.problems)
    folder = root / BACKUP_DIR
    folder.mkdir(exist_ok=True)
    safety = folder / f"pre-restore-{_stamp(now_utc)}.zip"
    safety.write_bytes(build_backup(root, now_utc))
    before_swap(report)
    staging = folder / f"staging-{_stamp(now_utc)}"
    new_files = _config_only(contents)
    try:
        _write_all(staging, new_files)
        _swap(root, staging, new_files)
    except BaseException as error:
        try:
            _rollback(root, safety, now_utc)
        except RollbackError as failed:
            raise failed from error
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    for old in sorted(folder.glob("pre-restore-*.zip"))[:-KEEP_SAFETY_COPIES]:
        old.unlink(missing_ok=True)
    return report
