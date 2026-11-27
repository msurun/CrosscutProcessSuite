"""Read-only proposals of operating modes and equipment groups from a dataset's history (#145).

PRODUCT 3.1 step 2: the engine proposes, the engineer accepts or edits in the GUI, and the
accepted items are saved through the ordinary site route. Nothing is written here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from crosscut_connectors.mode_proposals import propose_from_history
from fastapi import APIRouter

from crosscut_api.source_admin_routes import _site

if TYPE_CHECKING:
    from crosscut_api.app import DatasetStore

DatasetResolver = Callable[[Path, str], Path]
PROPOSAL_PATH = "/datasets/{dataset_id}/catalogue/proposals/modes"


class _ModeProposalEndpoints:
    """Load one dataset's history and the site document, and run the engine."""

    def __init__(self, store: DatasetStore, resolve_dataset: DatasetResolver) -> None:
        """Keep the shared dataset store so history is read like every other view."""
        self.store = store
        self.resolve_dataset = resolve_dataset

    def get_proposals(self, dataset_id: str) -> dict[str, Any]:
        """Mode and equipment-group proposals with evidence; the catalogue is not changed."""
        self.resolve_dataset(self.store.root, dataset_id)  # 404 for an unknown dataset
        t_s, values = self.store.load_seconds(dataset_id)
        arrays = {tag: np.asarray(v, dtype=float) for tag, v in values.items()}
        found = propose_from_history(t_s, arrays, _site(self.store.root))
        return {"dataset": dataset_id, **found}


def build_mode_proposal_router(store: DatasetStore, resolve_dataset: DatasetResolver) -> APIRouter:
    """Register the read-only mode proposal endpoint."""
    endpoints = _ModeProposalEndpoints(store, resolve_dataset)
    router = APIRouter()
    router.add_api_route(PROPOSAL_PATH, endpoints.get_proposals, methods=["GET"])
    return router
