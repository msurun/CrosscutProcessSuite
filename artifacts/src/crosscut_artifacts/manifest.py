"""Artifact manifest handling."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import numpy as np

SUPPORTED_SCHEMA_VERSION = "0.1.0"


class ArtifactError(ValueError):
    """Base class for artifact-related errors."""


class ArtifactVersionError(ArtifactError):
    """Raised when the artifact schema version is not supported."""


class ArtifactIntegrityError(ArtifactError):
    """Raised when the artifact integrity check fails."""


def sha256_bytes(data: bytes) -> str:
    """Compute the SHA-256 hex digest of the given bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of the file at the given path."""
    sha256 = hashlib.sha256()
    with path.open("rb") as binary_file:
        while chunk := binary_file.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def tags_signature(tag_ids: Sequence[str]) -> str:
    """Compute the SHA-256 hex digest of the given tag IDs."""
    return sha256_bytes("\n".join(tag_ids).encode("utf-8"))


def check_schema_version(version: str) -> None:
    """Check if the given schema version is supported."""
    if not re.fullmatch(r"^\d+\.\d+\.\d+$", version):
        raise ArtifactError(f"Invalid schema version: {version}")
    supported_major = int(SUPPORTED_SCHEMA_VERSION.split(".")[0])
    major = int(version.split(".")[0])
    if major > supported_major:
        raise ArtifactVersionError(f"Unsupported schema version: {version}")


def _validate_payload_path(path: str, reading: bool = False) -> None:
    """Validate the given payload path."""
    if not path:
        raise ArtifactError("Payload path cannot be empty")
    if path == ".":
        raise ArtifactError("Payload path cannot be '.'")
    if "\\" in path:
        raise ArtifactError("Payload path cannot contain backslashes")
    if PurePosixPath(path).is_absolute():
        raise ArtifactError("Payload path cannot be absolute")
    if PureWindowsPath(path).drive or PureWindowsPath(path).root:
        raise ArtifactError("Payload path cannot be absolute")
    if ".." in PurePosixPath(path).parts:
        raise ArtifactError("Payload path cannot contain '..'")


def npz_bytes(arrays: Mapping[str, np.ndarray]) -> bytes:
    """Create a deterministic .npz archive from the given arrays."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as zf:
        for name, array in arrays.items():
            entry_buffer = io.BytesIO()
            np.lib.format.write_array(entry_buffer, array, allow_pickle=False)
            entry_data = entry_buffer.getvalue()
            info = zipfile.ZipInfo(
                f"{name}.npy",
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            zf.writestr(info, entry_data)
    return buffer.getvalue()


def write_artifact(
    out_dir: str | Path,
    artifact_type: str,
    payload: Mapping[str, bytes],
    *,
    creator: Mapping[str, str],
    inputs: Sequence[Mapping[str, str]] | None = None,
    tags_signature: str | None = None,
    metrics: Mapping[str, Any] | None = None,
    valid_context: Mapping[str, Any] | None = None,
    created_utc: str | None = None,
    signature: str | None = None,
) -> dict[str, Any]:
    """Write an artifact to the given directory."""
    if not re.fullmatch(r"^[a-z][a-z0-9_]*$", artifact_type):
        raise ValueError(f"Invalid artifact type: {artifact_type}")
    if not payload:
        raise ValueError("Payload cannot be empty")
    for path in payload:
        _validate_payload_path(path)

    out_dir = Path(out_dir)
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"Artifact already exists at {out_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    for path, data in payload.items():
        (out_dir / path).parent.mkdir(parents=True, exist_ok=True)
        (out_dir / path).write_bytes(data)

    doc: dict[str, Any] = {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "artifact_type": artifact_type,
        "created_utc": created_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "creator": dict(creator),
    }
    if inputs is not None:
        doc["inputs"] = [dict(input_) for input_ in inputs]
    if tags_signature is not None:
        doc["tags_signature"] = tags_signature
    doc["payload"] = sorted(
        [{"path": path, "sha256": sha256_bytes(data)} for path, data in payload.items()],
        key=lambda x: x["path"],
    )
    if metrics is not None:
        doc["metrics"] = metrics
    if valid_context is not None:
        doc["valid_context"] = valid_context
    doc["signature"] = signature

    manifest_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def read_manifest(path: str | Path, *, verify: bool = True) -> dict[str, Any]:
    """Read the manifest from the given artifact directory."""
    path = Path(path)
    doc = _load_manifest_document(path)
    _validate_manifest_document(doc, path)
    if verify:
        _verify_payload_files(doc, path)
    return doc


def _load_manifest_document(path: Path) -> dict[str, Any]:
    """Load and parse the manifest JSON document."""
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        raise ArtifactError(f"Manifest not found at {manifest_path}")
    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ArtifactError(f"Invalid manifest at {manifest_path}") from e
    if not isinstance(doc, dict):
        raise ArtifactError(f"Manifest at {manifest_path} is not a JSON object")
    return doc


def _validate_manifest_document(doc: dict[str, Any], path: Path) -> None:
    """Validate the manifest structure and payload paths."""
    manifest_path = path / "manifest.json"
    if "schema_version" not in doc or "payload" not in doc:
        raise ArtifactError(f"Invalid manifest at {manifest_path}")

    check_schema_version(doc["schema_version"])
    for item in doc["payload"]:
        _validate_payload_path(item["path"], reading=True)


def _verify_payload_files(doc: dict[str, Any], path: Path) -> None:
    """Verify that every payload file exists and matches its recorded hash."""
    for item in doc["payload"]:
        file_path = path / item["path"]
        if not file_path.exists():
            raise ArtifactIntegrityError(f"Payload file not found: {file_path}")
        if sha256_file(file_path) != item["sha256"]:
            raise ArtifactIntegrityError(f"Payload file integrity check failed: {file_path}")
