"""HTTP routes of the PLS soft sensor (advisory): configs, lab results, fit, model, run.

Everything lives in ``<data root>/_softsensor``: ``<sid>.json`` (config), ``<sid>.lab.csv`` (lab
results, normalised to ``sample_time,value`` in seconds from the first dataset sample),
``<sid>.model.json`` and ``<sid>.manifest.json``. Nothing else is written and nothing reaches a
plant: the soft sensor only advises.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import numpy as np
from crosscut_softsensor.bias import BiasTrackerError
from crosscut_softsensor.config import SoftSensorConfig, SoftSensorConfigError, load_config
from crosscut_softsensor.features import FeatureError, build_lagged, feature_names
from crosscut_softsensor.pls import PlsModel, PlsModelError, fit_pls
from crosscut_softsensor.runner import LabResults, SoftSensorRun, run_softsensor
from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from crosscut_api.anomaly_routes import WindowRequest, _bin_means, _window_mask

DIR_NAME = "_softsensor"
SID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
MAX_CSV_BYTES = 1_000_000
DEFAULT_MAX_POINTS = 1500
MODEL_KIND = "softsensor_pls"
CATEGORIES = ("ok", "missing_input", "out_of_range", "extrapolation")
Sid = Annotated[str, PathParam(pattern=SID_PATTERN)]
SecondsLoader = Callable[[str], tuple[np.ndarray, dict[str, Any]]]
QualityLoader = Callable[[str], dict[str, np.ndarray]]


class LabUpload(BaseModel):
    """Lab CSV text; ISO sample times are made relative to ``origin_iso`` (the first sample)."""

    csv_text: str
    origin_iso: str | None = None


class FitRequest(BaseModel):
    """Training cut: only lab results available before ``train_end_s`` are used."""

    train_end_s: float | None = None


class RunRequest(WindowRequest):
    """Window to run plus the size limit of the returned series."""

    max_points: Annotated[int, Field(ge=2, le=100_000)] = DEFAULT_MAX_POINTS


def _parse_time(token: str, origin: datetime | None, line: int) -> float:
    """Seconds from a number or, with an origin, from an ISO time."""
    text = token.strip()
    try:
        return float(text)
    except ValueError:
        pass
    if origin is None:
        raise HTTPException(
            status_code=422, detail=f"line {line}: ISO sample_time needs origin_iso"
        )
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail=f"line {line}: bad sample_time {token!r}"
        ) from error
    return (_aware(moment) - origin).total_seconds()


def _aware(moment: datetime) -> datetime:
    """The moment with UTC attached when it has no zone."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _origin(origin_iso: str | None) -> datetime | None:
    """The parsed origin time (422 when it is not an ISO time)."""
    if origin_iso is None:
        return None
    try:
        return _aware(datetime.fromisoformat(origin_iso.replace("Z", "+00:00")))
    except ValueError as error:
        raise HTTPException(status_code=422, detail="origin_iso: not an ISO time") from error


def _delimiter(header: str) -> str:
    """The field delimiter of a CSV header line: semicolon, tab or comma."""
    return ";" if ";" in header else "\t" if "\t" in header else ","


def _float_cell(cell: str, delimiter: str, line: int) -> float:
    """A finite number (decimal comma accepted unless the comma is the delimiter)."""
    text = cell.strip()
    try:
        number = float(text.replace(",", ".") if delimiter != "," else text)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"line {line}: bad value {cell!r}") from error
    if not np.isfinite(number):
        raise HTTPException(status_code=422, detail=f"line {line}: value is not finite")
    return number


def parse_lab_csv(text: str, origin_iso: str | None = None) -> list[tuple[float, float]]:
    """Rows (seconds, value) sorted by time from lab CSV text with columns sample_time, value."""
    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise HTTPException(status_code=422, detail="csv_text: larger than 1 MB")
    lines = [line for line in text.lstrip("﻿").splitlines() if line.strip()]
    if not lines:
        raise HTTPException(status_code=422, detail="csv_text: empty")
    delimiter = _delimiter(lines[0])
    rows = list(csv.reader(lines, delimiter=delimiter))
    header = [cell.strip().lower() for cell in rows[0]]
    if "sample_time" not in header or "value" not in header:
        raise HTTPException(status_code=422, detail="csv_text: columns sample_time and value")
    origin, ti, vi = _origin(origin_iso), header.index("sample_time"), header.index("value")
    parsed = [
        (_parse_time(row[ti], origin, n), _float_cell(row[vi], delimiter, n))
        for n, row in enumerate(rows[1:], start=2)
        if len(row) > max(ti, vi)
    ]
    if len(parsed) != len(rows) - 1:
        raise HTTPException(status_code=422, detail="csv_text: a row has too few columns")
    if not parsed:
        raise HTTPException(status_code=422, detail="csv_text: no data rows")
    return sorted(parsed)


