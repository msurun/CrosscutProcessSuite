"""Read-only operating-envelope route of a dataset (PRODUCT 8.3a, #189).

Descriptive conditional quantiles per operating mode; it never writes and makes no causal claim.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import numpy as np
from crosscut_anomaly.operating_envelope import EnvelopeError, operating_envelope
from crosscut_connectors import mode_eval
from crosscut_connectors.site import SiteError, load_site
from fastapi import APIRouter, HTTPException, Query

NS_PER_SECOND = 1_000_000_000
WideLoader = Callable[[str], tuple[np.ndarray, dict[str, Any]]]
QualityLoader = Callable[[str], dict[str, np.ndarray]]


def _utc(timestamp_ns: float) -> str:
    """ISO 8601 UTC text of a nanosecond Unix timestamp."""
    moment = datetime.fromtimestamp(float(timestamp_ns) / NS_PER_SECOND, tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _site(root: Path) -> dict[str, Any]:
    """The catalogue, or an empty one when none exists (then all samples form one mode)."""
    try:
        return load_site(root)
    except SiteError:
        return {}


def _modes(site: dict, target: str | None, data: dict, count: int) -> tuple:
    """Mode label and stopped mask per sample; no modes means one mode ``all``."""
    if not site.get("modes"):
        return np.full(count, "all", dtype=object), np.zeros(count, dtype=bool)
    labels = mode_eval.evaluate(site, target, data, count)
    off = mode_eval.not_running(site, target, data, count)
    return labels, mode_eval.stopped_mask(labels, off)


class EnvelopeEndpoints:
    """Bind the envelope route to one data root and its dataset loaders."""

    def __init__(self, root: Path, load_wide: WideLoader, load_quality: QualityLoader) -> None:
        """Store the root and the aligned value and quality readers."""
        self.root, self.load_wide, self.load_quality = root, load_wide, load_quality

    def envelope(self, dataset_id: str, outcome: str, variables: list[str], options: dict,
                 target: str | None) -> dict:
        """Observed per-mode quantiles of ``outcome`` over one or two operating variables."""
        stamps, data = self.load_wide(dataset_id)
        if len(stamps) < 2:
            raise HTTPException(status_code=422, detail="dataset has too few samples")
        quality = self.load_quality(dataset_id)
        data = {tag: np.where(quality[tag] == 0, values, np.nan) for tag, values in data.items()}
        site = _site(self.root)
        labels, stopped = _modes(site, target, data, len(stamps))
        period = float(np.median(np.diff(stamps))) / NS_PER_SECOND
        try:
            result = operating_envelope(data, labels, stopped, outcome=outcome,
                                        variables=variables, sample_period_s=period, **options)
        except EnvelopeError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        window = {"start_utc": _utc(stamps[0]), "end_utc": _utc(stamps[-1])}
        defs = mode_eval.applicable_modes(site, target) if site.get("modes") else []
        return {**result, "dataset_id": dataset_id, "window": window, "target": target,
                "mode_definitions": defs}


def build_operating_envelope_router(
    root: Path, load_wide: WideLoader, load_quality: QualityLoader,
) -> APIRouter:
    """Build the single read-only envelope route for one local data root."""
    router = APIRouter()
    endpoints = EnvelopeEndpoints(root, load_wide, load_quality)

    def route(dataset_id: str, outcome: str, x: str, y: str | None = None,
              bins: Annotated[int, Query(ge=2, le=40)] = 8,
              min_count: Annotated[int, Query(ge=1)] = 20,
              tolerance: Annotated[float, Query(ge=0)] = 0.0,
              direction: Annotated[str, Query(pattern="^(max|min)$")] = "max",
              target: str | None = None) -> dict:
        """Descriptive operating envelope (read-only)."""
        options = {"bins": bins, "min_count": min_count, "tolerance": tolerance,
                   "direction": direction}
        return endpoints.envelope(dataset_id, outcome, [x] + ([y] if y else []), options, target)

    router.add_api_route("/datasets/{dataset_id}/operating-envelope", route, methods=["GET"])
    return router
