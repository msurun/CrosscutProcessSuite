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
    """Compute the SHA-256 hex digest of the file at the given path.

    SHA-256 (Secure Hash Algorithm, 256-bit, from the FIPS 180-4 standard) maps any
    input to a fixed 64-character hexadecimal string, called the digest. The digest
    acts as a fingerprint: two identical files always produce the same digest, and a
    changed file produces a completely different one. This allows a caller to detect
    whether a file was corrupted or tampered with.

    The file is hashed in a streaming fashion, so arbitrarily large files can be
    processed without loading them entirely into memory. The function is pure with
    respect to its input: it reads the file but never writes to it, so nothing
    observable changes.

    Args:
        path: Location of the file to hash, opened in binary mode.

    Returns:
        The lowercase hexadecimal SHA-256 digest, 64 characters long.
    """
    # A SHA-256 object accumulates input across update() calls.
    sha256 = hashlib.sha256()
    with path.open("rb") as binary_file:
        # The walrus operator assigns the next chunk and tests it in one step. The
        # loop stops when read() returns b"", which signals end-of-file. 8192 bytes
        # (8 KiB) is the chunk size in bytes: large enough to keep read overhead low,
        # small enough to keep memory use constant regardless of file size.
        while chunk := binary_file.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def tags_signature(tag_ids: Sequence[str]) -> str:
    """Compute the SHA-256 hex digest of the given tag IDs."""
    return sha256_bytes("\n".join(tag_ids).encode("utf-8"))


def check_schema_version(version: str) -> None:
    """Check if the given schema version is supported.

    Versions follow the three-part semantic versioning format ``major.minor.patch``
    (units: integers). Only the major part is compared, because a different major
    number means the artifact format changed in a way this code cannot read;
    minor and patch differences are assumed to stay readable.

    Returns None when the version is well formed and its major part is known.

    Raises:
        ArtifactError: the version is not ``major.minor.patch`` with digit parts.
        ArtifactVersionError: the artifact was written by a newer, unknown schema.
    """
    # Only accept the exact "digits.digits.digits" shape, so that the int() calls
    # below cannot fail on empty parts or stray characters.
    if not re.fullmatch(r"^\d+\.\d+\.\d+$", version):
        raise ArtifactError(f"Invalid schema version: {version}")
    # The version this build was written against; its major number is the newest
    # schema generation we can still parse.
    supported_major = int(SUPPORTED_SCHEMA_VERSION.split(".")[0])
    major = int(version.split(".")[0])
    # A higher major means a backwards-incompatible format, so refuse it loudly
    # instead of reading the artifact with wrong assumptions.
    if major > supported_major:
        raise ArtifactVersionError(f"Unsupported schema version: {version}")


def _validate_payload_path(path: str, reading: bool = False) -> None:
    """Validate the given payload path.

    A payload path names a file or directory inside an artifact bundle. It is stored and later
    joined with an extraction directory, so it must stay *relative* and stay *inside* that
    directory: something like ``model/weights.bin`` is fine, while ``/etc/passwd`` or
    ``../../secrets`` would escape it (a path-traversal attack).

    The checks here are deliberately textual and purely syntactic: the path is never resolved
    against the filesystem, so the same string is accepted on Linux and Windows.

    Args:
        path: The payload path to validate, in POSIX form (``/`` as the separator).
        reading: Unused for now; kept so callers can share one signature for read and write.

    Raises:
        ArtifactError: If the path is empty, absolute, or contains a separator or ``..``
            segment that would let it leave the artifact directory.
    """
    # An empty path would make callers join the extraction directory with nothing, silently
    # pointing at the directory itself instead of a file inside it.
    if not path:
        raise ArtifactError("Payload path cannot be empty")
    # A lone "." is the current directory: joining it with the extraction directory yields the
    # extraction directory, so it is the same "points at the directory" hazard as above.
    if path == ".":
        raise ArtifactError("Payload path cannot be '.'")
    if "\\" in path:
        raise ArtifactError("Payload path cannot contain backslashes")
    if PurePosixPath(path).is_absolute():
        raise ArtifactError("Payload path cannot be absolute")
    # PurePosixPath sees "C:/x" as a single relative segment, so Windows syntax needs its own
    # parser: "drive" is the "C:" part and "root" is the leading "/" or "\" after it.
    if PureWindowsPath(path).drive or PureWindowsPath(path).root:
        raise ArtifactError("Payload path cannot be absolute")
    # Split first, then test each segment for equality: a substring test on ".." would also
    # reject innocent names such as "notes..txt", while segment-wise ".." is always a climb up.
    if ".." in PurePosixPath(path).parts:
        raise ArtifactError("Payload path cannot contain '..'")


