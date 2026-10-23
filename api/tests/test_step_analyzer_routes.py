"""Route tests of the step analyzer: HTTP status, payload keys and the analyzer wiring.

The loader is a test function returning a synthetic self-regulating loop so the route is
exercised end to end without touching a dataset on disk.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import numpy as np
import pytest
from crosscut_api import step_analyzer_routes
from crosscut_api.step_analyzer_routes import StepRecord, build_step_analyzer_router
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

DT_S = 10.0
N_SAMPLES = 900
STEP_INDEX = 200
STEP_TIME_S = STEP_INDEX * DT_S
GAIN = 0.8
TAU_S = 120.0
THETA_S = 40.0
OUT_BEFORE = 40.0
OUT_AFTER = 47.0
NOISE_STD = 0.15
ORIGIN_UTC_S = 1_790_000_000.0
LOOP_NAME = "LIC-101"
MAX_LOGBOOK_ENTRIES = 500


def _build_record_pv(t_s: np.ndarray, out: np.ndarray) -> np.ndarray:
    """First-order response K=0.8, tau=120 s, theta=40 s to the OUT step, plus noise 0.15."""
    rng = np.random.default_rng(seed=42)
    delay_s = np.clip(t_s - STEP_TIME_S - THETA_S, a_min=0.0, a_max=None)
    response = GAIN * (OUT_AFTER - OUT_BEFORE) * (1.0 - np.exp(-delay_s / TAU_S))
    return OUT_BEFORE + response + rng.normal(scale=NOISE_STD, size=t_s.size)


def _build_out(t_s: np.ndarray) -> np.ndarray:
    """OUT (plant units) steps from 40 to 47 at sample 200 and stays there."""
    out = np.full(t_s.size, OUT_BEFORE)
    out[STEP_INDEX:] = OUT_AFTER
    return out


def _make_record() -> StepRecord:
    """One synthetic self-regulating loop: dt 10 s, 900 samples, MANUAL mode, PV to an OUT step."""
    t_s = np.arange(N_SAMPLES) * DT_S
    out = _build_out(t_s)
    start_utc = ORIGIN_UTC_S + STEP_TIME_S
    test_windows = [
        {
            "label": "T1",
            "start_utc": _iso_utc(start_utc - 60.0),
            "end_utc": _iso_utc(start_utc + 600.0),
        }
    ]
    return StepRecord(
        t_s=t_s,
        pv=_build_record_pv(t_s, out),
        sp=np.full(N_SAMPLES, 40.0),
        out=out,
        mode=np.zeros(N_SAMPLES, dtype=int),
        origin_utc_s=ORIGIN_UTC_S,
        unit="cm",
        process_kind="self_regulating",
        test_windows=test_windows,
    )


@pytest.fixture
def client() -> TestClient:
    """TestClient on an app carrying only the step analyzer route and the synthetic loader."""
    app = FastAPI()
    app.include_router(build_step_analyzer_router(lambda _dataset_id, _loop: _make_record()))
    return TestClient(app)


def _post_steps(client: TestClient, body: dict[str, Any]) -> Any:
    """POST the body to the steps route of dataset 'demo' and return the response."""
    return client.post("/datasets/demo/steps", json=body)


def _find_row(payload: dict[str, Any], kind: str) -> dict[str, Any]:
    """The first row of the payload whose 'kind' equals ``kind``."""
    return next(row for row in payload["rows"] if row["kind"] == kind)


def test_a_valid_request_returns_the_payload_keys(client: TestClient) -> None:
    response = _post_steps(client, {"loop": LOOP_NAME})

    assert response.status_code == 200
    assert {"loop", "rows", "summary", "skipped", "n_events"} <= set(response.json())


def test_the_step_row_is_fitted_as_a_first_order_model_with_gain_near_the_truth(
    client: TestClient,
) -> None:
    response = _post_steps(client, {"loop": LOOP_NAME})
    row = _find_row(response.json(), "out_step")

    assert row["model"] == "fopdt"
    assert row["params"]["gain"]["value"] == pytest.approx(GAIN, rel=0.10)


def test_the_step_row_is_labelled_with_the_covering_test_window(client: TestClient) -> None:
    response = _post_steps(client, {"loop": LOOP_NAME})
    row = _find_row(response.json(), "out_step")

    assert row["test_label"] == "T1"


def test_a_logbook_entry_within_two_minutes_is_attached(client: TestClient) -> None:
    event_s = ORIGIN_UTC_S + STEP_TIME_S
    body = {
        "loop": LOOP_NAME,
        "logbook": [{"time_utc": _iso_utc(event_s + 120.0), "text": "valve stroked"}],
    }
    response = _post_steps(client, body)

    assert "valve stroked" in _row_texts(response.json())


def test_a_logbook_entry_twenty_minutes_away_is_not_attached(client: TestClient) -> None:
    event_s = ORIGIN_UTC_S + STEP_TIME_S
    body = {
        "loop": LOOP_NAME,
        "logbook": [{"time_utc": _iso_utc(event_s + 1200.0), "text": "unrelated note"}],
    }
    response = _post_steps(client, body)

    assert "unrelated note" not in _row_texts(response.json())


def test_forcing_ipdt_returns_an_ipdt_model(client: TestClient) -> None:
    response = _post_steps(client, {"loop": LOOP_NAME, "model": "ipdt"})
    row = _find_row(response.json(), "out_step")

    assert row["model"] == "ipdt"


def test_an_empty_loop_name_is_rejected_with_422(client: TestClient) -> None:
    response = _post_steps(client, {"loop": ""})

    assert response.status_code == 422


def test_an_unknown_model_is_rejected_with_422(client: TestClient) -> None:
    response = _post_steps(client, {"loop": LOOP_NAME, "model": "abc"})

    assert response.status_code == 422


def test_more_logbook_entries_than_the_limit_is_rejected_with_422(client: TestClient) -> None:
    entries = [{"time_utc": _iso_utc(ORIGIN_UTC_S), "text": ""}] * (MAX_LOGBOOK_ENTRIES + 1)
    response = _post_steps(client, {"loop": LOOP_NAME, "logbook": entries})

    assert response.status_code == 422


def test_an_unknown_dataset_passes_the_404_through() -> None:
    def rejecting_loader(_dataset_id: str, _loop: str) -> StepRecord:
        raise HTTPException(status_code=404, detail="unknown dataset")

    app = FastAPI()
    app.include_router(build_step_analyzer_router(rejecting_loader))
    response = TestClient(app).post("/datasets/missing/steps", json={"loop": LOOP_NAME})

    assert response.status_code == 404


def test_a_value_error_from_the_analyzer_becomes_a_422_with_the_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raising_analyze(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise ValueError("bad")

    monkeypatch.setattr(step_analyzer_routes, "analyze_steps", raising_analyze)
    response = _post_steps(client, {"loop": LOOP_NAME})
    detail = response.json()["detail"]

    assert response.status_code == 422
    assert detail["message"] == "bad"


def _iso_utc(epoch_s: float) -> str:
    """ISO 8601 UTC timestamp of an epoch second, as the logbook body expects."""
    from datetime import datetime

    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


def _row_texts(payload: dict[str, Any]) -> list[str]:
    """Every free-text string found in the event-bearing rows of the payload."""
    texts: list[str] = []
    for row in payload["rows"]:
        for value in row.get("logbook", []):
            texts.append(str(value.get("text", "")))
    return texts
