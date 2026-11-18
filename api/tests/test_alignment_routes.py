"""Exercise catalogue timing and the delay scan on synthetic user measurements.

An isolated router makes the expected delay independent of plant simulation models.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from crosscut_api.softsensor_routes import build_softsensor_router
from crosscut_api.target_alignment import aligned_labs, training_target
from crosscut_softsensor.config import load_config
from fastapi import FastAPI
from fastapi.testclient import TestClient

CONFIG = {"schema_version": "1.0.0", "id": "target", "target_tag": "lab",
          "input_tags": ["process"], "mode": "advisory", "lab_delay_s": 0}
SCAN = {"reference_tag": "process", "min_delay_s": -10, "max_delay_s": 10, "step_s": 1}
TRUE_DELAY_S = 4  # Reference recording delay in seconds.
MISSING_CODE = -12345  # User-defined historian sentinel, deliberately not -9999.


def _write_catalogue(root: Path, metadata: dict) -> None:
    """Store a small catalogue with the supplied lab timing rules."""
    folder = root / "_site"
    folder.mkdir(exist_ok=True)
    document = {"tags": [{"id": "lab"}, {"id": "process"}],
                "import": {"missing_codes": [MISSING_CODE]},
                "labs": [{"id": "laboratory", "tag": "lab", **metadata}]}
    (folder / "site.json").write_text(json.dumps(document), encoding="utf-8")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Expose the actual router with a delayed, noisy-free random reference signal."""
    times = np.arange(240, dtype=float)
    signal = np.random.default_rng(38).normal(size=len(times))
    reference = np.interp(times - TRUE_DELAY_S, times, signal)
    app = FastAPI()
    app.include_router(build_softsensor_router(
        tmp_path, lambda _: (times, {"process": reference}),
        lambda _: {"process": np.zeros(len(times), dtype=int)}))
    client = TestClient(app)
    client.put("/softsensor/target", json=CONFIG)
    lab_times = np.arange(20, 220, 4)
    values = signal[lab_times].copy()
    values[3] = MISSING_CODE
    rows = "\n".join(f"{stamp},{value}" for stamp, value in zip(lab_times, values, strict=True))
    client.post("/softsensor/target/lab", json={"csv_text": f"sample_time,value\n{rows}\n"})
    _write_catalogue(tmp_path, {})
    return client


def test_scan_recovers_the_delay_and_honours_the_catalogue_missing_code(client: TestClient) -> None:
    """The API returns the known shift and a finite uncertainty band after removing a sentinel."""
    response = client.post("/datasets/user/softsensor/target/alignment-scan", json=SCAN)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["best_delay_s"] == TRUE_DELAY_S
    assert report["interval_low_s"] <= TRUE_DELAY_S <= report["interval_high_s"]
    assert report["pairs"] == 49


def test_scan_names_an_unknown_reference_tag(client: TestClient) -> None:
    """A mistyped reference tag produces an actionable validation response."""
    response = client.post("/datasets/user/softsensor/target/alignment-scan",
                           json={**SCAN, "reference_tag": "unknown"})
    assert response.status_code == 422
    assert "unknown reference tag" in response.json()["detail"]


def test_scan_rejects_an_invalid_delay_range(client: TestClient) -> None:
    """An inverted range returns a validation response instead of a server error."""
    response = client.post("/datasets/user/softsensor/target/alignment-scan",
                           json={**SCAN, "max_delay_s": -20})
    assert response.status_code == 422


def test_training_separates_physical_time_from_report_availability(tmp_path: Path) -> None:
    """A late report cannot enter training even when its physical timestamp is earlier."""
    _write_catalogue(tmp_path, {"stamp": {"meaning": "end"}, "composite_window_s": 20,
                                "report_delay_s": 30, "analyser_delay_s": 5})
    labs = aligned_labs(tmp_path, [(100.0, 8.0)], load_config(CONFIG))
    bins = np.arange(0, 150, 5, dtype=float)
    assert labs.t_s.tolist() == [85.0]
    assert labs.available_s.tolist() == [130.0]
    assert np.isnan(training_target(bins, labs, 120)).all()
    assert training_target(bins, labs, 140)[17] == 8.0