def npz_bytes(arrays: Mapping[str, np.ndarray]) -> bytes:
    """Create a deterministic .npz archive from the given arrays.

    A .npz file is just a ZIP archive holding one .npy file per array: the
    exact same bytes are produced for the same input, so the output can be
    hashed or compared between runs. ``arrays`` maps an array name to the
    numpy array to store under it.

    Returns:
        The archive as raw bytes, ready to be written to disk or hashed.

    Raises:
        ValueError: If an array holds opaque Python objects, which numpy
            refuses to serialise when pickling is disabled.
    """
    # The archive is built in memory: no temporary file on disk, and the
    # whole ZIP can be returned as a single bytes object at the end.
    buffer = io.BytesIO()
    # ZIP_STORED copies bytes verbatim instead of compressing. Compression
    # would be slower (deflate is not free) and its output could change
    # between zlib versions, which would break byte-for-byte reproducibility.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as zf:
        # dict preserves insertion order, so names are written in the order
        # the caller listed them: the archive layout depends only on input.
        for name, array in arrays.items():
            # numpy's own .npy format, written into a scratch buffer. It
            # holds a magic string, the dtype, the shape and the raw values.
            # allow_pickle=False keeps the file portable and safe to load:
            # loading it can never execute code hidden in the archive.
            entry_buffer = io.BytesIO()
            np.lib.format.write_array(entry_buffer, array, allow_pickle=False)
            entry_data = entry_buffer.getvalue()
            # ZipInfo lets us set every field of the zip header by hand.
            # A fresh ZipInfo would otherwise default some of them from the
            # clock or from the running OS, making two "identical" archives
            # differ. The fixed date is the ZIP epoch (1980-01-01) because
            # ZIP stores timestamps in a 16-bit field that cannot go earlier.
            info = zipfile.ZipInfo(
                f"{name}.npy",
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            # Each of the three fields below is pinned to a constant value
            # for the same reason: reproducibility. create_system = 3 means
            # "Unix"; external_attr holds the Unix file mode in its high
            # 16 bits (0o600 = owner read/write only) with no DOS flags in
            # the low bits.
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            zf.writestr(info, entry_data)
    # getvalue() returns everything written so far without consuming the
    # buffer, so the bytes can still be copied or read again by the caller.
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
    """Write an artifact to the given directory.

    An "artifact" is a bundle of files (the payload) plus a manifest.json that
    describes them: content hashes, provenance (who made it, from which inputs)
    and optional metadata. The manifest is written last, so its presence marks
    the directory as a complete artifact.

    payload maps a relative file path to the raw bytes of that file; nested
    paths such as "data/table.csv" are allowed. Returns the manifest as a dict.
    """
    # The type becomes part of a filename and of lookups elsewhere, so it is
    # restricted to a lowercase "snake_case" identifier: no path separators,
    # no dots, nothing that could escape the artifact directory.
    if not re.fullmatch(r"^[a-z][a-z0-9_]*$", artifact_type):
        raise ValueError(f"Invalid artifact type: {artifact_type}")

    # An artifact with no files carries no information; reject it early rather
    # than writing a manifest that points at nothing.
    if not payload:
        raise ValueError("Payload cannot be empty")
    for path in payload:
        _validate_payload_path(path)

    out_dir = Path(out_dir)

    # The manifest is the sentinel for "an artifact already lives here". Writing
    # over an existing artifact would silently mix two payloads, so refuse.
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"Artifact already exists at {out_dir}")

    # Write the payload first, the manifest afterwards (see the docstring).
    # parents=True creates intermediate directories so a nested relative path
    # such as "a/b/c.bin" can be stored as-is.
    out_dir.mkdir(parents=True, exist_ok=True)
    for path, data in payload.items():
        (out_dir / path).parent.mkdir(parents=True, exist_ok=True)
        (out_dir / path).write_bytes(data)

    # Built up field by field: required fields always present, optional ones
    # only when the caller supplied them, so absent means "not applicable"
    # rather than null.
    doc: dict[str, Any] = {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "artifact_type": artifact_type,
        # created_utc is an ISO-8601 UTC timestamp, e.g. "2024-05-01T09:30:00Z".
        "created_utc": created_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "creator": dict(creator),
    }
    if inputs is not None:
        doc["inputs"] = [dict(input_) for input_ in inputs]
    if tags_signature is not None:
        doc["tags_signature"] = tags_signature

    # Payload index: one entry per file with its path (relative, as given by the
    # caller) and the SHA-256 of its bytes, sorted by path so the manifest is
    # byte-for-byte reproducible for the same payload. sha256_bytes returns the
    # digest as a lowercase hex string.
    doc["payload"] = sorted(
        [{"path": path, "sha256": sha256_bytes(data)} for path, data in payload.items()],
        key=lambda x: x["path"],
    )
    if metrics is not None:
        doc["metrics"] = metrics
    if valid_context is not None:
        doc["valid_context"] = valid_context

    # signature may be None: then the key exists with a null value, meaning
    # "this artifact was written unsigned".
    doc["signature"] = signature

    # Trailing newline after the JSON, so the file is a well-formed text file
    # for tools such as `git diff` and line-based readers.
    manifest_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def read_manifest(path: str | Path, *, verify: bool = True) -> dict[str, Any]:
    """Read the manifest from the given artifact directory.

    A "manifest" is the JSON index of a model artifact: it lists the files that
    make up the artifact together with their metadata (size, checksum, ...).
    The `checksum` field of each entry identifies the file content by hash, so a
    reader can detect a corrupted or edited artifact.

    Args:
        path: directory that holds the manifest, or the manifest file itself.
        verify: when True, also hash the payload files on disk and compare the
            result against the checksums stored in the manifest. This costs one
            full read of every file, so callers that only want the metadata can
            pass verify=False.

    Returns:
        The manifest as a dict with the parsed document structure.

    Raises:
        FileNotFoundError: if the manifest is missing under `path`.
        ValueError: if the document is not a valid manifest, or if verify=True
            and a payload file does not match its recorded checksum.
    """
    # Normalise early (str, Path and other path-likes) so every helper below can
    # assume it receives a real Path.
    path = Path(path)

    # Step 1: read the document. This is I/O only: no structure checks happen yet,
    # so the result may be any JSON value (dict, list, scalar, ...).
    doc = _load_manifest_document(path)

    # Step 2: check the shape. After this call the manifest is known to be a dict
    # with the expected keys, so the assertions further down are safe to rely on.
    _validate_manifest_document(doc, path)

    # Step 3: optional integrity check. Skipped by default in cheap callers
    # because it reads every payload file (hash of the whole file, disk-bound).
    if verify:
        _verify_payload_files(doc, path)

    return doc


