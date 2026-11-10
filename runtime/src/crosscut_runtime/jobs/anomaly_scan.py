"""
Live anomaly scan job (Phase 1 #44, module 3).
Scans the latest window of the runtime history with the PCA model that the anomaly API
fitted and stored (<data root>/_anomaly/<id>.model.json), using the offline detector, so
live and offline share one code path. The job never trains a model by itself.
"""

import json
import math
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from crosscut_anomaly import config, detect, pca_model
from crosscut_anomaly.config import AnomalyConfigError

from crosscut_runtime.history import HistoryStore

ANOMALY_DIR = "_anomaly"
NO_MODEL = "no_trained_model"


def _aligned_matrix(
    history: HistoryStore, tags: list[str], since_ts: float | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """
    Query every tag since ``since_ts``, keep only timestamps present for ALL tags (intersection).
    
    Returns:
        A tuple (t_array, x_array) where t_array is 1D timestamps and
        x_array is 2D (samples x tags) of values, aligned and sorted by time.
    """
    tag_series = [history.query(tag, since_ts) for tag in tags]
    if not tag_series:
        return np.array([]), np.array([[]])
    
    # Find common timestamps across all tags
    common_ts = set(ts for ts, _ in tag_series[0])
    for series in tag_series[1:]:
        common_ts.intersection_update(ts for ts, _ in series)
    
    sorted_ts = sorted(common_ts)
    if not sorted_ts:
        return np.array([]), np.array([[]]).reshape(0, len(tags))
    
    t_array = np.array(sorted_ts, dtype=float)
    x_array = np.zeros((len(sorted_ts), len(tags)), dtype=float)
    
    for j, series in enumerate(tag_series):
        # Convert list of tuples to dict, checking for duplicate timestamps
        series_dict = {}
        for ts, val in series:
            if ts in series_dict:
                raise ValueError(f"Duplicate timestamp {ts} found in history for tag {tags[j]}")
            series_dict[ts] = val
            
        for i, ts in enumerate(sorted_ts):
            x_array[i, j] = series_dict[ts]
            
    return t_array, x_array


def _extract_events(result: Any) -> list[dict[str, Any]]:
    """Convert scan events to plain dictionaries for the JSON output."""
    events = []
    for ev in result.events:
        events.append({
            "kind": ev.kind,
            "start_s": ev.start_s,
            "end_s": ev.end_s,
            "closed": ev.closed,
            "exceeded": ev.exceeded,
            "top_spe_tags": ev.top_spe_tags,
            "top_t2_tags": ev.top_t2_tags,
            "stuck_tag": ev.stuck_tag,
        })
    return events


class AnomalyScanJob:
    """
    Periodic job that samples live tags, stores them, and scans them with the stored PCA model.
    """

    def __init__(
        self,
        job_doc: dict[str, Any],
        connector: Any,
        history: HistoryStore,
        clock: Callable[[], float] = time.time,
        model_dir: Path | None = None,
    ) -> None:
        """Initialize the job; ``model_dir`` is the ``_anomaly`` folder of the data root."""
        self._id = job_doc["id"]
        self._tags = job_doc["tags"]
        self._period_s = float(job_doc.get("period_s", 60.0))
        self._window_s = float(job_doc.get("window_s", 3600.0))
        self._connector = connector
        self._history = history
        self._clock = clock
        self._dir = model_dir
        self._quality: dict[tuple[str, float], int] = {}

        if len(self._tags) < 2:
            raise ValueError("anomaly_scan needs at least 2 tags")

    def _sample_ts(self, stamp: str, now: float) -> float:
        """Source timestamp floored to the sample period; ``now`` when it cannot be parsed."""
        try:
            ts = datetime.fromisoformat(stamp).timestamp()
        except (TypeError, ValueError):
            ts = now
        return math.floor(ts / self._period_s) * self._period_s

    def _sample_live(self, now: float) -> None:
        """Read live tags; append finite values to history and remember their quality."""
        live_data = self._connector.read_live(self._tags)
        rows = []
        for tag in self._tags:
            live_val = live_data.get(tag)
            if live_val is None or live_val.value is None:
                continue
            if math.isfinite(live_val.value):
                ts = self._sample_ts(live_val.timestamp_utc, now)
                rows.append((tag, ts, live_val.value))
                self._quality[(tag, ts)] = int(live_val.quality)
        if rows:
            self._history.append(rows)

    def _quality_matrix(self, t: np.ndarray) -> np.ndarray:
        """Quality code per row and tag (0 when unknown, e.g. rows stored before a restart)."""
        q = np.zeros((len(t), len(self._tags)))
        for j, tag in enumerate(self._tags):
            for i, ts in enumerate(t):
                q[i, j] = self._quality.get((tag, float(ts)), 0)
        return q

    def _prune_quality(self, since: float) -> None:
        """Drop remembered quality codes older than the scan window."""
        self._quality = {k: v for k, v in self._quality.items() if k[1] >= since}

    def _load_config(self) -> config.AnomalyConfig:
        """The stored detector config, or one built from the job doc (detector defaults)."""
        path = self._dir / f"{self._id}.json" if self._dir else None
        if path is not None and path.is_file():
            return config.load_config(json.loads(path.read_text(encoding="utf-8")))
        return config.load_config({
            "schema_version": "1.0.0",
            "id": self._id,
            "tags": self._tags,
            "mode": "advisory",
            "sample_period_s": self._period_s,
        })

    def _load_model(self) -> pca_model.PcaModel | None:
        """The model fitted through the anomaly API, or None when none was stored."""
        path = self._dir / f"{self._id}.model.json" if self._dir else None
        if path is None or not path.is_file():
            return None
        return pca_model.PcaModel.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def _prepare(
        self,
    ) -> tuple[config.AnomalyConfig, pca_model.PcaModel] | dict[str, Any]:
        """Config and model, or an error response when they are missing or unusable."""
        try:
            cfg = self._load_config()
            model = self._load_model()
        except (AnomalyConfigError, pca_model.PcaModelError, OSError, ValueError, KeyError) as err:
            return self._error_response(0, f"invalid_model_or_config: {err}")
        if model is None:
            return self._error_response(0, NO_MODEL)
        if list(model.tags) != list(cfg.tags) or list(cfg.tags) != list(self._tags):
            return self._error_response(0, "stale_model: tags differ, fit it again")
        return cfg, model

    def run(self) -> dict[str, Any]:
        """Execute one cycle of sampling and scanning with the stored model."""
        now = self._clock()
        self._sample_live(now)
        since = now - self._window_s
        self._prune_quality(since)
        prepared = self._prepare()
        if isinstance(prepared, dict):
            return prepared
        cfg, model = prepared
        t, x = _aligned_matrix(self._history, self._tags, since)
        result = detect.scan(model, t, x, self._quality_matrix(t), cfg)
        return {
            "samples": len(t),
            "kpi": None,
            "scan": {
                "status": "ok",
                "train_rows": model.n_train,
                "n_valid": result.n_valid,
                "events": _extract_events(result),
            },
        }

    @staticmethod
    def _error_response(total: int, reason: str) -> dict[str, Any]:
        """Format an error response (no model, stale model or bad config)."""
        scan = {"status": "error", "reason": reason, "events": []}
        return {"samples": total, "kpi": None, "scan": scan}
