"""Tag fingerprints and the tags a dependent uses: the pure core of dependency tracking (#166).

A fingerprint is what a config, model or job silently assumes about a tag: its source address,
unit, role(s) and valid range. Comparing the fingerprint a dependent was built on with the
catalogue now in force tells whether it still runs on the same tag; the diff names the change
(removed, remapped, unit changed, role moved, range changed, rebound). No file access here.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

Doc = Mapping[str, Any]
Fingerprint = dict[str, Any]
LOOP_ROLES = ("pv", "sp", "out", "mode")
KINDS = ("removed", "remapped", "unit_changed", "role_moved", "range_changed", "rebound")


def _roles(site: Doc) -> dict[str, set[str]]:
    """Roles per tag id as ``role@owner`` strings: signals, loop members, controller variables."""
    roles: dict[str, set[str]] = defaultdict(set)
    for signal in site.get("signals", []):
        roles[signal["tag"]].add(f"{signal['role']}@{signal.get('loop', '')}")
    for loop in site.get("loops", []):
        for role in LOOP_ROLES:
            if loop.get(role):
                roles[loop[role]].add(f"{role}@{loop['id']}")
    for controller in site.get("controllers", []):
        for variable in controller.get("variables", []):
            tag = variable.get("binding", {}).get("tag")
            if tag:
                roles[tag].add(f"{variable['role']}@{controller['id']}")
    return roles


def _range(tag: Doc) -> list[float | None] | None:
    """The valid range of a tag as ``[low, high]``, None when it has none."""
    limits = tag.get("range")
    if not limits:
        return None
    return [limits.get("low"), limits.get("high")]


def tag_fingerprints(site: Doc) -> dict[str, Fingerprint]:
    """The fingerprint of every tag of the catalogue: id, source, address, unit, roles, range."""
    roles = _roles(site)
    return {
        tag["id"]: {
            "id": tag["id"],
            "source": tag.get("source"),
            "address": tag.get("address"),
            "unit": tag.get("unit", ""),
            "roles": sorted(roles.get(tag["id"], ())),
            "range": _range(tag),
        }
        for tag in site.get("tags", [])
    }


def controller_tag_ids(controller: Doc, loops: Iterable[Doc]) -> set[str]:
    """Tags a controller reads or writes: its CV/DV/ICV tags and the PV/SP/OUT of its MV loops."""
    wanted = {v["binding"]["loop"] for v in controller.get("variables", []) if v["role"] == "MV"}
    tags = {
        v["binding"]["tag"] for v in controller.get("variables", []) if "tag" in v["binding"]
    }
    for loop in loops:
        if loop["id"] in wanted:
            tags.update(str(loop[key]) for key in ("pv", "sp", "out") if loop.get(key))
    return tags


def _loop_tags(loop_ids: Iterable[str], site: Doc) -> set[str]:
    """PV, SP, OUT and mode tags of the named loops (unknown loops add nothing)."""
    wanted = set(loop_ids)
    return {
        str(loop[key]) for loop in site.get("loops", []) if loop["id"] in wanted
        for key in LOOP_ROLES if loop.get(key)
    }


def _equipment_tags(equipment_ids: Iterable[str], site: Doc) -> set[str]:
    """Signal and running-flag tags of the named equipment entries."""
    wanted = set(equipment_ids)
    tags: set[str] = set()
    for entry in site.get("equipment", []):
        if entry["id"] in wanted:
            tags.update(signal["tag"] for signal in entry.get("signals", []))
            if entry.get("running"):
                tags.add(entry["running"]["tag"])
    return tags


def job_tag_ids(job: Doc, site: Doc) -> set[str]:
    """The tags a runtime job uses now, resolved through the catalogue in force."""
    kind = job.get("kind")
    if kind in ("loop_kpi", "tuning_review"):
        return _loop_tags(job.get("loops", []), site)
    if kind == "anomaly_scan":
        return set(job.get("tags", []))
    if kind == "equipment_scan":
        return _equipment_tags(job.get("equipment", []), site)
    if kind == "controller":
        entry = next(
            (c for c in site.get("controllers", []) if c["id"] == job.get("controller")), {}
        )
        return controller_tag_ids(entry, site.get("loops", [])) if entry else set()
    return set()


def _changes(old: Fingerprint, new: Fingerprint) -> list[tuple[str, str]]:
    """``(kind, detail)`` pairs for one tag whose fingerprint moved."""
    found: list[tuple[str, str]] = []
    if (old["source"], old["address"]) != (new["source"], new["address"]):
        found.append(("remapped", f"{old['source']}:{old['address']} -> "
                                  f"{new['source']}:{new['address']}"))
    if old["unit"] != new["unit"]:
        found.append(("unit_changed", f"{old['unit']!r} -> {new['unit']!r}"))
    if old["roles"] != new["roles"]:
        found.append(("role_moved", f"{', '.join(old['roles']) or '-'} -> "
                                    f"{', '.join(new['roles']) or '-'}"))
    if old["range"] != new["range"]:
        found.append(("range_changed", f"{old['range']} -> {new['range']}"))
    return found


def diff_fingerprints(
    baseline: Mapping[str, Fingerprint], current: Mapping[str, Fingerprint],
    used_now: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    """Reasons a dependent built on ``baseline`` is stale against ``current``.

    Each tag of the baseline must still exist and match. ``used_now`` (jobs only) are the tags the
    dependent resolves to today; an existing one that was not in the baseline is a ``rebound`` (a
    loop was re-pointed at another tag). Tags missing from the catalogue are the validator's job.
    """
    reasons: list[dict[str, str]] = []
    for tag in sorted(baseline):
        new = current.get(tag)
        if new is None:
            reasons.append({"tag": tag, "kind": "removed", "detail": "tag removed from catalogue"})
            continue
        for kind, detail in _changes(baseline[tag], new):
            reasons.append({"tag": tag, "kind": kind, "detail": detail})
    for tag in sorted((set(used_now or ()) - set(baseline)) & set(current)):
        reasons.append({"tag": tag, "kind": "rebound", "detail": "not built on this tag"})
    return reasons


def reason_text(reasons: Iterable[Mapping[str, str]]) -> str:
    """One line for a status field: ``stale_dependency: TAG removed; TAG2 remapped (a -> b)``."""
    parts = [f"{r['tag']} {r['kind']} ({r['detail']})" for r in reasons]
    return "stale_dependency: " + "; ".join(parts)
