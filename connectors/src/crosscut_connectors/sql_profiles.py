"""SQL historian profiles: vendor-specific SQL templates loaded from JSON (Phase 5, #50).

A profile is data, not code. It holds the SELECT templates that turn one vendor historian's
tables into Crosscut's browse, metadata, history and latest-value shapes, plus the map from
vendor quality codes to LiveValue quality (0 good, 1 uncertain, 2 bad). Keeping it in JSON
lets a site correct a table or column name without changing the connector.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from crosscut_connectors.base import ConnectorError

SQL_PROFILES_DIR = Path(__file__).with_name("sql_profiles")
PROFILE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "schemas" / "sql-historian-profile.schema.json"
)
PROFILE_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")

QUALITY_GOOD = 0
QUALITY_UNCERTAIN = 1
QUALITY_BAD = 2
QUALITY_BY_NAME = {
    "good": QUALITY_GOOD,
    "uncertain": QUALITY_UNCERTAIN,
    "bad": QUALITY_BAD,
}
QUALITY_NAMES = ("good", "uncertain", "bad")
HISTORY_COLUMNS = ("timestamp", "value", "quality")


class ProfileError(ConnectorError):
    """A historian profile is missing, malformed or internally inconsistent."""


@dataclass(frozen=True)
class SqlQuery:
    """A SELECT template and the 0-based column positions of the values it returns."""

    sql: str
    columns: Mapping[str, int]
    period_sql: str | None = None


@dataclass(frozen=True)
class QualityMap:
    """Inclusive vendor code ranges mapped to LiveValue quality, plus the fallback."""

    ranges: tuple[tuple[int, int, int], ...]
    default: int


@dataclass(frozen=True)
class HistorianProfile:
    """One vendor's historian SQL and quality conventions."""

    name: str
    vendor: str
    description: str
    unverified: tuple[str, ...]
    quality: QualityMap
    browse: SqlQuery
    metadata: SqlQuery
    history: SqlQuery
    latest: SqlQuery


def available_profiles() -> list[str]:
    """Names of the profiles shipped in ``sql_profiles/``, sorted."""
    return sorted(path.stem for path in SQL_PROFILES_DIR.glob("*.json"))


def load_profile(name: str) -> HistorianProfile:
    """Load and validate the shipped profile ``name``.

    Raises ProfileError when the name is not a plain file stem or the file is invalid.
    """
    if not PROFILE_NAME_PATTERN.fullmatch(name):
        raise ProfileError(f"invalid SQL historian profile name: {name!r}")
    path = SQL_PROFILES_DIR / f"{name}.json"
    if not path.is_file():
        raise ProfileError(
            f"unknown SQL historian profile: {name!r} (have {available_profiles()})"
        )
    return load_profile_file(path)


def load_profile_file(path: Path) -> HistorianProfile:
    """Load and validate one profile JSON file; ProfileError lists every problem."""
    document = _read_document(path)
    problems = profile_problems(document)
    if problems:
        raise ProfileError(f"{path.name}: " + "; ".join(problems))
    return _build_profile(document)


def profile_problems(document: Mapping[str, Any]) -> list[str]:
    """Schema and cross-field problems of one profile document; empty when valid."""
    schema = json.loads(PROFILE_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    problems = [f"{_location(error.absolute_path)}: {error.message}" for error in errors]
    return problems or _semantic_problems(document)


def map_quality(quality_map: QualityMap, code: Any) -> int:
    """Map a vendor quality code to LiveValue quality (0 good, 1 uncertain, 2 bad).

    A NULL or unknown code becomes ``quality_map.default``; every shipped profile sets
    that fallback to bad, because a value nobody can classify must not look trustworthy.
    """
    if code is None:
        return quality_map.default
    for low, high, live_quality in quality_map.ranges:
        if low <= int(code) <= high:
            return live_quality
    return quality_map.default


def _read_document(path: Path) -> dict[str, Any]:
    """Read one profile file as a JSON object; ProfileError explains a bad file."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProfileError(f"profile file not found: {path}") from None
    except json.JSONDecodeError as error:
        raise ProfileError(f"{path.name} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise ProfileError(f"{path.name} must hold a JSON object")
    return document


def _semantic_problems(document: Mapping[str, Any]) -> list[str]:
    """Checks a JSON Schema cannot express; the document already matches the schema."""
    problems = _quality_overlaps(document["quality"])
    problems += _missing_columns(document["browse"], "browse", ("tag",))
    problems += _missing_columns(document["metadata"], "metadata", ("description",))
    for name in ("history", "latest"):
        problems += _missing_columns(document[name], name, HISTORY_COLUMNS)
    return problems


def _quality_overlaps(quality: Mapping[str, Any]) -> list[str]:
    """No vendor code may belong to two categories, and min must not exceed max."""
    claimed: dict[int, str] = {}
    problems: list[str] = []
    for category in QUALITY_NAMES:
        for interval in quality[category]:
            problems += _claim_range(claimed, category, interval)
    return problems


def _claim_range(claimed: dict[int, str], category: str, interval: Mapping[str, int]) -> list[str]:
    """Claim every code of one range for ``category``; report bad or repeated ranges."""
    low, high = int(interval["min"]), int(interval["max"])
    if low > high:
        return [f"quality.{category}: min {low} is above max {high}"]
    problems = []
    for code in range(low, high + 1):
        if code in claimed:
            problems.append(f"quality.{category}: code {code} already claimed by {claimed[code]}")
        else:
            claimed[code] = category
    return problems


def _missing_columns(
    query: Mapping[str, Any], name: str, required: tuple[str, ...]
) -> list[str]:
    """One problem per required column the query's column map does not name."""
    columns = query["columns"]
    return [f"{name}.columns: missing {column!r}" for column in required if column not in columns]


def _build_profile(document: Mapping[str, Any]) -> HistorianProfile:
    """Turn a validated profile document into frozen dataclasses."""
    history = document["history"]
    return HistorianProfile(
        name=str(document["profile"]),
        vendor=str(document["vendor"]),
        description=str(document["description"]),
        unverified=tuple(str(item) for item in document.get("unverified", [])),
        quality=_build_quality(document["quality"]),
        browse=_build_query(document["browse"]),
        metadata=_build_query(document["metadata"]),
        history=_build_query(history, history.get("period_sql")),
        latest=_build_query(document["latest"]),
    )


def _build_quality(section: Mapping[str, Any]) -> QualityMap:
    """Flatten the named quality ranges into (low, high, LiveValue quality) tuples."""
    ranges: list[tuple[int, int, int]] = []
    for category in QUALITY_NAMES:
        mapped = QUALITY_BY_NAME[category]
        ranges += [(int(item["min"]), int(item["max"]), mapped) for item in section[category]]
    return QualityMap(tuple(ranges), QUALITY_BY_NAME[str(section["default"])])


def _build_query(section: Mapping[str, Any], period_sql: Any = None) -> SqlQuery:
    """Build one SQL template; ``period_sql`` is only set for history queries."""
    return SqlQuery(
        sql=str(section["sql"]),
        columns={str(name): int(index) for name, index in section["columns"].items()},
        period_sql=str(period_sql) if period_sql else None,
    )


def _location(path: Any) -> str:
    """A dotted location such as ``history.columns.quality`` ("profile" at the root)."""
    return ".".join(str(part) for part in path) or "profile"
