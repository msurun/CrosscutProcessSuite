"""
Live anomaly scan job (Phase 1 #44, module 3).
Learns a PCA model from the runtime history store, then scans the latest
window with the offline detector, so live and offline share one code path.
"""

import math
import time
from collections.abc import Callable
from typing import Any

import numpy as np
from crosscut_anomaly import config, detect, pca_model

from crosscut_runtime.history import HistoryStore

REFIT_EVERY_S = 3600.0
MIN_TRAIN_ROWS_BASE = 60
MIN_TRAIN_ROWS_PER_TAG = 10


def _aligned_matrix(
    history: HistoryStore, tags: list[str]
) -> tuple[np.ndarray, np.ndarray]:
    """
    Query every tag, keep only timestamps present for ALL tags (intersection).
    
    Returns:
        A tuple (t_array, x_array) where t_array is 1D timestamps and
        x_array is 2D (samples x tags) of values, aligned and sorted by time.
    """
    tag_series = [history.query(tag) for tag in tags]
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
    Periodic job that samples live tags, stores them, and runs PCA anomaly detection.
    """

    def __init__(
        self,
        job_doc: dict[str, Any],
        connector: Any,
        history: HistoryStore,
        clock: Callable[[], float] = time.time
    ) -> None:
        """Initialize the anomaly scan job."""
        self._id = job_doc["id"]
        self._tags = job_doc["tags"]
        self._period_s = float(job_doc.get("period_s", 60.0))
        self._window_s = float(job_doc.get("window_s", 3600.0))
        self._connector = connector
        self._history = history
        self._clock = clock
        self._model: Any = None
        self._last_fit_ts = 0.0

        if len(self._tags) < 2:
            raise ValueError("anomaly_scan needs at least 2 tags")

    def _sample_live(self, now: float) -> None:
        """Read live tags and append finite values to history."""
        live_data = self._connector.read_live(self._tags)
        rows = []
        for tag in self._tags:
            live_val = live_data.get(tag)
            if live_val is not None and live_val.value is not None:
                if math.isfinite(live_val.value):
                    rows.append((tag, now, live_val.value))
        if rows:
            self._history.append(rows)

    def _build_config(self) -> config.AnomalyConfig:
        """Construct the validated configuration for the anomaly detector."""
        doc = {
            "schema_version": "1.0.0",
            "id": self._id,
            "tags": self._tags,
            "mode": "advisory",
            "sample_period_s": self._period_s,
            "dynamic_lags": 0,
            "stuck_samples": 0,
        }
        return config.load_config(doc)

    def _split_data(
        self, t: np.ndarray, x: np.ndarray, now: float
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Split historical data into training and scanning windows."""
        cutoff_ts = now - self._window_s
        scan_mask = t >= cutoff_ts
        train_mask = t < cutoff_ts
        return t[train_mask], x[train_mask], t[scan_mask], x[scan_mask]

    def _update_model(
        self, train_x: np.ndarray, cfg: config.AnomalyConfig, now: float
    ) -> str | None:
        """Refit the model if necessary. Returns an error reason or None on success."""
        if self._model is not None and (now - self._last_fit_ts) < REFIT_EVERY_S:
            return None

        try:
            self._model = pca_model.fit_from_config(train_x, cfg)
            self._last_fit_ts = now
            return None
        except pca_model.PcaModelError as err:
            return str(err)

    def run(self) -> dict[str, Any]:
        """Execute one cycle of sampling and scanning."""
        now = self._clock()
        self._sample_live(now)
        
        t, x = _aligned_matrix(self._history, self._tags)
        cfg = self._build_config()
        t_train, x_train, t_scan, x_scan = self._split_data(t, x, now)
        
        n_train = len(t_train)
        needed = max(MIN_TRAIN_ROWS_BASE, MIN_TRAIN_ROWS_PER_TAG * len(self._tags))
        
        if n_train < needed:
            return self._learning_response(len(t), n_train, needed, None)
            
        err_reason = self._update_model(x_train, cfg, now)
        if err_reason is not None:
            return self._learning_response(len(t), n_train, needed, err_reason)
            
        result = detect.scan(self._model, t_scan, x_scan, None, cfg)
        return {
            "samples": len(t),
            "kpi": None,
            "scan": {
                "status": "ok",
                "train_rows": n_train,
                "n_valid": result.n_valid,
                "events": _extract_events(result),
            }
        }

    def _learning_response(
        self, total: int, n_train: int, needed: int, reason: str | None
    ) -> dict[str, Any]:
        """Format a learning response when training data or fit fails."""
        resp = {
            "status": "learning",
            "train_rows": n_train,
            "needed": needed,
            "events": [],
        }
        if reason:
            resp["reason"] = reason
        return {"samples": total, "kpi": None, "scan": resp}
