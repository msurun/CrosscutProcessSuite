"""Version history of a saved rule base: save a snapshot, list it, load it and diff two rule bases.

Snapshots live under ``<user_dir>/_history/<system_id>/<version_id>.json``. A version id is the UTC
instant of the save, formatted so that sorting the ids sorts the snapshots by time.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crosscut_fuzzy.library import check_id
from crosscut_fuzzy.model import FuzzyModelError

HISTORY_DIR_NAME = "_history"
VERSION_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{12}Z$")
VERSION_ID_FORMAT = "%Y%m%dT%H%M%S%fZ"

DEFAULT_OPERATOR = "and"
DEFAULT_WEIGHT = 1.0
DEFAULT_ENABLED = True

OPTIONAL_RULE_FIELDS = ("operator", "weight", "enabled")


def save_version(
    system_id: str, document: Mapping[str, Any], user_dir: Path, *, now: datetime
) -> str:
    """Write ``document`` as the newest version of ``system_id`` and return its version id.

    ``now`` is the instant to stamp; callers pass it explicitly so the clock lives outside the
    storage layer.

    Raises:
        FuzzyModelError: when the id is not a plain identifier.
    """
    check_id(system_id)
    version_id = format_version_id(now)
    directory = _history_dir(system_id, user_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{version_id}.json").write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf8"
    )
    return version_id


def format_version_id(moment: datetime) -> str:
    """The version id of ``moment``, taken in UTC (an aware datetime is converted first)."""
    return moment.astimezone(UTC).strftime(VERSION_ID_FORMAT)


def list_versions(system_id: str, user_dir: Path) -> list[str]:
    """Version ids of ``system_id``, newest first; empty when it has no history yet."""
    check_id(system_id)
    directory = _history_dir(system_id, user_dir)
    if not directory.exists():
        return []
    return sorted((path.stem for path in directory.glob("*.json")), reverse=True)


def load_version(system_id: str, version_id: str, user_dir: Path) -> dict[str, Any]:
    """The saved document of one version.

    Raises:
        FileNotFoundError: when that version does not exist.
    """
    check_id(system_id)
    check_version_id(version_id)
    path = _history_dir(system_id, user_dir) / f"{version_id}.json"
    if not path.exists():
        raise FileNotFoundError(version_id)
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf8"))
    return document


def check_version_id(version_id: str) -> str:
    """The version id when it looks like one.

    Raises:
        FuzzyModelError: for anything that could be a path or is not a well-formed id.
    """
    if not VERSION_ID_PATTERN.match(version_id):
        raise FuzzyModelError(f"invalid version id: {version_id!r}")
    return version_id


def diff_documents(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Differences between two rule bases, as a list of change dictionaries sorted by code.

    Each change is a small dict such as
    ``{"code": "term_added", "variable": "temp", "term": "cold"}``.
    An empty list means the two documents describe the same system.
    """
    changes = _variable_changes(old, new) + _rule_changes(old, new)
    return sorted(changes, key=_sort_key)


def _history_dir(system_id: str, user_dir: Path) -> Path:
    """Directory holding the versions of one system."""
    return user_dir / HISTORY_DIR_NAME / system_id


