"""Policy file loader, schema validation, and digest verification (Phase 2, #46).

Loads and verifies JSON write policy files against schemas/write-policy.schema.json
and checks SHA-256 digest integrity to prevent tampering.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from crosscut_gateway.interfaces import WritePolicy
from crosscut_gateway.policy import PolicyError, policy_from_dict


def canonical_bytes(data: dict[str, Any]) -> bytes:
    """Return deterministic canonical UTF-8 bytes for a JSON dictionary.

    Keys are lexicographically sorted with compact separators (',', ':')
    and unescaped UTF-8 characters.
    """
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def policy_digest(data: dict[str, Any]) -> str:
    """Return the SHA-256 hex digest of the canonical JSON representation."""
    return hashlib.sha256(canonical_bytes(data)).hexdigest()


def _find_schema_path() -> Path:
    """Locate schemas/write-policy.schema.json by traversing parent directories."""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / "schemas" / "write-policy.schema.json"
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    raise PolicyError("Schema file schemas/write-policy.schema.json not found")


def _read_and_parse_json(path: Path) -> dict[str, Any]:
    """Read path and parse JSON content, mapping any I/O or syntax error to PolicyError."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise PolicyError(f"Cannot read policy file {path}: {err}") from err
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as err:
        raise PolicyError(f"Invalid JSON in policy file {path}: {err}") from err
    if not isinstance(data, dict):
        raise PolicyError(f"Policy file {path} must contain a JSON object")
    return data


def _validate_schema(data: dict[str, Any]) -> None:
    """Validate data against write-policy.schema.json with lazy jsonschema import."""
    from jsonschema import Draft202012Validator  # lazy import per requirements

    schema_path = _find_schema_path()
    try:
        schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema_doc)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    except Exception as err:
        raise PolicyError(f"Schema loading or validation failed: {err}") from err
    if errors:
        issues = "; ".join(f"{list(e.path)}: {e.message}" for e in errors)
        raise PolicyError(f"Policy schema validation failed: {issues}")


def _verify_digest(digest: str, expected_digest: str | None) -> None:
    """Compare computed digest with expected digest, raising PolicyError on mismatch."""
    if expected_digest is None:
        return
    expected = expected_digest.strip().lower()
    if digest.lower() != expected:
        msg = f"policy digest mismatch: hash {digest} does not match expected {expected}"
        raise PolicyError(msg)


def load_policy_file(
    path: Path,
    expected_digest: str | None = None,
) -> tuple[dict[str, WritePolicy], str, str]:
    """Load, validate against schema, verify digest, and parse write policies.

    Parameters
    ----------
    path: Path to the JSON policy file on disk.
    expected_digest: Optional expected SHA-256 hex digest for tamper prevention.

    Returns
    -------
    tuple of (targets mapping, gateway mode string, computed SHA-256 digest hex).
    """
    data = _read_and_parse_json(path)
    _validate_schema(data)
    digest = policy_digest(data)
    _verify_digest(digest, expected_digest)
    targets = policy_from_dict(data)
    mode = str(data["mode"])
    return targets, mode, digest
