"""Structured difference of two site catalogue documents.

Lists whose entries all carry an ``id`` (tags, loops, equipment, controllers, sources, ...)
are compared entry by entry: added ids, removed ids and, per changed entry, the fields whose
value differs (nested values are compared and shown whole). Any other top-level key is
compared by field. The result feeds the Versions view and the publish approval rule.
"""

from __future__ import annotations

from typing import Any

Doc = dict[str, Any]


def _keyed(value: Any) -> dict[str, Doc] | None:
    """The entries of a list of id-carrying objects by id, or None when it is not such a list."""
    if not isinstance(value, list) or not all(isinstance(e, dict) and "id" in e for e in value):
        return None
    return {str(entry["id"]): entry for entry in value}


def _field_changes(before: Doc, after: Doc) -> list[Doc]:
    """The fields (sorted by name) whose value differs; a missing field reads as ``None``."""
    names = sorted(set(before) | set(after))
    return [
        {"field": name, "before": before.get(name), "after": after.get(name)}
        for name in names
        if before.get(name) != after.get(name)
    ]


def _diff_entries(old: dict[str, Doc], new: dict[str, Doc]) -> Doc:
    """Added, removed and changed entries of two id-keyed collections."""
    changed = []
    for entry_id in sorted(set(old) & set(new)):
        fields = _field_changes(old[entry_id], new[entry_id])
        if fields:
            changed.append({"id": entry_id, "fields": fields})
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "changed": changed,
    }


def _diff_section(old: Any, new: Any) -> Doc | None:
    """The difference of one top-level value, or None when it is unchanged."""
    if old == new:
        return None
    old_keyed = _keyed([] if old is None else old)
    new_keyed = _keyed([] if new is None else new)
    if old_keyed is not None and new_keyed is not None:
        return _diff_entries(old_keyed, new_keyed)
    if isinstance(old, dict) and isinstance(new, dict):
        return {"fields": _field_changes(old, new)}
    return {"fields": [{"field": "", "before": old, "after": new}]}


def diff_sites(old: Doc, new: Doc) -> Doc:
    """``{"sections": {name: difference}, "empty": bool}`` between two site documents."""
    sections: Doc = {}
    for name in sorted(set(old) | set(new)):
        section = _diff_section(old.get(name), new.get(name))
        if section is not None:
            sections[name] = section
    return {"sections": sections, "empty": not sections}
