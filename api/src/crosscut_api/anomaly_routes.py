"""HTTP routes of the PCA anomaly detector (ADR 010): configs, fit on a window, scan, model.

Everything lives in ``<data root>/_anomaly``: ``<aid>.json`` (config), ``<aid>.model.json`` (fitted
PCA) and ``<aid>.manifest.json`` (provenance, ADR 004 style fields). Nothing else is written and
nothing reaches a plant: the detector only advises.
"""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import numpy as np
from crosscut_anomaly.config import AnomalyConfig, AnomalyConfigError, load_config
from crosscut_anomaly.detect import AnomalyEvent, scan
from crosscut_anomaly.pca_model import PcaModel, PcaModelError, fit_pca
from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

DIR_NAME = "_anomaly"
AID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
DEFAULT_MAX_POINTS = 1500
MODEL_KIND = "anomaly_pca"
Aid = Annotated[str, PathParam(pattern=AID_PATTERN)]
SecondsLoader = Callable[[str], tuple[np.ndarray, dict[str, Any]]]
QualityLoader = Callable[[str], dict[str, np.ndarray]]


class WindowRequest(BaseModel):
    """Part of a record (seconds from the first sample) to work on."""

    start_s: float | None = None
    end_s: float | None = None


class ScanRequest(WindowRequest):
    """Window to scan plus the size limit of the returned series."""

    max_points: Annotated[int, Field(ge=2, le=100_000)] = DEFAULT_MAX_POINTS


class _AnomalyEndpoints:
    """The anomaly route handlers, bound to the data root and the dataset loaders."""

    def __init__(
        self, root: Path, load_seconds: SecondsLoader, load_quality: QualityLoader
    ) -> None:
        self.folder = root / DIR_NAME
        self.load_seconds = load_seconds
        self.load_quality = load_quality

    def list_anomalies(self) -> list[str]:
        """Ids of the saved detector configurations, sorted."""
        if not self.folder.is_dir():
            return []
        return sorted(p.stem for p in self.folder.glob("*.json") if "." not in p.stem)

    def get_anomaly(self, aid: Aid) -> dict[str, Any]:
        """One saved configuration as stored (404 when unknown)."""
        path = self._path(aid, ".json")
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"unknown anomaly config: {aid}")
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return document

    def put_anomaly(self, aid: Aid, document: dict[str, Any]) -> dict[str, Any]:
        """Validate and save a configuration (422 with the reason when it is not acceptable)."""
        config = _config_or_422(document)
        if config.id != aid:
            raise HTTPException(status_code=422, detail=f"id: {config.id!r} does not match {aid!r}")
        self._write(self._path(aid, ".json"), document)
        return document

    def post_fit(self, dataset_id: str, aid: Aid, request: WindowRequest) -> dict[str, Any]:
        """Fit the PCA on the window, store model and manifest, return the model summary."""
        config = _config_or_422(self.get_anomaly(aid))
        t_s, x, _ = self._binned(dataset_id, config, request)
        try:
            model = fit_pca(x, config.tags, config.variance_fraction, config.alpha)
        except PcaModelError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        window = {"start_s": float(t_s[0]), "end_s": float(t_s[-1])}
        self._write(self._path(aid, ".model.json"), model.to_dict())
        manifest = _manifest(config, model, dataset_id, window)
        self._write(self._path(aid, ".manifest.json"), manifest)
        return _summary(model, manifest)

    def get_model(self, aid: Aid) -> dict[str, Any]:
        """Summary of the fitted model (404 when not fitted)."""
        model, manifest = self._model(aid)
        return _summary(model, manifest)

    def post_scan(self, dataset_id: str, aid: Aid, request: ScanRequest) -> dict[str, Any]:
        """Scan the window with the fitted model: events, counts and a downsampled series."""
        config = _config_or_422(self.get_anomaly(aid))
        model, _ = self._model(aid)
        if model.tags != config.tags:
            raise HTTPException(status_code=422, detail="tags: model is stale, fit it again")
        t_s, x, _ = self._binned(dataset_id, config, request)
        result = scan(model, t_s, x, None, config)
        return {
            "events": [_event_record(model, event, x) for event in result.events],
            "n_valid": result.n_valid,
            "n_skipped": result.n_skipped,
            "skipped_reasons": result.skipped_reasons,
            "series": _series(model, t_s, x, request.max_points),
        }

    def _path(self, aid: str, suffix: str) -> Path:
        """File of one id (``aid`` was checked against AID_PATTERN by the route)."""
        return self.folder / f"{aid}{suffix}"

    def _model(self, aid: str) -> tuple[PcaModel, dict[str, Any]]:
        """The stored model and its manifest (404 when the detector is not fitted)."""
        model_path = self._path(aid, ".model.json")
        manifest_path = self._path(aid, ".manifest.json")
        if not (model_path.is_file() and manifest_path.is_file()):
            raise HTTPException(status_code=404, detail=f"model not fitted: {aid}")
        model = PcaModel.from_dict(json.loads(model_path.read_text(encoding="utf-8")))
        return model, json.loads(manifest_path.read_text(encoding="utf-8"))

    def _binned(
        self, dataset_id: str, config: AnomalyConfig, window: WindowRequest
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Bin start times, bin means (bins by tags, NaN if no valid sample) and bad-bin flags.

        A sample is invalid when its value is not finite or its quality code is not 0.
        """
        t_s, columns = self.load_seconds(dataset_id)
        quality = self.load_quality(dataset_id)
        missing = [tag for tag in config.tags if tag not in columns]
        if missing:
            raise HTTPException(status_code=404, detail=f"unknown tags: {missing}")
        keep = _window_mask(t_s, window)
        t0, period = float(t_s[keep][0]), config.sample_period_s
        bins = ((t_s[keep] - t0) // period).astype(int)
        n_bins = int(bins[-1]) + 1
        x = np.full((n_bins, len(config.tags)), np.nan)
        for j, tag in enumerate(config.tags):
            good = np.isfinite(columns[tag][keep]) & (quality[tag][keep] == 0)
            x[:, j] = _bin_means(bins, columns[tag][keep], good, n_bins)
        return t0 + period * np.arange(n_bins), x, np.isnan(x).any(axis=1)

    @staticmethod
    def _write(path: Path, document: dict[str, Any]) -> None:
        """Write a JSON file so a reader never sees half of it (temporary file, then replace)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)