def _load_manifest_document(path: Path) -> dict[str, Any]:
    """Load and parse the manifest JSON document.

    A "manifest" is the metadata file an artifact ships with: it describes the artifact
    (name, version, thresholds, and so on) as a JSON object. This function reads it from
    disk and returns it as a plain Python dict.

    The document lives at ``<path>/manifest.json``. We deliberately distinguish three
    failure modes so the caller can print a useful message:
    - the file is missing,
    - the file is present but is not valid JSON,
    - the file is valid JSON but is not a JSON object.

    Returns the parsed manifest as a ``dict``.
    Raises ArtifactError with the offending path in the message for any of the above.
    """
    # We build the full path ourselves instead of asking the caller for a file path,
    # so callers cannot accidentally point at a document with a different layout.
    manifest_path = path / "manifest.json"

    # Fail fast on the missing-file case: json parsing below would only say "no such file",
    # which loses the reason and the path we actually looked at.
    if not manifest_path.exists():
        raise ArtifactError(f"Manifest not found at {manifest_path}")
    try:
        # Read as text with an explicit encoding rather than letting Python guess the
        # platform default: a manifest written on CI must parse on a developer machine too.
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    # json.JSONDecodeError is the only error this read+parse can raise that the caller
    # can act on (a manifest written by hand or by a broken tool). Wrap it so the caller
    # never has to import the json module just to catch our errors; chain with "from e"
    # so the original position (line/column) stays in the traceback.
    except json.JSONDecodeError as e:
        raise ArtifactError(f"Invalid manifest at {manifest_path}") from e

    # A JSON document can be any JSON value: list, string, number, true/false, null.
    # The rest of the code indexes it like an object with keys, so reject anything else
    # here rather than fail later with a confusing AttributeError or KeyError.
    if not isinstance(doc, dict):
        raise ArtifactError(f"Manifest at {manifest_path} is not a JSON object")
    return doc