def _lab_csv(rows: list[tuple[float, float]]) -> str:
    """Normalised CSV text of lab rows."""
    return "sample_time,value\n" + "".join(f"{t!r},{v!r}\n" for t, v in rows)


def _lab_summary(rows: list[tuple[float, float]]) -> dict[str, Any]:
    """Count, first/last time and the rows themselves."""
    return {
        "count": len(rows),
        "first_s": rows[0][0],
        "last_s": rows[-1][0],
        "rows": [{"t_s": t, "value": v} for t, v in rows],
    }


class _SoftSensorEndpoints:
    """The soft sensor route handlers, bound to the data root and the dataset loaders."""

    def __init__(
        self, root: Path, load_seconds: SecondsLoader, load_quality: QualityLoader
    ) -> None:
        self.folder = root / DIR_NAME
        self.load_seconds = load_seconds
        self.load_quality = load_quality

    def list_softsensors(self) -> list[str]:
        """Ids of the saved configurations, sorted."""
        if not self.folder.is_dir():
            return []
        return sorted(p.stem for p in self.folder.glob("*.json") if "." not in p.stem)

    def get_softsensor(self, sid: Sid) -> dict[str, Any]:
        """One saved configuration as stored (404 when unknown)."""
        path = self._path(sid, ".json")
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"unknown soft sensor: {sid}")
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return document

    def put_softsensor(self, sid: Sid, document: dict[str, Any]) -> dict[str, Any]:
        """Validate and save a configuration (422 with the reason when not acceptable)."""
        config = _config_or_422(document)
        if config.id != sid:
            raise HTTPException(status_code=422, detail=f"id: {config.id!r} does not match {sid!r}")
        _write_text(self._path(sid, ".json"), json.dumps(document, indent=2, ensure_ascii=False))
        return document

    def post_lab(self, sid: Sid, upload: LabUpload) -> dict[str, Any]:
        """Parse, normalise and store the lab CSV; return what was stored."""
        self.get_softsensor(sid)
        rows = parse_lab_csv(upload.csv_text, upload.origin_iso)
        _write_text(self._path(sid, ".lab.csv"), _lab_csv(rows))
        return _lab_summary(rows)

    def get_lab(self, sid: Sid) -> dict[str, Any]:
        """The stored lab results (404 when none were uploaded)."""
        return _lab_summary(self._lab_rows(sid))

    def post_fit(self, dataset_id: str, sid: Sid, request: FitRequest) -> dict[str, Any]:
        """Fit PLS against the lab results known before ``train_end_s``; store model, manifest."""
        config = _config_or_422(self.get_softsensor(sid))
        rows = self._lab_rows(sid)
        t_s, columns = self._binned(dataset_id, config, WindowRequest())
        end = float(t_s[-1]) if request.train_end_s is None else request.train_end_s
        before = t_s < end
        if not before.any():
            raise HTTPException(status_code=422, detail="train_end_s: no samples before it")
        x, _ = build_lagged(columns, config.input_tags, config.lags_s, config.sample_period_s)
        y = _training_target(t_s[before], rows, config.lab_delay_s, end)
        model = _fit_or_422(x[before], y, config)
        window = {"start_s": float(t_s[0]), "end_s": end}
        manifest = _manifest(config, model, dataset_id, window)
        manifest["r2_train"] = _r2(model, x[before], y)
        _write_text(self._path(sid, ".model.json"), json.dumps(model.to_dict(), indent=2))
        _write_text(self._path(sid, ".manifest.json"), json.dumps(manifest, indent=2))
        return _summary(model, manifest, manifest["r2_train"])

    def get_model(self, sid: Sid) -> dict[str, Any]:
        """Summary of the fitted model (404 when not fitted)."""
        model, manifest = self._model(sid)
        return _summary(model, manifest, manifest.get("r2_train"))

    def post_run(self, dataset_id: str, sid: Sid, request: RunRequest) -> dict[str, Any]:
        """Run the fitted model over the window with lab bias tracking."""
        config = _config_or_422(self.get_softsensor(sid))
        model, _ = self._model(sid)
        if model.feature_names != tuple(feature_names(config.input_tags, config.lags_s)) or (
            model.sample_period_s != config.sample_period_s
        ):
            raise HTTPException(status_code=422, detail="input_tags: model is stale, fit it again")
        t_s, columns = self._binned(dataset_id, config, request)
        rows = self._lab_rows(sid)
        labs = LabResults.with_delay(
            np.array([r[0] for r in rows]), np.array([r[1] for r in rows]), config.lab_delay_s
        )
        result = _run_or_422(model, config, t_s, columns, labs)
        return _run_document(result, rows, request.max_points)

    def _path(self, sid: str, suffix: str) -> Path:
        """File of one id (``sid`` was checked against SID_PATTERN by the route)."""
        return self.folder / f"{sid}{suffix}"

    def _lab_rows(self, sid: str) -> list[tuple[float, float]]:
        """The stored lab rows (404 when the sensor is unknown or has no lab file)."""
        self.get_softsensor(sid)
        path = self._path(sid, ".lab.csv")
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"no lab results uploaded: {sid}")
        return parse_lab_csv(path.read_text(encoding="utf-8"))

    def _model(self, sid: str) -> tuple[PlsModel, dict[str, Any]]:
        """The stored model and its manifest (404 when not fitted)."""
        model_path = self._path(sid, ".model.json")
        manifest_path = self._path(sid, ".manifest.json")
        if not (model_path.is_file() and manifest_path.is_file()):
            raise HTTPException(status_code=404, detail=f"model not fitted: {sid}")
        model = PlsModel.from_dict(json.loads(model_path.read_text(encoding="utf-8")))
        return model, json.loads(manifest_path.read_text(encoding="utf-8"))

    def _binned(
        self, dataset_id: str, config: SoftSensorConfig, window: WindowRequest
    ) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """Bin start times and bin means by input tag (NaN where no good sample)."""
        t_s, columns = self.load_seconds(dataset_id)
        quality = self.load_quality(dataset_id)
        missing = [tag for tag in config.input_tags if tag not in columns]
        if missing:
            raise HTTPException(status_code=422, detail=f"unknown tags: {missing}")
        keep = _window_mask(t_s, window)
        t0, period = float(t_s[keep][0]), config.sample_period_s
        bins = ((t_s[keep] - t0) // period).astype(int)
        n_bins = int(bins[-1]) + 1
        means = {}
        for tag in config.input_tags:
            good = np.isfinite(columns[tag][keep]) & (quality[tag][keep] == 0)
            means[tag] = _bin_means(bins, columns[tag][keep], good, n_bins)
        return t0 + period * np.arange(n_bins), means


def build_softsensor_router(
    root: Path, load_seconds: SecondsLoader, load_quality: QualityLoader
) -> APIRouter:
    """Routes for soft sensor configs, lab data and models under ``root`` and fit/run on datasets.

    Args:
        root: The data root; everything is written below ``<root>/_softsensor``.
        load_seconds: Reads a dataset into (time in seconds, columns by tag), 404 if unknown.
        load_quality: Quality codes by tag of a dataset (0 = good), aligned with the columns.
    """
    router = APIRouter()
    endpoints = _SoftSensorEndpoints(root, load_seconds, load_quality)
    one, on_dataset = "/softsensor/{sid}", "/datasets/{dataset_id}/softsensor/{sid}"
    table: list[tuple[str, str, Callable[..., Any]]] = [
        ("/softsensor", "GET", endpoints.list_softsensors),
        (one, "GET", endpoints.get_softsensor),
        (one, "PUT", endpoints.put_softsensor),
        (f"{one}/lab", "POST", endpoints.post_lab),
        (f"{one}/lab", "GET", endpoints.get_lab),
        (f"{one}/model", "GET", endpoints.get_model),
        (f"{on_dataset}/fit", "POST", endpoints.post_fit),
        (f"{on_dataset}/run", "POST", endpoints.post_run),
    ]
    for path, method, handler in table:
        router.add_api_route(path, handler, methods=[method])
    return router


def _write_text(path: Path, text: str) -> None:
    """Write a file so a reader never sees half of it (temporary file, then replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _config_or_422(document: dict[str, Any]) -> SoftSensorConfig:
    """The validated config, or HTTP 422 with the SoftSensorConfigError message."""
    try:
        return load_config(document)
    except SoftSensorConfigError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _training_target(
    t_bins: np.ndarray, rows: list[tuple[float, float]], delay_s: float, end_s: float
) -> np.ndarray:
    """Lab value on the bin holding its sample time; only results sampled and available < end."""
    y = np.full(len(t_bins), np.nan)
    for t, value in rows:
        row = int(np.searchsorted(t_bins, t, side="right")) - 1
        if row >= 0 and t < end_s and t + delay_s < end_s:
            y[row] = value
    return y


def _fit_or_422(x: np.ndarray, y: np.ndarray, config: SoftSensorConfig) -> PlsModel:
    """Fit the model; a fit problem becomes HTTP 422 with its message."""
    try:
        return fit_pls(x, y, config, x_domain=x)
    except (PlsModelError, FeatureError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _run_or_422(
    model: PlsModel,
    config: SoftSensorConfig,
    t_s: np.ndarray,
    columns: dict[str, np.ndarray],
    labs: LabResults,
) -> SoftSensorRun:
    """Run the soft sensor; a model or tracker problem becomes HTTP 422."""
    try:
        return run_softsensor(model, config, t_s, columns, labs)
    except (PlsModelError, FeatureError, BiasTrackerError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _r2(model: PlsModel, x: np.ndarray, y: np.ndarray) -> float | None:
    """Coefficient of determination of the model on the training rows."""
    est = model.predict(x)
    ok = np.isfinite(est) & np.isfinite(y)
    total = float(np.sum((y[ok] - y[ok].mean()) ** 2))
    return _num(1.0 - float(np.sum((y[ok] - est[ok]) ** 2)) / total) if total > 0 else None


def _manifest(
    config: SoftSensorConfig, model: PlsModel, dataset_id: str, window: dict[str, float]
) -> dict[str, Any]:
    """Provenance of a fitted model (minimal manifest in the spirit of ADR 004)."""
    return {
        "kind": MODEL_KIND,
        "config_id": config.id,
        "dataset_id": dataset_id,
        "model_sha256": model.sha256(),
        "config_sha256": hashlib.sha256(repr(config).encode("utf-8")).hexdigest(),
        "window": window,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _summary(model: PlsModel, manifest: dict[str, Any], r2: float | None) -> dict[str, Any]:
    """The model figures the UI shows."""
    return {
        "n_components": model.n_components,
        "cv_rmse": [_num(v) for v in model.cv_rmse],
        "chosen_components": model.chosen_components,
        "cv_sigma": _num(model.cv_sigma),
        "n_train": model.n_train,
        "domain_rows": model.domain_rows,
        "r2_train": r2,
        "sha256": manifest["model_sha256"],
        "window": manifest["window"],
        "dataset_id": manifest["dataset_id"],
        "created_utc": manifest["created_utc"],
    }


def _num(value: float) -> float | None:
    """A float for JSON, None when it is NaN or infinite."""
    return float(value) if np.isfinite(value) else None


def _values(values: np.ndarray, picks: np.ndarray) -> list[float | None]:
    """The values at ``picks`` with NaN as None."""
    return [_num(v) for v in values[picks]]


def _episodes(t_s: np.ndarray, flags: np.ndarray) -> list[dict[str, float]]:
    """Start and end time of every run of True flags."""
    padded = np.concatenate(([False], flags, [False])).astype(int)
    edges = np.flatnonzero(np.diff(padded))
    return [
        {"start_s": float(t_s[a]), "end_s": float(t_s[b - 1])}
        for a, b in zip(edges[::2], edges[1::2], strict=True)
    ]


def _run_document(
    run: SoftSensorRun, labs: list[tuple[float, float]], max_points: int
) -> dict[str, Any]:
    """Downsampled series, validity counts, drift episodes, lab points in the window, latest."""
    n = len(run.t_s)
    picks = np.unique(np.linspace(0, n, min(max_points, n), endpoint=False).astype(int))
    counts = {c: run.validity.count(c) for c in CATEGORIES}
    inside = [{"t_s": t, "value": v} for t, v in labs if run.t_s[0] <= t <= run.t_s[-1]]
    return {
        "series": {
            "t_s": run.t_s[picks].tolist(),
            "estimate": _values(run.estimate, picks),
            "corrected": _values(run.corrected, picks),
            "bias": _values(run.bias, picks),
            "drift": run.drift[picks].tolist(),
            "validity": [run.validity[i] for i in picks],
        },
        "validity_counts": counts,
        "drift_episodes": _episodes(run.t_s, run.drift),
        "lab_points": inside,
        "n_lab_used": run.n_lab_used,
        "latest": {
            "t_s": float(run.t_s[-1]),
            "estimate": _num(run.estimate[-1]),
            "corrected": _num(run.corrected[-1]),
            "bias": _num(run.bias[-1]),
            "drift": bool(run.drift[-1]),
            "validity": run.validity[-1],
        },
    }
