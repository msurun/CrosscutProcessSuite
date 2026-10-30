"""Cross-reference checks of the site catalogue (36b): ids, hierarchy, signals and units.

A JSON Schema cannot say that a tag id used by a loop exists or that the equipment tree has
no cycle. These checks run after the schema passes, so every list and key they read is present.
Each function returns readable lines such as ``loops.2.pv: unknown tag 'X'``.
"""

from __future__ import annotations

from collections import Counter, deque
from typing import Any

Document = dict[str, Any]
LEVELS = {"site": 0, "area": 1, "unit": 2, "equipment": 3}
LOOP_SLOTS = ("pv", "sp", "out", "mode")  # signal roles that fill a slot of loops[]
LOOP_ROLES = frozenset((*LOOP_SLOTS, "fb"))  # signal roles that need a loop
SECTIONS = ("equipment", "loops", "labs", "modes")


def reference_problems(document: Document) -> list[str]:
    """All 36b problems of a document that already matches the schema."""
    tags = {tag["id"]: tag for tag in document["tags"]}
    loop_ids = {loop["id"] for loop in document.get("loops", [])}
    conversions = document.get("units", {}).get("conversions", [])
    problems = [line for name in SECTIONS for line in _duplicate_ids(document, name)]
    problems += _equipment_problems(document.get("equipment", []), tags)
    problems += _loop_problems(document.get("loops", []), tags, loop_ids, conversions)
    problems += _signal_problems(document, tags, loop_ids)
    problems += _lab_problems(document.get("labs", []), tags, conversions)
    problems += _mode_problems(document.get("modes", []), tags, document.get("equipment", []))
    return problems


def convertible(source: str, target: str, conversions: list[Document]) -> bool:
    """True when two units are equal or linked by a chain of conversions (either direction)."""
    if source == target:
        return True
    neighbours: dict[str, set[str]] = {}
    for item in conversions:
        neighbours.setdefault(item["from"], set()).add(item["to"])
        neighbours.setdefault(item["to"], set()).add(item["from"])
    seen, queue = {source}, deque([source])
    while queue:
        for unit in neighbours.get(queue.popleft(), ()):
            if unit == target:
                return True
            if unit not in seen:
                seen.add(unit)
                queue.append(unit)
    return False


def _duplicate_ids(document: Document, name: str) -> list[str]:
    """One line per id used twice in a section."""
    counts = Counter(entry["id"] for entry in document.get(name, []))
    return [f"{name}: duplicate id {item!r}" for item in sorted(counts) if counts[item] > 1]


def _unknown(where: str, ids: Any, known: Any) -> list[str]:
    """One line per id that is not in ``known``."""
    return [f"{where}: unknown tag {item!r}" for item in ids if item not in known]


def _equipment_problems(entries: list[Document], tags: dict[str, Document]) -> list[str]:
    """Parents, level order, cycles and tag attachment of the equipment hierarchy."""
    by_id = {entry["id"]: entry for entry in entries}
    problems: list[str] = []
    owner: dict[str, str] = {}
    for index, entry in enumerate(entries):
        where = f"equipment.{index}"
        problems += _parent_problems(where, entry, by_id)
        problems += _unknown(f"{where}.tags", entry.get("tags", []), tags)
        for tag_id in entry.get("tags", []):
            if tag_id in owner and owner[tag_id] != entry["id"]:
                problems.append(
                    f"{where}.tags: tag {tag_id!r} is already attached to {owner[tag_id]!r}"
                )
            owner.setdefault(tag_id, entry["id"])
    return problems


def _parent_problems(where: str, entry: Document, by_id: dict[str, Document]) -> list[str]:
    """Missing parent, wrong level order and parent cycle of one entry."""
    parent_id = entry.get("parent")
    if parent_id is None:
        return (
            []
            if entry["level"] == "site"
            else [f"{where}.parent: a {entry['level']} needs a parent"]
        )
    if entry["level"] == "site":
        return [f"{where}.parent: a site has no parent"]
    if parent_id not in by_id:
        return [f"{where}.parent: unknown equipment {parent_id!r}"]
    if _has_cycle(entry["id"], by_id):
        return [f"{where}.parent: cycle through {entry['id']!r}"]
    if LEVELS[by_id[parent_id]["level"]] >= LEVELS[entry["level"]]:
        return [f"{where}.parent: {parent_id!r} must be above the {entry['level']} level"]
    return []


def _has_cycle(start: str, by_id: dict[str, Document]) -> bool:
    """True when following parents from ``start`` returns to it."""
    current, steps = by_id[start].get("parent"), 0
    while current in by_id and steps <= len(by_id):
        if current == start:
            return True
        current, steps = by_id[current].get("parent"), steps + 1
    return False


