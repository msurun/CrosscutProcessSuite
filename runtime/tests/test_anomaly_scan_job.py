"""Tests of AnomalyScanJob: learning gate, live scan with events, and tag-count validation.

A replay connector returns one row of a fixed correlated matrix per read, and a fake clock
advances 60 s per run, so the job runs its real sampling, history and PCA code deterministically.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from crosscut_anomaly import detect
from crosscut_anomaly.pca_model import fit_pca
from crosscut_connectors.base import LiveValue
from crosscut_runtime.history import HistoryStore
from crosscut_runtime.jobs.anomaly_scan import AnomalyScanJob

TAGS = ["FIC101.pv", "FIC101.sp", "FIC101.out"]
PERIOD_S = 60.0
WINDOW_S = 3000.0
START_S = 1_700_000_000.0
TICKS = 300
SHIFT_TICKS = 60
SHIFT_SIZE = 5.0


class TickClock:
    """A clock the test moves by hand; calling it returns the current epoch seconds."""

    def __init__(self) -> None:
        """Start the clock at a fixed epoch time."""
        self.now = START_S

    def __call__(self) -> float:
        """Return the current time in epoch seconds."""
        return self.now


class ReplayConnector:
    """A read_live source that returns the next row of a fixed matrix on every read."""

    def __init__(self, matrix: np.ndarray, bad_from: int | None = None) -> None:
        """Hold the matrix (rows = ticks, columns = TAGS), the read position, bad-quality start."""
        self._matrix = matrix
        self._row = 0
        self._bad_from = bad_from

    def read_live(self, tag_ids: list[str]) -> dict[str, LiveValue]:
        """Return the current row for every requested tag and advance to the next row."""
        values = self._matrix[self._row]
        self._row += 1
        stamp = datetime.fromtimestamp(START_S + (self._row - 1) * PERIOD_S, UTC).isoformat()
        bad = self._bad_from is not None and self._row > self._bad_from
        return {
            tag: LiveValue(
                value=float(values[TAGS.index(tag)]), quality=2 if bad else 0, timestamp_utc=stamp
            )
            for tag in tag_ids
        }


def _correlated_matrix(ticks: int, shift_last: float = 0.0) -> np.ndarray:
    """Three correlated noisy tags; tag 0 is raised by shift_last over the last SHIFT_TICKS rows."""
    rng = np.random.default_rng(7)
    latent = rng.normal(size=ticks)
    loadings = np.array([1.0, 0.8, -0.6])
    noise = rng.normal(scale=0.1, size=(ticks, len(TAGS)))
    matrix = latent[:, None] * loadings + noise
    if shift_last:
        matrix[-SHIFT_TICKS:, 0] += shift_last
    return matrix


def _job_doc(tags: list[str]) -> dict[str, Any]:
    """An anomaly_scan job document with the test period and window."""
    return {"id": "scan-1", "tags": tags, "period_s": PERIOD_S, "window_s": WINDOW_S}


def _store_model(tmp_path: Path, doc_extra: dict[str, Any] | None = None) -> Path:
    """Fit a model on a clean matrix and store it and its config like the anomaly API does."""
    folder = tmp_path / "_anomaly"
    folder.mkdir(exist_ok=True)
    doc = {
        "schema_version": "1.0.0", "id": "scan-1", "tags": TAGS, "mode": "advisory",
        "sample_period_s": PERIOD_S, **(doc_extra or {}),
    }
    (folder / "scan-1.json").write_text(json.dumps(doc), encoding="utf-8")
    model = fit_pca(_correlated_matrix(500), TAGS, 0.9, 0.99)
    (folder / "scan-1.model.json").write_text(json.dumps(model.to_dict()), encoding="utf-8")
    return folder


def _make_job(
    tmp_path: Path, matrix: np.ndarray, clock: TickClock, bad_from: int | None = None
) -> AnomalyScanJob:
    """An AnomalyScanJob reading the matrix, history and model store under tmp_path."""
    history = HistoryStore(tmp_path / "history.db")
    connector = ReplayConnector(matrix, bad_from)
    return AnomalyScanJob(_job_doc(TAGS), connector, history, clock, tmp_path / "_anomaly")


def _run_ticks(job: AnomalyScanJob, clock: TickClock, ticks: int) -> dict[str, Any]:
    """Run the job for some ticks, advancing the clock one period each; return the last result."""
    result: dict[str, Any] = {}
    for _ in range(ticks):
        result = job.run()
        clock.now += PERIOD_S
    return result


def test_scan_reports_no_trained_model_instead_of_self_training(tmp_path: Path) -> None:
    clock = TickClock()
    job = _make_job(tmp_path, _correlated_matrix(TICKS), clock)
    scan = _run_ticks(job, clock, TICKS)["scan"]
    assert scan["status"] == "error"
    assert scan["reason"] == "no_trained_model"
    assert scan["events"] == []
    assert not (tmp_path / "_anomaly" / "scan-1.model.json").exists()


def test_scan_is_ok_with_stored_model(tmp_path: Path) -> None:
    _store_model(tmp_path)
    clock = TickClock()
    job = _make_job(tmp_path, _correlated_matrix(TICKS), clock)
    scan = _run_ticks(job, clock, TICKS)["scan"]
    assert scan["status"] == "ok"
    assert scan["n_valid"] > 0
    assert scan["events"] == []


def test_anomaly_id_selects_the_stored_model(tmp_path: Path) -> None:
    _store_model(tmp_path)
    clock = TickClock()
    history = HistoryStore(tmp_path / "history.db")
    doc = {**_job_doc(TAGS), "id": "live-job", "anomaly_id": "scan-1"}
    connector = ReplayConnector(_correlated_matrix(TICKS), None)
    job = AnomalyScanJob(doc, connector, history, clock, tmp_path / "_anomaly")
    assert _run_ticks(job, clock, TICKS)["scan"]["status"] == "ok"


def test_sudden_shift_in_recent_ticks_produces_an_event(tmp_path: Path) -> None:
    _store_model(tmp_path)
    clock = TickClock()
    job = _make_job(tmp_path, _correlated_matrix(TICKS, shift_last=SHIFT_SIZE), clock)
    scan = _run_ticks(job, clock, TICKS)["scan"]
    assert scan["status"] == "ok"
    assert len(scan["events"]) >= 1


def test_live_quality_reaches_the_detector(tmp_path: Path) -> None:
    _store_model(tmp_path)
    clock = TickClock()
    job = _make_job(tmp_path, _correlated_matrix(TICKS, shift_last=SHIFT_SIZE), clock, bad_from=0)
    scan = _run_ticks(job, clock, TICKS)["scan"]
    assert scan["n_valid"] == 0
    assert scan["events"] == []


def test_history_rows_use_the_source_timestamp(tmp_path: Path) -> None:
    clock = TickClock()
    job = _make_job(tmp_path, _correlated_matrix(TICKS), clock)
    clock.now = START_S + 10_000.0
    job.run()
    rows = job._history.query(TAGS[0])
    assert [ts for ts, _ in rows] == [START_S - START_S % PERIOD_S]


def test_stuck_samples_comes_from_the_stored_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store_model(tmp_path, {"stuck_samples": 5})
    seen: list[int] = []
    real_scan = detect.scan

    def spy(model: Any, t: Any, x: Any, quality: Any, cfg: Any) -> Any:
        seen.append(cfg.stuck_samples)
        return real_scan(model, t, x, quality, cfg)

    monkeypatch.setattr(detect, "scan", spy)
    clock = TickClock()
    _run_ticks(_make_job(tmp_path, _correlated_matrix(TICKS), clock), clock, 3)
    assert seen == [5, 5, 5]


def test_stuck_samples_falls_back_to_detector_default(tmp_path: Path) -> None:
    _store_model(tmp_path)
    job = _make_job(tmp_path, _correlated_matrix(TICKS), TickClock())
    assert job._load_config().stuck_samples == 0


def test_history_query_is_bounded_to_the_scan_window(tmp_path: Path) -> None:
    _store_model(tmp_path)
    clock = TickClock()
    job = _make_job(tmp_path, _correlated_matrix(TICKS), clock)
    result = _run_ticks(job, clock, TICKS)
    assert result["samples"] <= WINDOW_S / PERIOD_S + 1
    assert result["samples"] < TICKS


def test_stale_model_tags_are_reported(tmp_path: Path) -> None:
    folder = _store_model(tmp_path)
    doc = json.loads((folder / "scan-1.json").read_text(encoding="utf-8"))
    doc["tags"] = TAGS[::-1]
    (folder / "scan-1.json").write_text(json.dumps(doc), encoding="utf-8")
    clock = TickClock()
    job = _make_job(tmp_path, _correlated_matrix(TICKS), clock)
    assert _run_ticks(job, clock, 3)["scan"]["reason"].startswith("stale_model")


def test_job_with_one_tag_is_rejected(tmp_path: Path) -> None:
    history = HistoryStore(tmp_path / "history.db")
    with pytest.raises(ValueError, match="at least 2 tags"):
        AnomalyScanJob(_job_doc(["FIC101.pv"]), ReplayConnector(_correlated_matrix(1)), history)
