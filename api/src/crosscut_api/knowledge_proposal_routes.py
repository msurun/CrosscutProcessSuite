"""Expose evidence-backed loop knowledge suggestions without saving them.

History and metadata use the same dataset store and catalogue merge as the editor.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from crosscut_loops.knowledge_proposal import propose_knowledge
from crosscut_loops.overview import LoopTags
from fastapi import APIRouter, HTTPException

from crosscut_api.site_loops import flat_tag_rows

if TYPE_CHECKING:
    from crosscut_api.app import DatasetStore

DatasetResolver = Callable[[Path, str], Path]
PROPOSAL_PATH = "/datasets/{dataset_id}/loops/{loop_name}/knowledge/proposal"


def _tag_metadata(
    store: DatasetStore, dataset_dir: Path, loop: LoopTags
) -> dict[str, Any]:
    """Read engineering limits from tag metadata, keeping knowledge overrides separate."""
    rows = flat_tag_rows(store.root, store.tags_of(dataset_dir))
    tags_by_id = {row["id"]: row for row in rows}
    return {
        "pv": tags_by_id.get(loop.pv, {}),
        "out": tags_by_id.get(loop.out, {}),
        "vendor": loop.vendor,
    }


def _loop_signals(
    loop: LoopTags, values: dict[str, Any], t_s: np.ndarray
) -> tuple[np.ndarray, ...]:
    """Read aligned PV/SP/OUT/mode arrays; absent optional tags remain unknown."""
    if loop.pv not in values or loop.out not in values:
        raise HTTPException(status_code=422, detail="Record the loop PV and OUT before analysis")
    # NaN keeps a missing mode from being mistaken for a manual operating interval.
    unknown = np.full_like(t_s, np.nan, dtype=float)
    return tuple(np.asarray(values.get(tag, unknown), dtype=float)
                 for tag in (loop.pv, loop.sp, loop.out, loop.mode))


class _ProposalEndpoints:
    """Load one loop's history and translate proposal validation errors to HTTP."""

    def __init__(self, store: DatasetStore, resolve_dataset: DatasetResolver) -> None:
        """Keep the application's shared loaders for consistent dataset resolution."""
        self.store = store
        self.resolve_dataset = resolve_dataset

    def get_proposal(self, dataset_id: str, loop_name: str) -> dict[str, Any]:
        """Return suggestions with evidence; accepted knowledge is saved elsewhere."""
        dataset_dir = self.resolve_dataset(self.store.root, dataset_id)
        loop = self.store.find_loop(dataset_dir, loop_name)
        t_s, values = self.store.load_seconds(dataset_id)
        pv, sp, out, mode = _loop_signals(loop, values, t_s)
        metadata = _tag_metadata(self.store, dataset_dir, loop)
        try:
            proposals = propose_knowledge(t_s, pv, sp, out, mode, metadata)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        needs_step_test = proposals.pop("needs_step_test", False)
        return {"loop": loop_name, "proposals": proposals, "needs_step_test": needs_step_test}


def build_knowledge_proposal_router(
    store: DatasetStore, resolve_dataset: DatasetResolver
) -> APIRouter:
    """Register the read-only history proposal endpoint with the shared dataset store."""
    endpoints = _ProposalEndpoints(store, resolve_dataset)
    router = APIRouter()
    router.add_api_route(PROPOSAL_PATH, endpoints.get_proposal, methods=["GET"])
    return router