def _validate_manifest_document(doc: dict[str, Any], path: Path) -> None:
    """Validate the manifest structure and payload paths.

    The manifest is a JSON document that describes an artifact: a version tag plus
    the list of payload files that make up the artifact.

    Args:
        doc: Parsed manifest contents. Expected shape:
            {"schema_version": <str>, "payload": [{"path": <str>, ...}, ...]}.
        path: Directory that holds manifest.json; used only to build error messages.

    Raises:
        ArtifactError: If a required top-level key is missing, the schema version is
            unsupported, or a payload entry points outside the artifact directory.
    """
    manifest_path = path / "manifest.json"
    # Both keys are mandatory: "schema_version" tells us how to interpret the
    # document, "payload" lists the files the artifact ships. Either one missing
    # means the file is not a manifest at all, so we fail before touching the payload.
    if "schema_version" not in doc or "payload" not in doc:
        raise ArtifactError(f"Invalid manifest at {manifest_path}")

    # Reject manifests written by a future (or unknown) schema before we
    # interpret any other field with the current rules.
    check_schema_version(doc["schema_version"])
    # Every payload entry must name a file that lives inside the artifact
    # directory; reading=True asks the path check to run in read mode, i.e. the
    # target is expected to already exist rather than be created.
    for item in doc["payload"]:
        _validate_payload_path(item["path"], reading=True)


def _verify_payload_files(doc: dict[str, Any], path: Path) -> None:
    """Verify that every payload file exists and matches its recorded hash.

    A "payload" is a manifest entry: a document (here `doc`) that was serialised alongside
    the files it references, so a later reader can detect tampering or truncation. Each
    entry in `doc["payload"]` stores the file's POSIX path relative to `path` plus the
    SHA-256 digest the file had when the manifest was written. Recomputing the digest now
    and comparing it to the recorded one answers "is this still the exact same bytes?":
    any single flipped bit changes the hash, so a mismatch means corruption or tampering.

    Raises:
        ArtifactIntegrityError: if a referenced file is missing, or its content no longer
            hashes to the recorded digest.
    """
    # Paths in the manifest are relative, so they are joined onto the artifact root `path`
    # to obtain the file location on disk. Iterating in manifest order means the first
    # broken entry is the one reported, which keeps failures deterministic across runs.
    for item in doc["payload"]:
        file_path = path / item["path"]
        # Existence is checked before hashing because hashing a missing file would raise
        # FileNotFoundError, whose message would not say which manifest entry is at fault.
        if not file_path.exists():
            raise ArtifactIntegrityError(f"Payload file not found: {file_path}")
        # Full read per file, bounded by file size; `item["sha256"]` is the lowercase hex
        # digest recorded at write time, compared as a string against the freshly computed one.
        if sha256_file(file_path) != item["sha256"]:
            raise ArtifactIntegrityError(f"Payload file integrity check failed: {file_path}")
