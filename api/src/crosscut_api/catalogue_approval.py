"""When does publishing a catalogue version need a second engineer? (issue #165, ADR 013)

Owner rule: a second person (an engineer or lead other than the publisher) approves only when
the change touches a loop or a controller that has ACTIVE WRITES; any other change is published
by one engineer. "Active writes" is read from files the other processes already keep:

* a controller whose runtime record (``_runtime/controllers/<id>.json``) is ``on`` writes
  through its MV bindings, so the controller and the loops its MVs bind are active;
* a loop whose output tag is an enabled gateway target while the gateway mode is ``confirm``
  or ``supervised`` is active (``_gateway/state.json``);
* a gateway folder whose state cannot be read is treated as unknown: every loop and controller
  counts as active (fail closed).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crosscut_runtime.controllers.host import record_path
from crosscut_runtime.controllers.state import ON

Doc = dict[str, Any]
WRITING_MODES = frozenset({"confirm", "supervised"})
ENABLED_TARGET = "enabled"


@dataclass(frozen=True)
class ActiveWrites:
    """Loop and controller ids with active writes; ``unknown`` when the gateway cannot be read."""

    loops: frozenset[str] = frozenset()
    controllers: frozenset[str] = frozenset()
    unknown: bool = False


def _gateway_targets(root: Path) -> tuple[frozenset[str], bool]:
    """Enabled gateway target tags while writing is allowed, and whether the state is unknown."""
    gateway = root / "_gateway"
    if not gateway.is_dir():
        return frozenset(), False
    try:
        state = json.loads((gateway / "state.json").read_text(encoding="utf-8"))
        targets = state.get("targets") or {}
        writing = state.get("mode") in WRITING_MODES
    except (OSError, ValueError, AttributeError):
        return frozenset(), True
    enabled = {tag for tag, value in targets.items() if value == ENABLED_TARGET}
    return frozenset(enabled if writing else ()), False


def _controller_loops(controller: Doc) -> set[str]:
    """Loop ids bound by the MV variables of a controller entry."""
    return {
        v["binding"]["loop"]
        for v in controller.get("variables", [])
        if v.get("role") == "MV" and "loop" in v.get("binding", {})
    }


def _record_state(root: Path, controller_id: str) -> str:
    """The state stored in a controller record as written (``load_record`` would turn a stored
    ``on`` into ``standby``, which is right after a restart but hides a running controller)."""
    try:
        data = json.loads(record_path(root, controller_id).read_text(encoding="utf-8"))
        return str(data["state"])
    except FileNotFoundError:
        return ""  # never started: off
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return ON  # a record that exists but cannot be read counts as running (fail closed)


def active_writes(root: Path, published: Doc) -> ActiveWrites:
    """The loops and controllers of the published catalogue that write right now."""
    targets, unknown = _gateway_targets(root)
    loops = {loop["id"] for loop in published.get("loops", []) if loop.get("out") in targets}
    controllers: set[str] = set()
    for controller in published.get("controllers", []):
        if _record_state(root, controller["id"]) == ON:
            controllers.add(controller["id"])
            loops |= _controller_loops(controller)
    return ActiveWrites(frozenset(loops), frozenset(controllers), unknown)


def _changed_ids(section: Doc | None) -> set[str]:
    """Ids removed or changed in one diff section (added entries cannot be active yet)."""
    if not section:
        return set()
    return set(section.get("removed", [])) | {c["id"] for c in section.get("changed", [])}


LOOP_TAG_FIELDS = ("pv", "sp", "out", "mode")


def _entries(docs: list[Doc], section: str, ids: set[str]) -> list[Doc]:
    """The entries of a section with one of the ids, from every document (old and new)."""
    return [e for d in docs for e in d.get(section, []) if str(e.get("id")) in ids]


def _loops_of_tags(docs: list[Doc], tags: set[str]) -> set[str]:
    """Loops whose pv/sp/out/mode tag is one of ``tags``: a tag change is a change of the loop."""
    return {
        loop["id"]
        for d in docs
        for loop in d.get("loops", [])
        if any(loop.get(field) in tags for field in LOOP_TAG_FIELDS)
    }


def _controllers_of_tags(docs: list[Doc], tags: set[str]) -> set[str]:
    """Controllers with a variable bound to one of ``tags`` (CV, DV, ICV)."""
    return {
        c["id"]
        for d in docs
        for c in d.get("controllers", [])
        if any(v.get("binding", {}).get("tag") in tags for v in c.get("variables", []))
    }


def _equipment_reach(docs: list[Doc], equipment: set[str]) -> tuple[set[str], set[str]]:
    """Loops and tags a changed equipment entry owns or refers to (old and new membership)."""
    loops: set[str] = set()
    tags: set[str] = set()
    for entry in _entries(docs, "equipment", equipment):
        loops |= set(entry.get("loops", [])) | set(entry.get("loop_refs", []))
        tags |= set(entry.get("tags", []))
    return loops, tags


def _touched(diff: Doc, docs: list[Doc]) -> tuple[set[str], set[str]]:
    """Loop and controller ids a diff changes, directly or through tags and equipment."""
    sections = diff["sections"]
    loops = _changed_ids(sections.get("loops"))
    controllers = _changed_ids(sections.get("controllers"))
    tags = _changed_ids(sections.get("tags"))
    equip_loops, equip_tags = _equipment_reach(docs, _changed_ids(sections.get("equipment")))
    tags |= equip_tags
    loops |= equip_loops | _loops_of_tags(docs, tags)
    controllers |= _controllers_of_tags(docs, tags)
    return loops, controllers


def approval_reasons(diff: Doc, active: ActiveWrites, old: Doc, new: Doc) -> list[str]:
    """``loop:<id>`` / ``controller:<id>`` for every active entry the diff changes or removes.

    A changed or removed tag, or changed equipment membership, counts as a change of every loop
    (and controller variable) that uses it, even when the loop entry itself is unchanged.
    """
    loops, controllers = _touched(diff, [old, new])
    if not active.unknown:
        loops &= active.loops
        controllers &= active.controllers
    return sorted(f"loop:{i}" for i in loops) + sorted(f"controller:{i}" for i in controllers)
