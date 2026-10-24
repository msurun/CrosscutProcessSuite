"""Route tests of the step analyzer in driver/output mode: two non-loop tags, no loop name.

The dataset is synthetic and lives only in memory: a speed driver stepping by +-2 units every
40 minutes and a flow output that lags it first order (tau 20 s, gain 3). The route is exercised
end to end through an app carrying only the step analyzer router.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from crosscut_api.step_analyzer_routes import StepRecord, build_step_analyzer_router
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

DT_S = 10.0
SAMPLE_PERIOD_S = DT_S
STEP_INTERVAL_S = 40.0 * 60.0  # a driver step every 40 minutes
SAMPLE_COUNT = int(5.0 * 3600.0 / DT_S)  # five hours of data
DRIVER_STEP_UNIT = 2.0  # the driver alternates by +-2 units
DRIVER_BASELINE = 50.0
FLOW_GAIN = 3.0  # units of drv.flow per unit of drv.speed
FLOW_TAU_S = 20.0
FLOW_BIAS = 10.0
NOISE_STD = 0.05
ORIGIN_UTC_S = 1_790_000_000.0
DRIVER_TAG = "drv.speed"
OUTPUT_TAG = "drv.flow"
DATASET_ID = "demo"
MIN_DRIVER_EVENTS = 3
GAIN_RELATIVE_TOLERANCE = 0.20


def _build_driver_state(t_s: np.ndarray) -> np.ndarray:
    """drv.speed (plant units): baseline 50, alternating +2/-2 steps every 40 minutes."""
    step_index = np.floor(t_s / STEP_INTERVAL_S).astype(int)
    direction = np.where(step_index % 2 == 0, 1.0, -1.0)
    return DRIVER_BASELINE + direction * DRIVER_STEP_UNIT


def _build_driver_flow(t_s: np.ndarray, driver: np.ndarray) -> np.ndarray:
    """drv.flow: first-order lag of (drv.speed - baseline) with gain 3 and tau 20 s, plus noise."""
    rng = np.random.default_rng(seed=7)
    decay = np.exp(-DT_S / FLOW_TAU_S)
    flow = np.empty_like(t_s)
    flow[0] = FLOW_BIAS
    for i in range(1, t_s.size):
        target = FLOW_GAIN * (driver[i] - DRIVER_BASELINE)
        flow[i] = target + (flow[i - 1] - target) * decay
    return flow + rng.normal(scale=NOISE_STD, size=t_s.size)


def _make_driver_record() -> StepRecord:
    """One synthetic driver/output tag pair: drv.speed drives drv.flow, MANUAL mode."""
    t_s = np.arange(SAMPLE_COUNT) * SAMPLE_PERIOD_S
    driver = _build_driver_state(t_s)
    return StepRecord(
        t_s=t_s,
        pv=_build_driver_flow(t_s, driver),
        sp=np.full(SAMPLE_COUNT, DRIVER_BASELINE),
        out=driver,
        mode=np.zeros(SAMPLE_COUNT, dtype=int),
        origin_utc_s=ORIGIN_UTC_S,
        unit="m3/h",
        process_kind="self_regulating",
        test_windows=[],
    )


def _make_loop_loader(_dataset_id: str, _loop: str) -> StepRecord:
    """Any loop name resolves to the driver record; only the driver/output path is under test."""
    return _make_driver_record()


def _make_driver_loader(
    _dataset_id: str, driver: str, output: str
) -> StepRecord:
    """Return the synthetic record when both tags match, else 404 as the real loader would."""
    if driver == DRIVER_TAG and output == OUTPUT_TAG:
        return _make_driver_record()
    raise HTTPException(status_code=404, detail="unknown tag")


@pytest.fixture
def client() -> TestClient:
    """TestClient on an app carrying only the step analyzer route and the synthetic loaders."""
    app = FastAPI()
    app.include_router(build_step_analyzer_router(_make_loop_loader, _make_driver_loader))
    return TestClient(app)


def _post_steps(client: TestClient, body: dict[str, Any]) -> Any:
    """POST the body to the steps route of the demo dataset and return the response."""
    return client.post(f"/datasets/{DATASET_ID}/steps", json=body)


def _ok_fopdt_gains(payload: dict[str, Any]) -> list[float]:
    """Gain of every out_step row that was judged ok and fitted as FOPDT."""
    gains: list[float] = []
    for row in payload["rows"]:
        is_out_step = row["kind"] == "out_step"
        if is_out_step and row.get("model") == "fopdt" and row.get("verdict") == "ok":
            gains.append(row["params"]["gain"]["value"])
    return gains


def test_step_driver_routes_a_driver_output_body_returns_200(client: TestClient) -> None:
    response = _post_steps(client, {"driver": DRIVER_TAG, "output": OUTPUT_TAG})

    assert response.status_code == 200


def test_step_driver_routes_the_payload_has_out_step_rows(client: TestClient) -> None:
    payload = _post_steps(client, {"driver": DRIVER_TAG, "output": OUTPUT_TAG}).json()
    kinds = {row["kind"] for row in payload["rows"]}

    assert "out_step" in kinds


def test_step_driver_routes_at_least_three_driver_events_are_detected(client: TestClient) -> None:
    payload = _post_steps(client, {"driver": DRIVER_TAG, "output": OUTPUT_TAG}).json()

    assert payload["n_events"] >= MIN_DRIVER_EVENTS


def test_step_driver_routes_median_gain_of_ok_fopdt_rows_is_near_the_truth(
    client: TestClient,
) -> None:
    payload = _post_steps(client, {"driver": DRIVER_TAG, "output": OUTPUT_TAG}).json()
    gains = _ok_fopdt_gains(payload)

    assert np.median(gains) == pytest.approx(FLOW_GAIN, rel=GAIN_RELATIVE_TOLERANCE)


def test_step_driver_routes_giving_both_loop_and_driver_is_rejected_with_steps_target(
    client: TestClient,
) -> None:
    body = {"loop": "LIC-101", "driver": DRIVER_TAG, "output": OUTPUT_TAG}
    response = _post_steps(client, body)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "steps_target"


def test_step_driver_routes_driver_without_output_is_rejected_with_422(client: TestClient) -> None:
    response = _post_steps(client, {"driver": DRIVER_TAG})

    assert response.status_code == 422


def test_step_driver_routes_neither_loop_nor_pair_is_rejected_with_422(client: TestClient) -> None:
    response = _post_steps(client, {})

    assert response.status_code == 422


def test_step_driver_routes_an_unknown_driver_tag_passes_the_404_through(
    client: TestClient,
) -> None:
    response = _post_steps(client, {"driver": "drv.unknown", "output": OUTPUT_TAG})

    assert response.status_code == 404


def test_step_driver_routes_real_loader_reads_two_tags_of_a_dataset(tmp_path: Path) -> None:
    """The app's own loader: a simulated dataset, one tag as driver and another as output."""
    from crosscut_api.app import create_app  # noqa: PLC0415
    from crosscut_sim.run import main as run_simulation  # noqa: PLC0415

    argv = ["--plant", "mill_circuit", "--duration", "2h", "--sample-period", "10"]
    assert run_simulation([*argv, "--out", str(tmp_path)]) == 0
    real = TestClient(create_app(tmp_path))
    dataset = real.get("/datasets").json()[0]["id"]
    body = {"driver": "sim.mc.mill_feed", "output": "sim.mc.mill_power"}
    assert real.post(f"/datasets/{dataset}/steps", json=body).status_code == 200
    body["output"] = "sim.mc.no_such_tag"
    assert real.post(f"/datasets/{dataset}/steps", json=body).status_code == 404
