"""Version history of a saved rule base: save a snapshot, list it, load it and diff two rule bases.

Snapshots live under ``<user_dir>/_history/<system_id>/<version_id>.json``. A version id is the UTC
instant of the save, formatted so that sorting the ids sorts the snapshots by time.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from crosscut_fuzzy.library import check_id
from crosscut_fuzzy.model import FuzzyModelError

HISTORY_DIR_NAME = "_history"
VERSION_ID_PATTERN = re.compile(r"[0-9]{8}T[0-9]{12}Z")
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
    storage layer. When a version with that id already exists (a coarse clock, as on Windows,
    can return the same microsecond twice) the stamp moves forward one microsecond at a time,
    so a save never overwrites an earlier version and the ids still sort by time.

    Raises:
        FuzzyModelError: when the id is not a plain identifier.
    """
    check_id(system_id)
    directory = _history_dir(system_id, user_dir)
    directory.mkdir(parents=True, exist_ok=True)
    version_id = format_version_id(now)
    while (directory / f"{version_id}.json").exists():
        now += timedelta(microseconds=1)
        version_id = format_version_id(now)
    (directory / f"{version_id}.json").write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf8"
    )
    return version_id


def format_version_id(moment: datetime) -> str:
    """The version id of ``moment``, taken in UTC (an aware datetime is converted first)."""
    return moment.astimezone(UTC).strftime(VERSION_ID_FORMAT)


def list_versions(system_id: str, user_dir: Path) -> list[str]:
    """Version ids of ``system_id``, newest first; empty when it has no history yet.

    A "system" is a saved model; every save writes one snapshot file named
    ``<version_id>.json`` into that system's history directory. Version ids are
    timestamps formatted so that lexicographic order equals chronological order,
    which is why a plain string sort is enough to get newest first.
    """
    check_id(system_id)
    # One history directory per system; ``user_dir`` is the root of the user's workspace.
    directory = _history_dir(system_id, user_dir)
    if not directory.exists():
        return []
    # ``path.stem`` drops the ".json" suffix, leaving just the version id.
    # Sorting as text, reversed, is newest first because ids sort chronologically.
    return sorted((path.stem for path in directory.glob("*.json")), reverse=True)


def load_version(system_id: str, version_id: str, user_dir: Path) -> dict[str, Any]:
    """The saved document of one version.

    Each system owns a history directory of versions, one JSON file per version, named after
    the version id.

    Raises:
        FileNotFoundError: when that version does not exist.
    """
    check_id(system_id)
    check_version_id(version_id)

    # History is stored per system inside the user's directory, so the same version id
    # can exist in two systems without clashing.
    path = _history_dir(system_id, user_dir) / f"{version_id}.json"

    # Checked before reading so the caller gets a clear FileNotFoundError naming the
    # version, instead of whatever low-level error read_text would raise.
    if not path.exists():
        raise FileNotFoundError(version_id)

    # The document is the rule base as the user saved it; json.loads gives plain dicts, lists
    # and scalars, so the values are typed Any.
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf8"))
    return document


def check_version_id(version_id: str) -> str:
    """The version id when it looks like one.

    A version id names a stored snapshot. Because it becomes a file name, it must have exactly
    the form produced by ``format_version_id`` (``YYYYMMDDTHHMMSSffffffZ``, UTC) and can
    therefore never be a path.

    Args:
        version_id: The candidate id, as received from a request.

    Returns:
        The same string, unchanged, once it is known to be well formed.

    Raises:
        FuzzyModelError: for anything that could be a path or is not a
            well-formed id (empty, contains a slash, any other format).
    """
    # fullmatch() rejects a value that merely contains a valid id somewhere; ``$`` alone would
    # also accept a trailing newline.
    if not VERSION_ID_PATTERN.fullmatch(version_id):
        raise FuzzyModelError(f"invalid version id: {version_id!r}")
    return version_id


