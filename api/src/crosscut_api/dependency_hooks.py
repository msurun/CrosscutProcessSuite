"""Small helpers that tie model fits and job deploys to the dependency index (#166).

A fit, a redeploy or an engineer's re-confirmation re-baselines a dependent on the catalogue in
force; a deploy or a preview of a stale model is refused with the reason. Everything here is
best effort on the registering side (no catalogue yet means nothing to track) and strict on the
refusing side (a stale model never passes).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from crosscut_connectors.dependency_index import (
    DependencyError,
    IndexUnreadableError,
    register,
    scan_dependents,
    stale_reasons,
)
from crosscut_connectors.site import SiteError, load_site, site_path
from crosscut_connectors.site_fingerprint import reason_text

from crosscut_api.site_versions import current_version

REGISTER_TRIES = 4
REGISTER_WAIT_S = 0.2


def _site(root: Path) -> dict[str, Any] | None:
    """The published catalogue, None when there is none; SiteError/OSError when unreadable."""
    return load_site(root) if site_path(root).exists() else None


def register_dependent(root: Path, kind: str, ident: str) -> None:
    """Baseline ``kind:ident`` on the published catalogue (after a fit or a job save).

    A busy index is retried briefly; if it still fails the old (stale) entry stays, so the
    dependent keeps refusing to run or deploy rather than passing on an outdated baseline.
    """
    try:
        site = _site(root)
    except (SiteError, OSError):
        return
    dependent = None if site is None else scan_dependents(root, site).get(f"{kind}:{ident}")
    if site is None or dependent is None:
        return
    for attempt in range(REGISTER_TRIES):
        try:
            register(root, site, dependent, current_version(root))
            return
        except IndexUnreadableError:
            break  # a corrupt index must be repaired by hand, retrying cannot help
        except DependencyError:
            time.sleep(REGISTER_WAIT_S * (attempt + 1))
    logging.getLogger(__name__).warning("could not re-baseline %s:%s; it stays stale", kind, ident)


def stale_problem(root: Path, key: str) -> str | None:
    """Why ``key`` must not be deployed or used (the reason text), None when it is fine."""
    try:
        site = _site(root)
    except (SiteError, OSError):
        return "catalogue_unreadable"
    if site is None:
        return None
    try:
        reasons = stale_reasons(root, site, key)
    except IndexUnreadableError as error:
        return str(error)
    return reason_text(reasons) if reasons else None
