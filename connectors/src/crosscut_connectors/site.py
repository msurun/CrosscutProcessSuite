"""The site catalogue: load, validate and save ``<data root>/_site/site.json``.

The layout is fixed by ``schemas/site.schema.json``. Validation is the JSON Schema plus the
cross-reference checks a schema cannot express (unique ids, known sources, consistent limits;
tag ids, hierarchy and units of the 36b sections live in ``site_refs``).
Nothing here touches a plant: it reads and writes one configuration file.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from crosscut_connectors.site_refs import reference_problems

SITE_FOLDER = "_site"
SITE_FILE = "site.json"
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "site.schema.json"
IMPORT_KEYS = ("missing_codes", "decimal_comma", "delimiter", "time_names")


class SiteError(ValueError):
    """The site file is missing, unreadable or not acceptable."""


def site_path(root: Path) -> Path:
    """Where the site file of a data root lives."""
    return root / SITE_FOLDER / SITE_FILE


def load_site(root: Path) -> dict[str, Any]:
    """Read the site file of a data root as stored (no validation)."""
    path = site_path(root)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SiteError(f"no site file: {path}") from None
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise SiteError(f"site file is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise SiteError("site file must hold a JSON object")
    return document


def validate_site(document: dict[str, Any], schema_path: Path = SCHEMA_PATH) -> list[str]:
    """Problems of a site document, as readable lines; empty when it is acceptable."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    problems = [f"{_where(error.absolute_path)}: {error.message}" for error in errors]
    return problems or _cross_reference_problems(document)


def _where(path: Any) -> str:
    """A dotted location such as ``tags.3.id`` ("site" for the document itself)."""
    return ".".join(str(part) for part in path) or "site"


def _cross_reference_problems(document: dict[str, Any]) -> list[str]:
    """Checks beyond the schema; the document already matches the schema."""
    source_ids = [source["id"] for source in document.get("sources", [])]
    problems = _duplicates("sources", source_ids)
    problems += _duplicates("tags", [tag["id"] for tag in document["tags"]])
    for index, tag in enumerate(document["tags"]):
        problems += _tag_problems(index, tag, set(source_ids))
    problems += _import_problems(document.get("import", {}))
    problems += reference_problems(document)
    return problems


def _duplicates(name: str, ids: list[str]) -> list[str]:
    """One line per id that occurs more than once."""
    counts = Counter(ids)
    return [f"{name}: duplicate id {item!r}" for item in sorted(counts) if counts[item] > 1]


def _tag_problems(index: int, tag: dict[str, Any], source_ids: set[str]) -> list[str]:
    """Unknown source and inverted limits of one tag."""
    where = f"tags.{index}"
    problems = []
    if "source" in tag and tag["source"] not in source_ids:
        problems.append(f"{where}.source: unknown source {tag['source']!r}")
    for key in ("range", "eng_limits"):
        limits = tag.get(key, {})
        if "min" in limits and "max" in limits and limits["min"] > limits["max"]:
            problems.append(f"{where}.{key}: min is above max")
    return problems


def _import_problems(settings: dict[str, Any]) -> list[str]:
    """A decimal comma cannot share the file with a comma delimiter."""
    if settings.get("decimal_comma") and settings.get("delimiter", ",") == ",":
        return ["import.decimal_comma: needs a delimiter other than a comma"]
    return []


def read_settings_from_site(document: dict[str, Any]) -> dict[str, Any]:
    """The import settings stated in the site file, as keyword arguments for ReadSettings.

    Only keys the file states are returned, so the reader's own defaults apply to the rest.
    """
    stated = document.get("import", {})
    settings = {key: stated[key] for key in IMPORT_KEYS if key in stated}
    if "missing_codes" in settings:
        settings["missing_codes"] = tuple(float(code) for code in settings["missing_codes"])
    if "time_names" in settings:
        settings["time_names"] = frozenset(name.lower() for name in settings["time_names"])
    return settings


def save_site(root: Path, document: dict[str, Any]) -> None:
    """Validate and write the site file atomically; SiteError lists the problems."""
    problems = validate_site(document)
    if problems:
        raise SiteError("; ".join(problems))
    path = site_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(temp_name, path)
