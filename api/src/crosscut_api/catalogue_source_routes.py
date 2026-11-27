"""Build the site catalogue from a source: browse, test naming rules, preview, import (#209).

PRODUCT 3.1 steps 1-3 without typing: the source's address space is walked (browse + metadata),
ordered regex naming rules propose loops, roles, areas and equipment, the engineer sees the
preview (loops, incomplete loops, conflicts, unmatched tags) and imports the accepted part into
``site.json``. Nothing here writes to a plant.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any

from crosscut_connectors.base import CAP_BROWSE, CAP_METADATA, ConnectorError, NodeInfo
from crosscut_connectors.condition_signals import propose_kind, propose_running
from crosscut_connectors.naming_rules import PRESETS, NamingResult, apply_rules, compile_rules
from crosscut_connectors.registry import connector_from_source
from crosscut_connectors.site import validate_site
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import auth_dir
from crosscut_api.connector_routes import _find_source
from crosscut_api.site_version_routes import store_draft
from crosscut_api.source_admin_routes import _site

Doc = dict[str, Any]
# Most address-space nodes one walk visits; a larger tree is browsed branch by branch.
MAX_NODES = 5000


class RulesBody(BaseModel):
    """Naming rules and the tag names to test them on."""

    rules: list[Doc] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, max_length=20000)


class PreviewBody(BaseModel):
    """Which branches of a source to walk and the rules to apply."""

    nodes: list[str | None] = Field(default_factory=lambda: [None])
    rules: list[Doc] = Field(default_factory=list)


class ImportBody(BaseModel):
    """The accepted preview: tags (with their metadata), rules, and what to create from them."""

    tags: list[Doc] = Field(min_length=1, max_length=20000)
    rules: list[Doc] = Field(default_factory=list)
    loops: bool = True
    equipment: bool = True


def _compiled(raw: list[Doc]) -> Any:
    """Compiled rules; 422 naming the broken rule."""
    try:
        return compile_rules(raw)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def result_doc(result: NamingResult) -> Doc:
    """The rule result as JSON: matches, unmatched, conflicts, loops, incomplete, tree."""
    return {
        "matches": [asdict(m) for m in result.matches],
        "unmatched": result.unmatched,
        "conflicts": result.conflicts,
        "loops": result.loops,
        "incomplete": result.incomplete,
        "tree": result.tree,
    }


def walk(connector: Any, starts: list[str | None]) -> list[NodeInfo]:
    """Variable nodes below the start nodes, breadth first, at most MAX_NODES visited."""
    queue, found, seen = list(starts), [], 0
    while queue and seen < MAX_NODES:
        for node in connector.browse(node_id=queue.pop(0)):
            seen += 1
            if node.has_children:
                queue.append(node.id)
            if node.node_type == "variable":
                found.append(node)
    return found


def _path_segments(node: NodeInfo) -> list[str]:
    """The ``/`` parts of a string node id (``ns=2;s=A/B/C`` gives A, B, C), else [name]."""
    _, found, identifier = node.id.partition(";s=")
    parts = [part for part in identifier.split("/") if part] if found else []
    return parts or [node.name]


def _distinct_tails(group: list[NodeInfo]) -> dict[str, str]:
    """Names for nodes that share a browse name: the shortest path tails that tell them apart."""
    deepest = max(len(_path_segments(n)) for n in group)
    for depth in range(2, deepest + 1):
        tails = {n.id: ".".join(_path_segments(n)[-depth:]) for n in group}
        if len(set(tails.values())) == len(group):
            return tails
    return {n.id: n.name for n in group}


def unique_names(nodes: list[NodeInfo]) -> dict[str, str]:
    """Tag name per node id: the browse name, or a path tail when that name is not unique.

    OPC UA browse names are unique only under one parent (a DCS has ``Pv`` under every loop) but
    a catalogue tag id must be unique, so a repeated name becomes ``parent.name`` (``LIC301.Pv``),
    which naming rules can read the loop from. Names that are already unique are unchanged.
    """
    groups: dict[str, list[NodeInfo]] = {}
    for node in nodes:
        groups.setdefault(node.name, []).append(node)
    names = {node.id: node.name for node in nodes}
    for group in groups.values():
        if len(group) > 1:
            names.update(_distinct_tails(group))
    return names


def _metadata(connector: Any, nodes: list[NodeInfo]) -> dict[str, Doc]:
    """Unit, description and range per node id: browse info, improved by metadata() if offered."""
    meta = {n.id: {"unit": n.unit, "description": n.description} for n in nodes}
    if CAP_METADATA not in connector.capabilities() or not nodes:
        return meta
    try:
        for m in connector.metadata([n.id for n in nodes]):
            entry = meta.setdefault(m.id, {})
            entry.update({k: v for k, v in asdict(m).items() if v is not None and k != "id"})
    except ConnectorError:
        pass  # metadata only enriches the preview; browse results stay usable
    return meta


def _tag_entry(source_id: str, item: Doc) -> Doc:
    """A catalogue tag from a preview item: its name is the id, its node id the address."""
    entry: Doc = {
        "id": str(item["name"]),
        "source": source_id,
        "address": str(item.get("address") or item["name"]),
    }
    for key in ("unit", "description"):
        if item.get(key):
            entry[key] = str(item[key])
    return entry


def _loop_entries(result: NamingResult) -> list[Doc]:
    """Catalogue loops for every found loop with at least PV and OUT."""
    loops = []
    for loop_id, roles in result.loops.items():
        if "pv" in roles and "out" in roles:
            loops.append(
                {"id": loop_id, **{r: roles[r] for r in ("pv", "sp", "out", "mode") if r in roles}}
            )
    return loops


def _site_root(existing: list[Doc]) -> tuple[str, list[Doc]]:
    """Id of the site-level entry every area hangs under, creating ``site`` when there is none."""
    for entry in existing:
        if entry.get("level") == "site":
            return str(entry["id"]), []
    return "site", [{"id": "site", "level": "site"}]


@dataclass(frozen=True)
class _EquipmentInput:
    """What the equipment builder needs besides the rule tree."""

    loop_tags: dict[str, list[str]]  # loop id -> its tags (PV, SP, OUT, MODE)
    created: set[str]  # loop ids that exist in the catalogue after this import
    units: dict[str, str]  # tag id -> engineering unit, for the signal kind proposal


def _signals(tags: list[str], units: dict[str, str]) -> list[Doc]:
    """Condition signals with a proposed kind (unconfirmed) for tags that have one (#214)."""
    found = [(tag, propose_kind(tag, units.get(tag), None)) for tag in tags]
    return [{"tag": tag, "kind": kind, "confirmed": False} for tag, kind in found if kind]


def _equipment(eq_id: str, parent: str, content: Doc, given: _EquipmentInput) -> Doc:
    """One equipment entry: owned loops, all their tags plus signals, signals and running state."""
    loops = [loop for loop in content["loops"] if loop in given.created]
    loop_tags = [t for loop in loops for t in given.loop_tags.get(loop, [])]
    entry: Doc = {
        "id": eq_id,
        "level": "equipment",
        "parent": parent,
        "tags": list(dict.fromkeys(loop_tags + content["signals"])),
    }
    if loops:
        entry["loops"] = loops
    if signals := _signals(content["signals"], given.units):
        entry["signals"] = signals
        if running := propose_running(signals):
            entry["running"] = running
    return entry


def _equipment_entries(
    result: NamingResult, given: _EquipmentInput, existing: list[Doc]
) -> list[Doc]:
    """ISA-95 entries from the rule tree: site > area > equipment (#209, #214).

    Every entry below the site needs a parent (catalogue rule), so areas hang under the site
    entry and equipment found without an area hangs directly under it. A created loop that no
    equipment owns becomes a one-loop equipment (owner decision 2026-11-20).
    """
    root, entries = _site_root(existing)
    owned: set[str] = set()
    for area, equipment in result.tree.items():
        if area:
            entries.append({"id": area, "level": "area", "parent": root})
        for eq_id, content in equipment.items():
            if eq_id:
                entries.append(_equipment(eq_id, area or root, content, given))
                owned.update(content["loops"])
    for loop in sorted(given.created - owned):
        lone = _equipment(loop, root, {"loops": [loop], "signals": []}, given)
        entries.append(lone)
    return entries


def _merge(items: list[Doc], extra: list[Doc]) -> list[Doc]:
    """Existing entries plus the new ones; an existing id is kept (the engineer's edits win)."""
    known = {item["id"] for item in items}
    return items + [e for e in extra if e["id"] not in known]


def merged_site(site: Doc, source_id: str, body: ImportBody) -> tuple[Doc, Doc]:
    """The site with the import merged in, and counts of what was added."""
    out = copy.deepcopy(site)
    tags = [_tag_entry(source_id, item) for item in body.tags]
    result = apply_rules(_compiled(body.rules), [t["id"] for t in tags])
    before = {k: len(out.get(k, [])) for k in ("tags", "loops", "equipment")}
    out["tags"] = _merge(out.get("tags", []), tags)
    if body.loops:
        out["loops"] = _merge(out.get("loops", []), _loop_entries(result))
    if body.equipment:
        given = _EquipmentInput(
            loop_tags={loop: list(roles.values()) for loop, roles in result.loops.items()},
            created={loop["id"] for loop in out.get("loops", [])},
            units={t["id"]: t.get("unit", "") for t in out["tags"]},
        )
        existing = out.get("equipment", [])
        out["equipment"] = _merge(existing, _equipment_entries(result, given, existing))
    if body.rules:
        out.setdefault("naming", {})["rules"] = body.rules
    added = {k: len(out.get(k, [])) - before[k] for k in before}
    return out, added


class _Endpoints:
    """Handlers of the catalogue-from-source routes."""

    def __init__(self, root: Path, clock: Callable[[], float]) -> None:
        """Bind the data root and the audit clock."""
        self.root, self._clock = root, clock

    def presets(self) -> Doc:
        """Built-in naming rule presets for public tag conventions."""
        return {"presets": PRESETS}

    def test_rules(self, body: RulesBody) -> Doc:
        """Apply rules to a list of tag names (the rule tester)."""
        return result_doc(apply_rules(_compiled(body.rules), body.tags))

    def preview(self, source_id: str, body: PreviewBody) -> Doc:
        """Walk the chosen branches of a source, read metadata, apply the rules."""
        source = _find_source(self.root, source_id)
        rules = _compiled(body.rules)
        try:
            connector = connector_from_source(source)
            if CAP_BROWSE not in connector.capabilities():
                raise HTTPException(status_code=400, detail="source does not offer browsing")
            nodes = walk(connector, body.nodes)
            meta = _metadata(connector, nodes)
        except ConnectorError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        names = unique_names(nodes)
        items = [{"name": names[n.id], "address": n.id, **meta.get(n.id, {})} for n in nodes]
        return {
            "source": source_id,
            "items": items,
            "truncated": len(nodes) >= MAX_NODES,
            "naming": result_doc(apply_rules(rules, [i["name"] for i in items])),
        }

    def import_catalogue(
        self, source_id: str, body: ImportBody, actor: Annotated[ActorContext, Depends(actor_of)]
    ) -> Doc:
        """Merge the accepted preview into site.json (existing ids are kept)."""
        actor.require("config.edit")
        _find_source(self.root, source_id)
        site, added = merged_site(_site(self.root), source_id, body)
        problems = validate_site(site)
        if problems:
            raise HTTPException(status_code=422, detail=problems)
        self._audit(actor, source_id, added)
        store_draft(self.root, site, actor.actor)
        return {"source": source_id, "added": added}

    def _audit(self, actor: ActorContext, source_id: str, added: Doc) -> None:
        """Audit the import; no audit line, no change (503)."""
        audit = AuthAudit(auth_dir(self.root) / AUDIT_FILE, self._clock)
        counts = ",".join(f"{k}={v}" for k, v in added.items())
        try:
            audit.append(
                "catalogue_import",
                actor=actor.actor,
                source_ip=actor.source_ip,
                source=source_id,
                added=counts,
            )
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=503, detail="audit_unavailable") from error


def build_catalogue_source_router(root: Path, clock: Callable[[], float] = time.time) -> APIRouter:
    """Routes: naming presets, rule tester, source preview and catalogue import."""
    e = _Endpoints(root, clock)
    router = APIRouter()
    router.add_api_route("/catalogue/naming/presets", e.presets, methods=["GET"])
    router.add_api_route("/catalogue/naming/test", e.test_rules, methods=["POST"])
    router.add_api_route("/sources/{source_id}/catalogue-preview", e.preview, methods=["POST"])
    router.add_api_route(
        "/sources/{source_id}/catalogue-import", e.import_catalogue, methods=["POST"]
    )
    return router
