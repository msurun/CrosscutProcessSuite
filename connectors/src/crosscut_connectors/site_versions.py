"""Draft and immutable numbered versions of the site catalogue.

``<root>/_site/site.json`` stays the PUBLISHED catalogue: runtime, jobs and importers read it
through ``load_site`` and never see a draft. Edits go to ``_site/draft.json``. Publishing writes
``_site/versions/v0001.json`` (a stored copy, never overwritten) with ``v0001.meta.json``
(sha256, author, approver, time, note) and then makes the copy the published file.
A draft remembers the sha256 of the published document it started from, so a publish over a
catalogue that changed meanwhile is refused instead of overwriting it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crosscut_connectors.site import (
    SITE_FOLDER,
    SiteError,
    load_site,
    save_site,
    site_path,
    validate_site,
)

Doc = dict[str, Any]
DRAFT_FILE = "draft.json"
DRAFT_META_FILE = "draft.meta.json"
VERSIONS_FOLDER = "versions"
_META = re.compile(r"^v(\d{4,})\.meta\.json$")


def site_dir(root: Path) -> Path:
    """The ``_site`` folder of a data root."""
    return root / SITE_FOLDER


def versions_dir(root: Path) -> Path:
    """Where the stored versions and the catalogue audit log live."""
    return site_dir(root) / VERSIONS_FOLDER


def document_sha256(document: Doc) -> str:
    """sha256 of the canonical JSON form (sorted keys, no whitespace) of a document."""
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, document: Doc, exclusive: bool = False) -> None:
    """Write JSON atomically; ``exclusive`` refuses to replace an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise SiteError(f"{path.name} already exists; versions are immutable")
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(temp_name, path)


def read_json(path: Path) -> Doc | None:
    """A JSON object from a file, None when the file is absent."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as error:
        raise SiteError(f"{path.name} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise SiteError(f"{path.name} must hold a JSON object")
    return value


def _validate(document: Doc) -> None:
    """Raise SiteError listing the problems of an unacceptable document."""
    problems = validate_site(document)
    if problems:
        raise SiteError("; ".join(problems))


def published_sha256(root: Path) -> str | None:
    """sha256 of the published document, None when the project has no site file."""
    return document_sha256(load_site(root)) if site_path(root).exists() else None


def load_draft(root: Path) -> Doc | None:
    """The draft document, None when there is none."""
    return read_json(site_dir(root) / DRAFT_FILE)


def draft_base_sha256(root: Path) -> str | None:
    """sha256 of the published document the current draft started from."""
    meta = read_json(site_dir(root) / DRAFT_META_FILE) or {}
    return meta.get("base_sha256")


def save_draft(root: Path, document: Doc) -> None:
    """Store ``document`` as the draft (validated); a new draft records its base."""
    _validate(document)
    if load_draft(root) is None:
        write_json(site_dir(root) / DRAFT_META_FILE, {"base_sha256": published_sha256(root)})
    write_json(site_dir(root) / DRAFT_FILE, document)


def discard_draft(root: Path) -> None:
    """Remove the draft and its base record."""
    for name in (DRAFT_FILE, DRAFT_META_FILE):
        (site_dir(root) / name).unlink(missing_ok=True)


def _read_meta(root: Path, number: int) -> Doc:
    """The metadata of one version; SiteError when it does not exist."""
    meta = read_json(versions_dir(root) / f"v{number:04d}.meta.json")
    if meta is None:
        raise SiteError(f"version {number} does not exist")
    return meta


def list_versions(root: Path) -> list[Doc]:
    """Metadata of every stored version, oldest first."""
    folder = versions_dir(root)
    if not folder.is_dir():
        return []
    numbers = sorted(int(m.group(1)) for p in folder.iterdir() if (m := _META.match(p.name)))
    return [_read_meta(root, number) for number in numbers]


def current_version(root: Path) -> int | None:
    """Number of the newest published version, None while nothing was published."""
    versions = list_versions(root)
    return int(versions[-1]["version"]) if versions else None


def get_version(root: Path, number: int) -> tuple[Doc, Doc]:
    """``(meta, document)`` of a version; SiteError when missing or when the copy was altered."""
    meta = _read_meta(root, number)
    document = read_json(versions_dir(root) / f"v{number:04d}.json")
    if document is None or document_sha256(document) != meta["sha256"]:
        raise SiteError(f"version {number} is missing or does not match its sha256")
    return meta, document


def publish_document(
    root: Path, document: Doc, author: str, note: str, approver: str | None = None
) -> Doc:
    """Store ``document`` as the next immutable version and make it the published catalogue.

    Raises SiteError when it is invalid or the published file changed since the draft began.
    """
    if load_draft(root) is not None and draft_base_sha256(root) != published_sha256(root):
        raise SiteError("the published catalogue changed since this draft began")
    _validate(document)
    number = (current_version(root) or 0) + 1
    meta = {
        "version": number,
        "sha256": document_sha256(document),
        "author": author,
        "approver": approver,
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": note,
    }
    write_json(versions_dir(root) / f"v{number:04d}.json", document, exclusive=True)
    write_json(versions_dir(root) / f"v{number:04d}.meta.json", meta, exclusive=True)
    save_site(root, document)
    discard_draft(root)
    return meta
