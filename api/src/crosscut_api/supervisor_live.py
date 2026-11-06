"""Live setpoint and target tag lookup for supervisor proposals (ADR 014 section 7).

A proposal is built on the setpoint read live from the plant through the site's connector
(the same read the tuning proposals use), never on a request field or on a historical value.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from crosscut_connectors.registry import connector_from_source
from crosscut_connectors.site import SiteError, load_site
from fastapi import HTTPException

from crosscut_api.tuning_build import read_current

SP_KEY = "sp"


def _refuse(status: int, code: str) -> HTTPException:
    """A refusal whose detail is the stable code."""
    return HTTPException(status_code=status, detail=code)


def site_or_none(root: Path) -> dict[str, Any] | None:
    """The site document of the data root, or None when there is none."""
    try:
        return load_site(root)
    except SiteError:
        return None


def catalog_sp_tag(root: Path, loop_id: str) -> str | None:
    """The setpoint tag the site catalogue names for the loop, or None."""
    site = site_or_none(root) or {}
    for loop in site.get("loops", []):
        if loop_id in (loop.get("id"), loop.get("name")):
            return loop.get("sp") or None
    return None


def _source_of(site: dict[str, Any], tag: str) -> str | None:
    """Source id of the tag; a tag without source belongs to the only source, if just one."""
    sources = [str(s.get("id")) for s in site.get("sources", [])]
    for entry in site.get("tags", []):
        if entry.get("id") == tag and entry.get("source"):
            return str(entry["source"])
    return sources[0] if len(sources) == 1 else None


def read_live_sp(root: Path, tag: str, factory: Callable[[Any], Any] | None = None) -> float:
    """Live value of the setpoint ``tag`` through the site connector.

    Raises:
        HTTPException: 409 ``no_live_sp`` when no site, source or good live value is available.
    """
    site = site_or_none(root)
    source = None if site is None else _source_of(site, tag)
    if site is None or source is None:
        raise _refuse(409, "no_live_sp")
    try:
        value = read_current(site, source, {SP_KEY: tag}, factory or connector_from_source)[SP_KEY]
    except HTTPException:
        raise _refuse(409, "no_live_sp") from None
    if not math.isfinite(value):
        raise _refuse(409, "no_live_sp")
    return value
