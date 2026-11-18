"""Loops of the site catalogue as LoopTags, including the per-loop tuning knowledge.

One variable model (ADR 015): when a loop exists in ``<root>/_site/site.json`` that entry is
the single home of its knowledge (delay, ultimate period, amplitude limit, process kind,
vendor and engineering-range overrides). The adapter below carries that knowledge into
``LoopTags``, and the knowledge editor writes into the same entry. A dataset's
``project.json`` serves only datasets without a site catalogue loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from crosscut_connectors.site import load_site, site_path
from crosscut_loops.overview import LoopTags

PROCESS_KIND_DEFAULT = "self_regulating"


def _number(value: Any) -> float | None:
    """The value as float, or None when it is missing."""
    return None if value is None else float(value)


def tag_limits(tag: dict[str, Any]) -> tuple[float | None, float | None]:
    """Engineering limits of a tag row: flat eng_min/eng_max first, else ``eng_limits``."""
    block = tag.get("eng_limits") or {}
    low = tag.get("eng_min") if tag.get("eng_min") is not None else block.get("min")
    high = tag.get("eng_max") if tag.get("eng_max") is not None else block.get("max")
    return _number(low), _number(high)


def _first(*values: Any) -> float | None:
    """The first value that is not None, as float."""
    return _number(next((v for v in values if v is not None), None))


def merge_tags(
    site_tags: list[dict[str, Any]], dataset_tags: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Tag rows by id; a dataset row overrides the site row field by field."""
    merged = {t["id"]: dict(t) for t in site_tags}
    for row in dataset_tags:
        merged[row["id"]] = {**merged.get(row["id"], {}), **row}
    return merged


def build_site_loop(entry: dict[str, Any], tag_map: dict[str, dict[str, Any]]) -> LoopTags:
    """Build one LoopTags from a site catalogue loop entry and its stored knowledge."""
    lid = str(entry.get("id", ""))
    pv, out = str(entry.get("pv", "") or ""), str(entry.get("out", "") or "")
    pv_tag, out_tag = tag_map.get(pv, {}), tag_map.get(out, {})
    pv_low, pv_high = tag_limits(pv_tag)
    out_limits = entry.get("out_limits") or {}
    out_low, out_high = tag_limits(out_tag)
    return LoopTags(
        name=str(entry.get("name") or lid),
        pv=pv,
        sp=str(entry.get("sp", "") or ""),
        out=out,
        mode=str(entry.get("mode", "") or ""),
        unit=str(pv_tag.get("unit", "") or ""),
        eng_min=_first(entry.get("pv_eng_min"), pv_low),
        eng_max=_first(entry.get("pv_eng_max"), pv_high),
        delay_s=_number(entry.get("delay_s")),
        ultimate_period_s=_number(entry.get("ultimate_period_s")),
        amplitude_limit=_number(entry.get("amplitude_limit")),
        out_low=_first(entry.get("out_eng_min"), out_limits.get("min"), out_low),
        out_high=_first(entry.get("out_eng_max"), out_limits.get("max"), out_high),
        process_kind=str(entry.get("process_kind") or PROCESS_KIND_DEFAULT),
        vendor=entry.get("vendor"),
    )


def _stated_tags_in(entry: dict[str, Any], tag_dict: dict[str, dict[str, Any]]) -> bool:
    """True unless a PV or OUT id the site loop states is missing from the dataset.

    An empty or absent PV/OUT is not stated, so the loop is kept (onboarding
    readiness reports out-less loops as amber).
    """
    stated = [str(entry.get(role, "") or "") for role in ("pv", "out")]
    return all(tag in tag_dict for tag in stated if tag)


def usable_site_entries(root: Path, tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Site loop entries whose stated PV/OUT exist in the dataset; [] without a catalogue."""
    if not site_path(root).exists():
        return []
    try:
        entries = load_site(root).get("loops") or []
    except Exception:
        return []
    tag_dict = {t["id"]: t for t in tags}
    return [e for e in entries if _stated_tags_in(e, tag_dict)]


def site_loops_of(root: Path, tags: list[dict[str, Any]]) -> list[LoopTags]:
    """Return LoopTags defined in <root>/_site/site.json when present."""
    entries = usable_site_entries(root, tags)
    if not entries:
        return []
    try:
        merged = merge_tags(load_site(root).get("tags", []), tags)
        return [build_site_loop(entry, merged) for entry in entries]
    except Exception:
        return []


def site_entry_names(root: Path, tags: list[dict[str, Any]]) -> set[str]:
    """Display names of the usable site loops (name, else id)."""
    return {str(e.get("name") or e.get("id", "")) for e in usable_site_entries(root, tags)}


def flat_tag_rows(root: Path, tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dataset tag rows merged with the site rows, limits flattened to eng_min/eng_max."""
    try:
        site_tags = load_site(root).get("tags", []) if site_path(root).exists() else []
    except Exception:
        site_tags = []
    rows = []
    for row in merge_tags(site_tags, tags).values():
        low, high = tag_limits(row)
        rows.append({**row, "eng_min": low, "eng_max": high})
    return rows
