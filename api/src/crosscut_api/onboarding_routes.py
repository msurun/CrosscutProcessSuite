"""HTTP routes for dataset onboarding and multi-module readiness checks (Phase 1, #39).

Calculates per-module readiness verdicts (ok, warning, not_ready) and actionable advice
for control loops, anomaly detection, and soft sensors.
"""

from __future__ import annotations

from typing import Any

from crosscut_connectors.onboarding import evaluate_dataset_readiness
from crosscut_connectors.site import load_site, site_path
from fastapi import APIRouter

# Note: DatasetStore is defined in crosscut_api.app


def build_onboarding_router(store: Any) -> APIRouter:
    """Build and return FastAPI router for dataset onboarding and readiness checks."""
    router = APIRouter()

    @router.get("/datasets/{dataset_id}/readiness")
    def get_dataset_readiness(dataset_id: str) -> dict[str, Any]:
        """Compute readiness verdicts for loops, anomaly detection, and soft sensor."""
        t_s, values = store.load_seconds(dataset_id)
        loops = store.loops_of(dataset_id)
        site_doc = load_site(store.root) if site_path(store.root).exists() else None
        readiness = evaluate_dataset_readiness(dataset_id, t_s, values, loops, site_doc)
        return readiness.to_dict()

    return router