def diff_documents(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Differences between two rule bases, as a list of change dictionaries sorted by code.

    A *rule base* is a fuzzy system: named variables (each split into linguistic
    terms such as "cold", "warm", "hot") plus the rules that connect them.

    Each change is a small dict such as
    ``{"code": "term_added", "variable": "temp", "term": "cold"}``.
    The "code" field says *what kind* of change happened and doubles as the
    sort key, so callers can group changes by prefix ("rule_*", "term_*", ...).
    An empty list means the two documents describe the same system.

    Returns:
        All changes from ``old`` to ``new``, sorted by ``_sort_key``. The diff is directed: a
        rule removed going old -> new shows up as added when the arguments are swapped.
    """
    # Variable changes and rule changes are computed separately, then concatenated before sorting by
    # _sort_key.
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
    """Range and term differences of every variable present in either document.

    A "document" is a rule base as saved JSON: input and output variables (id, low, high,
    terms) plus rules. Inputs and outputs are compared together, matched by variable id.

    Returns a list of change records, one dict per change. Each record has a
    "code" key whose value tells which change happened:
      * "variable_added"   - present only in the new document, has "variable"
      * "variable_removed" - present only in the old document, has "variable"
      * "range_changed"    - [low, high] differs; also carries "old" and "new"
      * "term_added" / "term_removed" / "term_changed" - from the terms of the variable
    The last two groups are produced by `_sorted_variable_changes`.
    """
    old_variables = _variables_by_id(old)
    new_variables = _variables_by_id(new)
    changes: list[dict[str, Any]] = []

    # Union of the two id sets, so each variable is visited once whether it is only in the old
    # document, only in the new one, or in both.
    for variable_id in set(old_variables) | set(new_variables):
        before = old_variables.get(variable_id)
        after = new_variables.get(variable_id)

        if before is None:
            changes.append({"code": "variable_added", "variable": variable_id})
        elif after is None:
            changes.append({"code": "variable_removed", "variable": variable_id})
        else:
            # Same variable in both revisions: compare its range and terms.
            changes.extend(_sorted_variable_changes(variable_id, before, after))
    return changes


def _sorted_variable_changes(
    variable_id: str, before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    """The changes of one variable that still exists: its range, then its terms.

    A fuzzy variable is defined by two things: its universe of discourse -- the closed
    interval [low, high] its membership degree is plotted over -- and its terms (the
    membership functions such as "cold" or "hot") that partition that universe.

    `before` and `after` are the variable's serialised definitions, taken from two
    successive versions of the model. Returned is a list of change records, ordered so
    that the range change (if any) comes first and the term changes follow, because a
    reader should know the universe before reading about its terms.

    Raises nothing: a missing key falls back to the defaults below, so an older
    definition that predates a key is still comparable.
    """
    changes: list[dict[str, Any]] = []
    # A universe of discourse is the interval over which a variable's membership functions
    # are evaluated; low and high are both in the variable's own unit. Defaults describe the
    # normalised universe [0.0, 1.0] used when a definition omits the bounds.
    old_range = [before.get("low", 0.0), before.get("high", 1.0)]
    new_range = [after.get("low", 0.0), after.get("high", 1.0)]
    # Compare as whole lists, so that swapping low and high counts as a change even when
    # the pair of numbers is the same.
    if old_range != new_range:
        changes.append(
            {"code": "range_changed", "variable": variable_id, "old": old_range, "new": new_range}
        )
    # Terms are the named membership functions of this variable; each one maps a value of
    # the universe to a membership degree in [0.0, 1.0].
    changes.extend(_term_changes(variable_id, before.get("terms", ()), after.get("terms", ())))
    return changes


def _term_changes(variable_id: str, old_terms: Any, new_terms: Any) -> list[dict[str, Any]]:
    """Added, removed and changed terms of one variable, matched by term name.

    A "term" is a fuzzy set of the variable such as "cold" or "hot" (shape plus parameters).
    Terms are matched between the old and the new version by their name, because the name is
    the only stable identity: the shape and its parameters may both change.

    Returns one change dict per added term, per removed term and per term whose shape
    or parameters differ between the two versions. A term that is identical in both versions
    produces no dict.
    """
    # Index both term lists by name so a lookup by name costs O(1) instead of a
    # linear scan. Invariant: term names are unique inside one model version, so the
    # dict has exactly one entry per term and no entry is lost to a collision.
    old_by_name = {term["name"]: term for term in old_terms}
    new_by_name = {term["name"]: term for term in new_terms}

    # Names present on only one side cannot be compared, so they are reported here as
    # added or removed; the loop below only handles names present on both sides.
    changes = _added_and_removed_terms(variable_id, old_by_name, new_by_name)

    # Names in both versions: same name, but possibly a different shape and/or parameters.
    # We only iterate over the new terms, because every shared name appears in new_by_name
    # exactly once; the corresponding old term is looked up below.
    for name, term in new_by_name.items():
        # 'name in old_by_name' keeps this to shared names; _shape_of returns the comparable
        # (shape, params) pair used as the term's fingerprint.
        if name in old_by_name and _shape_of(old_by_name[name]) != _shape_of(term):
            changes.append(
                {
                    "code": "term_changed",
                    "variable": variable_id,
                    "term": name,
                    # Both shapes are kept so the caller can show a before/after diff.
                    "old": _shape_of(old_by_name[name]),
                    "new": _shape_of(term),
                }
            )
    return changes


def _added_and_removed_terms(
    variable_id: str, old_by_name: dict[str, Any], new_by_name: dict[str, Any]
) -> list[dict[str, Any]]:
    """Report the terms (fuzzy sets) that only one version of a variable has.

    Both mappings are keyed by term name, so the comparison is a pair of set differences.

    Returns one change dict per term, with keys "code", "variable" and "term".
    The order is: all removals first, then all additions.
    """
    changes: list[dict[str, Any]] = []
    # Terms present in the old version only: each one is a removal.
    for name in old_by_name:
        if name not in new_by_name:
            changes.append({"code": "term_removed", "variable": variable_id, "term": name})
    # Terms present in the new version only: each one is an addition.
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
    """Added, removed and changed rules, matched by rule id.

    The rules of ``old`` and ``new`` are matched by their "id". Each returned change is a dict
    describing one rule id: it is present only when the rule was added, removed, or its content
    differs. A rule that is identical on both sides yields no entry.

    Returns:
        One dict per added/removed/modified rule, in no particular order (a set is iterated).
    """
    # Index each collection by rule id so a rule can be looked up in O(1) instead of scanning.
    old_rules = _rules_by_id(old)
    new_rules = _rules_by_id(new)
    changes: list[dict[str, Any]] = []
    # Union of the two rule-id sets, so each id is visited exactly once whether it is only
    # in the old rules, only in the new rules, or in both.
    for rule_id in set(old_rules) | set(new_rules):
        # .get returns None when the id is absent on that side, which is exactly the signal
        # _rule_change needs to classify the change; it returns None when nothing changed.
        change = _rule_change(rule_id, old_rules.get(rule_id), new_rules.get(rule_id))
        if change is not None:
            changes.append(change)
    return changes


def _rule_change(
    rule_id: str, before: Mapping[str, Any] | None, after: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """The change of one rule id: added, removed or changed; None when it is unchanged.

    `rule_id` names the rule and the mapping holds its definition ("if", "then", operator,
    weight, enabled). `before` is the rule in the old document, `after` the rule in the new one.
    Either side is `None` when the rule does not exist there, which is how "added" and
    "removed" are told apart from "changed".

    Returns a dict with at least a "code" key ("rule_added", "rule_removed" or "rule_changed")
    and the "rule" id; a change also carries the list of differing field names under "fields".
    Returns None when the rule is present and identical on both sides, so callers can skip it.
    """
    # The rule exists only after the change: it was introduced, so no field comparison is needed.
    if before is None:
        return {"code": "rule_added", "rule": rule_id}
    # The rule exists only before the change: it was dropped, so its fields are irrelevant.
    if after is None:
        return {"code": "rule_removed", "rule": rule_id}
    # Both sides exist, so the rule survived the change and only some fields may differ.
    changed_fields = _changed_rule_fields(before, after)
    # An empty list means every field compares equal: nothing to report, hence None.
    if not changed_fields:
        return None
    return {"code": "rule_changed", "rule": rule_id, "fields": changed_fields}


def _changed_rule_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    """Names of the rule fields that differ, with missing optional fields read as their default.

    A rule has a required condition list ("if"), a required consequent ("then") and optional
    settings (OPTIONAL_RULE_FIELDS: operator, weight, enabled) that may be absent from the JSON.

    Returns the field names whose value changed between the two versions, in a stable order:
    "if" and "then" first, then the optional fields as listed in OPTIONAL_RULE_FIELDS.
    """
    # Required fields: a plain lookup, because absence and a value are already different things.
    fields = [field for field in ("if", "then") if before.get(field) != after.get(field)]
    # Optional fields: route through _optional_field so that "key missing" is compared as the
    # field's default value, not as None. Without it, writing out an optional field that equals
    # its default (e.g. "weight": 1.0) would be reported as a change although nothing changed.
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
    """Build the tuple used to order change records.

    Several change records may share a code, so ties are broken by the variable,
    then the term, then the rule that each record mentions, comparing the string
    forms in that order. Python compares tuples element by element from left to
    right, so one returned tuple is enough to encode the whole priority.

    Returns a 4-tuple ``(code, variable, term, rule)``, all strings, ready to be
    passed to ``sorted(..., key=...)``. Missing optional fields count as the
    empty string, which sorts before any real value.
    """
    return (
        str(change["code"]),
        str(change.get("variable", "")),
        str(change.get("term", "")),
        str(change.get("rule", "")),
    )