def build_anomaly_router(
    root: Path, load_seconds: SecondsLoader, load_quality: QualityLoader
) -> APIRouter:
    """Routes for anomaly configs and models under ``root`` and for fit/scan on its datasets.

    Args:
        root: The data root; everything is written below ``<root>/_anomaly``.
        load_seconds: Reads a dataset into (time in seconds, columns by tag), 404 if unknown.
        load_quality: Quality codes by tag of a dataset (0 = good), aligned with the columns.
    """
    router = APIRouter()
    endpoints = _AnomalyEndpoints(root, load_seconds, load_quality)
    one, on_dataset = "/anomaly/{aid}", "/datasets/{dataset_id}/anomaly/{aid}"
    table: list[tuple[str, str, Callable[..., Any]]] = [
        ("/anomaly", "GET", endpoints.list_anomalies),
        (one, "GET", endpoints.get_anomaly),
        (one, "PUT", endpoints.put_anomaly),
        (f"{one}/model", "GET", endpoints.get_model),
        (f"{on_dataset}/fit", "POST", endpoints.post_fit),
        (f"{on_dataset}/scan", "POST", endpoints.post_scan),
    ]
    for path, method, handler in table:
        router.add_api_route(path, handler, methods=[method])
    return router


def _config_or_422(document: dict[str, Any]) -> AnomalyConfig:
    """The validated config, or HTTP 422 with the AnomalyConfigError message."""
    try:
        return load_config(document)
    except AnomalyConfigError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _window_mask(t_s: np.ndarray, window: WindowRequest) -> np.ndarray:
    """Samples inside the window (422 when it is reversed or holds no sample)."""
    low = -np.inf if window.start_s is None else window.start_s
    high = np.inf if window.end_s is None else window.end_s
    if low > high:
        raise HTTPException(status_code=422, detail="start_s: must not exceed end_s")
    keep: np.ndarray = (t_s >= low) & (t_s <= high)
    if not keep.any():
        raise HTTPException(status_code=422, detail="no samples in the requested window")
    return keep


def _bin_means(bins: np.ndarray, values: np.ndarray, good: np.ndarray, n_bins: int) -> np.ndarray:
    """Mean of the good samples per bin; NaN where a bin has none."""
    sums = np.bincount(bins, weights=np.where(good, values, 0.0), minlength=n_bins)
    counts = np.bincount(bins, weights=good.astype(float), minlength=n_bins)
    means: np.ndarray = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
    return means


def _manifest(
    config: AnomalyConfig, model: PcaModel, dataset_id: str, window: dict[str, float]
) -> dict[str, Any]:
    """Provenance of a fitted model (minimal manifest in the spirit of ADR 004)."""
    return {
        "kind": MODEL_KIND,
        "config_id": config.id,
        "dataset_id": dataset_id,
        "model_sha256": model.sha256(),
        "window": window,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _summary(model: PcaModel, manifest: dict[str, Any]) -> dict[str, Any]:
    """The model figures the UI shows: k, variance shares, limits, hash and training window."""
    shares = model.eigenvalues / model.eigenvalues.sum()
    return {
        "k": model.k,
        "n_train": model.n_train,
        "explained_variance": shares.tolist(),
        "cumulative_variance": np.cumsum(shares).tolist(),
        "t2_limit": model.t2_limit,
        "spe_limit": model.spe_limit,
        "spe_limit_method": model.spe_limit_method,
        "sha256": manifest["model_sha256"],
        "window": manifest["window"],
        "dataset_id": manifest["dataset_id"],
        "created_utc": manifest["created_utc"],
    }


def _event_record(model: PcaModel, event: AnomalyEvent, x: np.ndarray) -> dict[str, Any]:
    """An event as JSON with the tag contributions at its peak."""
    record = dataclasses.asdict(event)
    record["contributions"] = model.contributions(x[event.peak_index])
    return record


def _series(model: PcaModel, t_s: np.ndarray, x: np.ndarray, max_points: int) -> dict[str, Any]:
    """T2 and SPE over time, max-pooled to ``max_points`` (peaks kept); NaN becomes null."""
    count = min(max_points, len(t_s))
    starts = np.unique(np.linspace(0, len(t_s), count, endpoint=False).astype(int))
    return {
        "t_s": t_s[starts].tolist(),
        "t2": _pooled(model.t2(x), starts),
        "spe": _pooled(model.spe(x), starts),
        "t2_limit": model.t2_limit,
        "spe_limit": model.spe_limit,
    }


def _pooled(values: np.ndarray, starts: np.ndarray) -> list[float | None]:
    """Maximum of each chunk beginning at ``starts`` (NaN ignored); None for all-NaN chunks."""
    pooled = np.fmax.reduceat(values, starts)
    return [None if np.isnan(v) else float(v) for v in pooled]
