"""Policy file loader, schema validation, and digest verification (Phase 2, #46).

Loads and verifies JSON write policy files against schemas/write-policy.schema.json
and checks SHA-256 digest integrity to prevent tampering.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, NoReturn

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


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object from its pairs, refusing any key that appears twice."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError(f"duplicate key {key!r} in policy JSON")
        result[key] = value
    return result


def _reject_constant(name: str) -> NoReturn:
    """Refuse the non-standard NaN, Infinity and -Infinity JSON tokens."""
    raise PolicyError(f"non-finite number {name} is not allowed in policy JSON")


def _read_and_parse_json(path: Path) -> dict[str, Any]:
    """Read path as UTF-8 (BOM tolerated) and parse strict JSON, mapping failures to PolicyError."""
    try:
        raw_text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as err:
        raise PolicyError(f"Cannot read policy file {path}: {err}") from err
    try:
        data = json.loads(
            raw_text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except PolicyError:
        raise
    except ValueError as err:  # JSONDecodeError and int-conversion limit both subclass ValueError
        raise PolicyError(f"Invalid JSON in policy file {path}: {err}") from err
    if not isinstance(data, dict):
        raise PolicyError(f"Policy file {path} must contain a JSON object")
    return data


def _load_validator_class() -> Any:
    """Import jsonschema's Draft 2020-12 validator lazily, reporting a missing package clearly."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError as err:
        raise PolicyError(f"jsonschema is required to validate policy files: {err}") from err
    return Draft202012Validator


def _validate_schema(data: dict[str, Any]) -> None:
    """Validate data against write-policy.schema.json."""
    validator_class = _load_validator_class()

    schema_path = _find_schema_path()
    try:
        schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = validator_class(schema_doc)
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


def validate_document(data: dict[str, Any]) -> dict[str, WritePolicy]:
    """Validate a parsed policy document against the schema and return its write policies.

    Raises PolicyError on any schema violation or invalid target definition.
    """
    _validate_schema(data)
    return policy_from_dict(data)
