"""Tests for artifact manifests: writing, reading, integrity and version compatibility."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from crosscut_artifacts.manifest import (
    SUPPORTED_SCHEMA_VERSION,
    ArtifactError,
    ArtifactIntegrityError,
    ArtifactMetadata,
    ArtifactVersionError,
    check_schema_version,
    npz_bytes,
    read_manifest,
    sha256_bytes,
    tags_signature,
    write_artifact,
)
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
CREATOR = {"tool": "crosscut-ident", "version": "0.1.0"}
CREATED = "2026-10-10T12:00:00Z"
METADATA = ArtifactMetadata(creator=CREATOR, created_utc=CREATED)


def manifest_validator() -> Draft202012Validator:
    """Build the JSON Schema validator for the artifact manifest schema in this repository."""
    schema = json.loads(
        (REPO_ROOT / "schemas" / "artifact-manifest.schema.json").read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema)


def make(out: Path, **kwargs: Any) -> dict[str, Any]:
    """Write the sample model artifact to ``out`` with two member files."""
    payload = {
        "model.npz": npz_bytes({"gain": np.array([[1.0, 2.0], [3.0, 4.0]])}),
        "notes/readme.txt": b"hello",
    }
    return write_artifact(
        out,
        "model",
        payload,
        ArtifactMetadata(creator=CREATOR, created_utc=CREATED, **kwargs),
    )


def test_supported_version_matches_schema_version_in_use() -> None:
    assert SUPPORTED_SCHEMA_VERSION == "0.1.0"


def test_round_trip_validates_against_schema(tmp_path: Path) -> None:
    """Test that a manifest round-trip preserves all data and validates against the schema."""
    doc = make(
        tmp_path,
        inputs=[{"dataset_hash": "a" * 64}],
        tags_signature=tags_signature(["a", "b"]),
        metrics={"rmse": 0.12},
        valid_context={"ore": "hard"},
    )
    on_disk = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == doc

    validate_manifest(doc)
    validate_schema_version(doc)
    validate_artifact_type(doc)
    validate_created_utc(doc)
    validate_signature(doc)
    validate_payload_paths(doc, tmp_path)


def validate_manifest(doc: dict) -> None:
    """Validate the manifest against the schema.

    Raises:
        AssertionError: if the manifest violates the schema; the message lists
            every validation error found.
    """
    errors = list(manifest_validator().iter_errors(doc))
    assert errors == [], [error.message for error in errors]


def validate_schema_version(doc: dict) -> None:
    """Validate the schema version."""
    assert doc["schema_version"] == SUPPORTED_SCHEMA_VERSION


def validate_artifact_type(doc: dict) -> None:
    """Validate the artifact type."""
    assert doc["artifact_type"] == "model"


def validate_created_utc(doc: dict) -> None:
    """Validate the created UTC timestamp."""
    assert doc["created_utc"] == CREATED


def validate_signature(doc: dict) -> None:
    """Validate the signature."""
    assert doc["signature"] is None


def validate_payload_paths(doc: dict, tmp_path: Path) -> None:
    """Validate the payload paths and their contents."""
    paths = {item["path"]: item["sha256"] for item in doc["payload"]}
    assert set(paths) == {"model.npz", "notes/readme.txt"}
    assert paths["notes/readme.txt"] == sha256_bytes(b"hello")
    assert (tmp_path / "notes" / "readme.txt").read_bytes() == b"hello"
    assert read_manifest(tmp_path) == doc


def test_optional_sections_are_omitted_when_not_given(tmp_path: Path) -> None:
    doc = make(tmp_path)
    for key in ("inputs", "tags_signature", "metrics", "valid_context"):
        assert key not in doc
    assert list(manifest_validator().iter_errors(doc)) == []


def test_output_is_deterministic(tmp_path: Path) -> None:
    make(tmp_path / "a")
    make(tmp_path / "b")
    assert (tmp_path / "a" / "manifest.json").read_bytes() == (
        tmp_path / "b" / "manifest.json"
    ).read_bytes()
    arrays = {"x": np.arange(5.0), "y": np.eye(2)}
    assert npz_bytes(arrays) == npz_bytes(arrays)
    loaded = np.load(io.BytesIO(npz_bytes(arrays)))
    assert set(loaded.files) == {"x", "y"}
    assert np.array_equal(loaded["y"], np.eye(2))
    with zipfile.ZipFile(io.BytesIO(npz_bytes(arrays))) as zf:
        assert {info.date_time for info in zf.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_refuses_to_overwrite_an_existing_artifact(tmp_path: Path) -> None:
    make(tmp_path)
    with pytest.raises(FileExistsError):
        make(tmp_path)


def test_tampered_or_missing_payload_is_detected(tmp_path: Path) -> None:
    make(tmp_path / "tampered")
    (tmp_path / "tampered" / "notes" / "readme.txt").write_bytes(b"HELLO")
    with pytest.raises(ArtifactIntegrityError):
        read_manifest(tmp_path / "tampered")
    # verification can be skipped explicitly
    assert read_manifest(tmp_path / "tampered", verify=False)["artifact_type"] == "model"

    make(tmp_path / "missing")
    (tmp_path / "missing" / "model.npz").unlink()
    with pytest.raises(ArtifactIntegrityError):
        read_manifest(tmp_path / "missing")


@pytest.mark.parametrize(
    ("version", "ok"),
    [("0.1.0", True), ("0.0.1", True), ("0.9.9", True), ("1.0.0", False), ("2.3.4", False)],
)
def test_version_rule_rejects_higher_major(version: str, ok: bool) -> None:
    if ok:
        check_schema_version(version)
    else:
        with pytest.raises(ArtifactVersionError):
            check_schema_version(version)


@pytest.mark.parametrize("version", ["v1", "1.0", "", "1.0.0-beta", "a.b.c"])
def test_malformed_version_is_rejected(version: str) -> None:
    with pytest.raises(ArtifactError):
        check_schema_version(version)


def test_reading_a_manifest_with_a_newer_major_version_fails(tmp_path: Path) -> None:
    make(tmp_path)
    path = tmp_path / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["schema_version"] = "1.0.0"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ArtifactVersionError):
        read_manifest(tmp_path)


@pytest.mark.parametrize(
    "name", ["../evil.bin", "/abs.bin", "a/../../b.bin", "C:/abs.bin", "", "."]
)
def test_unsafe_payload_paths_are_rejected_on_write(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        write_artifact(tmp_path / "x", "model", {name: b"x"}, METADATA)
    assert not (tmp_path / "evil.bin").exists()


def test_unsafe_payload_paths_are_rejected_on_read(tmp_path: Path) -> None:
    make(tmp_path)
    path = tmp_path / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["payload"][0]["path"] = "../outside.bin"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ArtifactError):
        read_manifest(tmp_path)


def test_empty_payload_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_artifact(tmp_path / "x", "model", {}, METADATA)


def test_invalid_artifact_type_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_artifact(tmp_path / "x", "Bad Type", {"a": b"1"}, ArtifactMetadata(creator=CREATOR))


def test_tags_signature_is_stable_order_sensitive_and_hex() -> None:
    signature = tags_signature(["sim.a", "sim.b"])
    assert signature == tags_signature(["sim.a", "sim.b"])
    assert signature != tags_signature(["sim.b", "sim.a"])
    assert len(signature) == 64
    assert set(signature) <= set("0123456789abcdef")
