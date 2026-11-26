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
        return str(data.get("state", ""))
    except (OSError, ValueError, AttributeError):
        return ""


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


def approval_reasons(diff: Doc, active: ActiveWrites) -> list[str]:
    """``loop:<id>`` / ``controller:<id>`` for every active entry the diff changes or removes."""
    sections = diff["sections"]
    loops = _changed_ids(sections.get("loops"))
    controllers = _changed_ids(sections.get("controllers"))
    if active.unknown:
        return sorted(f"loop:{i}" for i in loops) + sorted(f"controller:{i}" for i in controllers)
    return sorted(f"loop:{i}" for i in loops & active.loops) + sorted(
        f"controller:{i}" for i in controllers & active.controllers
    )
