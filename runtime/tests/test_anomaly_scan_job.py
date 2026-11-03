"""Tests of AnomalyScanJob: learning gate, live scan with events, and tag-count validation.

A replay connector returns one row of a fixed correlated matrix per read, and a fake clock
advances 60 s per run, so the job runs its real sampling, history and PCA code deterministically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from crosscut_connectors.base import LiveValue
from crosscut_runtime.history import HistoryStore
from crosscut_runtime.jobs.anomaly_scan import MIN_TRAIN_ROWS_BASE, AnomalyScanJob

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

    def __init__(self, matrix: np.ndarray) -> None:
        """Hold the matrix (rows = ticks, columns = TAGS) and the read position."""
        self._matrix = matrix
        self._row = 0

    def read_live(self, tag_ids: list[str]) -> dict[str, LiveValue]:
        """Return the current row for every requested tag and advance to the next row."""
        values = self._matrix[self._row]
        self._row += 1
        stamp = "2024-01-01T00:00:00+00:00"
        return {
            tag: LiveValue(value=float(values[TAGS.index(tag)]), quality=0, timestamp_utc=stamp)
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


def _make_job(tmp_path: Path, matrix: np.ndarray, clock: TickClock) -> AnomalyScanJob:
    """An AnomalyScanJob reading the matrix and storing history under tmp_path."""
    history = HistoryStore(tmp_path / "history.db")
    return AnomalyScanJob(_job_doc(TAGS), ReplayConnector(matrix), history, clock)


def _run_ticks(job: AnomalyScanJob, clock: TickClock, ticks: int) -> dict[str, Any]:
    """Run the job for some ticks, advancing the clock one period each; return the last result."""
    result: dict[str, Any] = {}
    for _ in range(ticks):
        result = job.run()
        clock.now += PERIOD_S
    return result


def test_scan_is_learning_before_enough_training_rows(tmp_path: Path) -> None:
    clock = TickClock()
    job = _make_job(tmp_path, _correlated_matrix(TICKS), clock)
    scan = _run_ticks(job, clock, 5)["scan"]
    assert scan["status"] == "learning"
    assert scan["needed"] == MIN_TRAIN_ROWS_BASE
    assert scan["events"] == []


def test_scan_is_ok_once_enough_history_is_trained(tmp_path: Path) -> None:
    clock = TickClock()
    job = _make_job(tmp_path, _correlated_matrix(TICKS), clock)
    scan = _run_ticks(job, clock, TICKS)["scan"]
    assert scan["status"] == "ok"
    assert scan["train_rows"] >= MIN_TRAIN_ROWS_BASE
    assert isinstance(scan["events"], list)


def test_sudden_shift_in_recent_ticks_produces_an_event(tmp_path: Path) -> None:
    clock = TickClock()
    job = _make_job(tmp_path, _correlated_matrix(TICKS, shift_last=SHIFT_SIZE), clock)
    scan = _run_ticks(job, clock, TICKS)["scan"]
    assert scan["status"] == "ok"
    assert len(scan["events"]) >= 1


def test_job_with_one_tag_is_rejected(tmp_path: Path) -> None:
    history = HistoryStore(tmp_path / "history.db")
    with pytest.raises(ValueError, match="at least 2 tags"):
        AnomalyScanJob(_job_doc(["FIC101.pv"]), ReplayConnector(_correlated_matrix(1)), history)