def _variables_by_id(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """All variables of a document keyed by id; inputs and outputs are compared together."""
    variables = list(document.get("inputs", ())) + list(document.get("outputs", ()))
    return {str(variable["id"]): variable for variable in variables}


def _variable_changes(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Range and term differences of every variable present in either document."""
    old_variables = _variables_by_id(old)
    new_variables = _variables_by_id(new)
    changes: list[dict[str, Any]] = []
    for variable_id in set(old_variables) | set(new_variables):
        before = old_variables.get(variable_id)
        after = new_variables.get(variable_id)
        if before is None:
            changes.append({"code": "variable_added", "variable": variable_id})
        elif after is None:
            changes.append({"code": "variable_removed", "variable": variable_id})
        else:
            changes.extend(_sorted_variable_changes(variable_id, before, after))
    return changes


def _sorted_variable_changes(
    variable_id: str, before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    """The changes of one variable that still exists: its range, then its terms."""
    changes: list[dict[str, Any]] = []
    old_range = [before.get("low", 0.0), before.get("high", 1.0)]
    new_range = [after.get("low", 0.0), after.get("high", 1.0)]
    if old_range != new_range:
        changes.append(
            {"code": "range_changed", "variable": variable_id, "old": old_range, "new": new_range}
        )
    changes.extend(_term_changes(variable_id, before.get("terms", ()), after.get("terms", ())))
    return changes


def _term_changes(variable_id: str, old_terms: Any, new_terms: Any) -> list[dict[str, Any]]:
    """Added, removed and changed terms of one variable, matched by term name."""
    old_by_name = {term["name"]: term for term in old_terms}
    new_by_name = {term["name"]: term for term in new_terms}
    changes = _added_and_removed_terms(variable_id, old_by_name, new_by_name)
    for name, term in new_by_name.items():
        if name in old_by_name and _shape_of(old_by_name[name]) != _shape_of(term):
            changes.append(
                {
                    "code": "term_changed",
                    "variable": variable_id,
                    "term": name,
                    "old": _shape_of(old_by_name[name]),
                    "new": _shape_of(term),
                }
            )
    return changes


def _added_and_removed_terms(
    variable_id: str, old_by_name: dict[str, Any], new_by_name: dict[str, Any]
) -> list[dict[str, Any]]:
    """Terms that exist in only one of the two versions of a variable."""
    changes: list[dict[str, Any]] = []
    for name in old_by_name:
        if name not in new_by_name:
            changes.append({"code": "term_removed", "variable": variable_id, "term": name})
    for name in new_by_name:
        if name not in old_by_name:
            changes.append({"code": "term_added", "variable": variable_id, "term": name})
    return changes


def _shape_of(term: Mapping[str, Any]) -> dict[str, Any]:
    """The part of a term a diff compares: its shape name and its parameters."""
    return {"shape": term["shape"], "params": list(term.get("params", ()))}


def _rules_by_id(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """All rules of a document keyed by id."""
    return {str(rule["id"]): rule for rule in document.get("rules", ())}


def _rule_changes(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Added, removed and changed rules, matched by rule id."""
    old_rules = _rules_by_id(old)
    new_rules = _rules_by_id(new)
    changes: list[dict[str, Any]] = []
    for rule_id in set(old_rules) | set(new_rules):
        change = _rule_change(rule_id, old_rules.get(rule_id), new_rules.get(rule_id))
        if change is not None:
            changes.append(change)
    return changes


def _rule_change(
    rule_id: str, before: Mapping[str, Any] | None, after: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """The change of one rule id: added, removed or changed; None when it is unchanged."""
    if before is None:
        return {"code": "rule_added", "rule": rule_id}
    if after is None:
        return {"code": "rule_removed", "rule": rule_id}
    changed_fields = _changed_rule_fields(before, after)
    if not changed_fields:
        return None
    return {"code": "rule_changed", "rule": rule_id, "fields": changed_fields}


def _changed_rule_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    """Names of the rule fields that differ, with missing optional fields read as their default."""
    fields = [field for field in ("if", "then") if before.get(field) != after.get(field)]
    fields += [
        field
        for field in OPTIONAL_RULE_FIELDS
        if _optional_field(before, field) != _optional_field(after, field)
    ]
    return fields


def _optional_field(rule: Mapping[str, Any], field: str) -> Any:
    """The value of an optional rule field, or its default when the document leaves it out."""
    defaults = {"operator": DEFAULT_OPERATOR, "weight": DEFAULT_WEIGHT, "enabled": DEFAULT_ENABLED}
    return rule.get(field, defaults[field])


def _sort_key(change: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """Sort changes by code, then by the variable, term and rule they mention."""
    return (
        str(change["code"]),
        str(change.get("variable", "")),
        str(change.get("term", "")),
        str(change.get("rule", "")),
    )