def _loop_problems(
    loops: list[Document],
    tags: dict[str, Document],
    loop_ids: set[str],
    conversions: list[Document],
) -> list[str]:
    """Tag ids, links and units of each loop."""
    problems: list[str] = []
    for index, loop in enumerate(loops):
        where = f"loops.{index}"
        slots = [loop[slot] for slot in LOOP_SLOTS if slot in loop]
        problems += _unknown(where, slots, tags)
        problems += _link_problems(where, loop, tags, loop_ids)
        problems += _loop_unit_problems(where, loop, tags, conversions)
    return problems


def _link_problems(
    where: str, loop: Document, tags: dict[str, Document], loop_ids: set[str]
) -> list[str]:
    """Each link names what its kind needs, and that exists."""
    problems: list[str] = []
    for number, link in enumerate(loop.get("links", [])):
        spot = f"{where}.links.{number}"
        if link["kind"] == "feedforward":
            problems += (
                _unknown(spot, [link["tag"]], tags) if "tag" in link else [f"{spot}: needs a tag"]
            )
        elif "loop" not in link:
            problems.append(f"{spot}: needs a loop")
        elif link["loop"] not in loop_ids or link["loop"] == loop["id"]:
            problems.append(f"{spot}: unknown loop {link['loop']!r}")
    return problems


def _loop_unit_problems(
    where: str, loop: Document, tags: dict[str, Document], conversions: list[Document]
) -> list[str]:
    """PV and SP must be in the same or convertible units."""
    pv, sp = tags.get(loop["pv"]), tags.get(loop.get("sp", ""))
    if pv is None or sp is None or not pv.get("unit") or not sp.get("unit"):
        return []
    if convertible(pv["unit"], sp["unit"], conversions):
        return []
    return [f"{where}: pv unit {pv['unit']!r} cannot be converted to sp unit {sp['unit']!r}"]


def _signal_problems(
    document: Document, tags: dict[str, Document], loop_ids: set[str]
) -> list[str]:
    """Signals name known tags and loops and agree with loops[]."""
    loops = {loop["id"]: loop for loop in document.get("loops", [])}
    problems: list[str] = []
    for index, signal in enumerate(document.get("signals", [])):
        where = f"signals.{index}"
        problems += _unknown(where, [signal["tag"]], tags)
        problems += _signal_loop_problems(where, signal, loops, loop_ids)
    return problems


def _signal_loop_problems(
    where: str, signal: Document, loops: dict[str, Document], loop_ids: set[str]
) -> list[str]:
    """A loop role needs a known loop whose slot holds the same tag."""
    role, loop_id = signal["role"], signal.get("loop")
    if loop_id is None:
        return [f"{where}.loop: role {role!r} needs a loop"] if role in LOOP_ROLES else []
    if loop_id not in loop_ids:
        return [f"{where}.loop: unknown loop {loop_id!r}"]
    if role in LOOP_SLOTS and loops[loop_id].get(role) != signal["tag"]:
        return [
            f"{where}: loop {loop_id!r} has {loops[loop_id].get(role)!r} as {role}, "
            f"not {signal['tag']!r}"
        ]
    return []


def _lab_problems(
    labs: list[Document], tags: dict[str, Document], conversions: list[Document]
) -> list[str]:
    """The result tag exists and the lab unit converts to the tag unit."""
    problems: list[str] = []
    for index, lab in enumerate(labs):
        tag = tags.get(lab.get("tag", ""))
        if "tag" in lab and tag is None:
            problems += _unknown(f"labs.{index}", [lab["tag"]], tags)
        elif tag and lab.get("unit") and tag.get("unit"):
            if not convertible(lab["unit"], tag["unit"], conversions):
                problems.append(
                    f"labs.{index}.unit: {lab['unit']!r} cannot be converted "
                    f"to tag unit {tag['unit']!r}"
                )
    return problems


def _mode_problems(
    modes: list[Document], tags: dict[str, Document], equipment: list[Document]
) -> list[str]:
    """Scope names equipment; every clause names a tag."""
    ids = {entry["id"] for entry in equipment}
    problems: list[str] = []
    for index, mode in enumerate(modes):
        where = f"modes.{index}"
        if "scope" in mode and mode["scope"] not in ids:
            problems.append(f"{where}.scope: unknown equipment {mode['scope']!r}")
        clauses = [clause["tag"] for clause in mode["condition"]["clauses"]]
        problems += _unknown(f"{where}.condition", clauses, tags)
    return problems
