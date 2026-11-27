"""Small helpers that tie model fits and job deploys to the dependency index (#166).

A fit, a redeploy or an engineer's re-confirmation re-baselines a dependent on the catalogue in
force; a deploy or a preview of a stale model is refused with the reason. Everything here is
best effort on the registering side (no catalogue yet means nothing to track) and strict on the
refusing side (a stale model never passes).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from crosscut_connectors.dependency_index import (
    DependencyError,
    register,
    scan_dependents,
    stale_reasons,
)
from crosscut_connectors.site import SiteError, load_site
from crosscut_connectors.site_fingerprint import reason_text

from crosscut_api.site_versions import current_version


def _site(root: Path) -> dict[str, Any] | None:
    """The published catalogue, None when there is none or it is unreadable."""
    try:
        return load_site(root)
    except (SiteError, OSError):
        return None


def register_dependent(root: Path, kind: str, ident: str) -> None:
    """Baseline ``kind:ident`` on the published catalogue (after a fit or a job save)."""
    site = _site(root)
    if site is None:
        return
    dependent = scan_dependents(root, site).get(f"{kind}:{ident}")
    if dependent is not None:
        try:
            register(root, site, dependent, current_version(root))
        except DependencyError:
            pass  # a busy index only delays tracking; the next publish baselines it


def stale_problem(root: Path, key: str) -> str | None:
    """Why ``key`` must not be deployed or used (the reason text), None when it is fine."""
    site = _site(root)
    reasons = stale_reasons(root, site, key) if site is not None else []
    if not reasons:
        return None
    return reason_text(reasons)
