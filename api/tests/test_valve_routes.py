"""HTTP-level tests of the valve stroke test routes (plan, dataset window, CSV upload)."""
# The routes are mounted on a bare FastAPI app with a fake record loader, so the tests exercise
# the request parsing, the 422/404 mapping and the JSON shape a UI depends on.

from __future__ import annotations

import numpy as np
import pytest
from crosscut_api.valve_routes import build_valve_router
from crosscut_loops.valve_test import plan_stroke_test
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# Simulation constants (units: % of span for OP, PV units for process, seconds for time)
PROCESS_GAIN_PV_PER_PERCENT = 0.5  # dPV / dOP (PV units per % of span)
PROCESS_TAU_S = 5.0  # process time constant, seconds
VALVE_DEADBAND_PERCENT = 0.5  # valve stick width, % of span
PV_NOISE_SIGMA = 0.01  # PV noise standard deviation, PV units
SAMPLE_TIME_S = 1.0  # record sample interval, seconds
DWELL_S = 120  # dwell per step, seconds
RANDOM_SEED = 1234  # fixed so the synthetic record is reproducible
MAX_SERIES_POINTS = 600  # the route's decimated series cap

VALID_PLAN_BODY = {"op_start": 50.0, "dwell_s": 120}
CSV_TOO_LARGE_BYTES = 5_000_001
CSV_MIN_ROWS = 20


def _simulate_stroke_record() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Simulate (t_s, op, pv) of a stick-slip valve followed by a first-order process.

    The OP is piecewise constant (op_start, then each step target, held dwell_s samples).
    The valve position stays put until |OP - position| exceeds ``VALVE_DEADBAND_PERCENT``, then
    snaps to OP. The PV is a first-order lag of the valve position plus Gaussian noise.
    """
    plan = plan_stroke_test(op_start=50.0, dwell_s=DWELL_S)
    op_profile_percent = [plan.op_start, *(step.op_target for step in plan.steps)]
    samples_per_level = int(DWELL_S / SAMPLE_TIME_S)
    op = np.repeat(op_profile_percent, samples_per_level).astype(float)
    n = len(op)

    valve_position = op[0]
    pv = np.empty(n)
    pv[0] = PROCESS_GAIN_PV_PER_PERCENT * valve_position
    alpha = SAMPLE_TIME_S / (PROCESS_TAU_S + SAMPLE_TIME_S)
    rng = np.random.default_rng(RANDOM_SEED)
    for k in range(1, n):
        if abs(op[k] - valve_position) > VALVE_DEADBAND_PERCENT:
            valve_position = op[k]
        target = PROCESS_GAIN_PV_PER_PERCENT * valve_position
        pv[k] = pv[k - 1] + alpha * (target - pv[k - 1]) + rng.normal(0.0, PV_NOISE_SIGMA)

    t_s = np.arange(n) * SAMPLE_TIME_S
    return t_s, op, pv


def _fake_loader(dataset_id: str, loop_name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A record loader that answers for any known dataset/loop and 404s for "nope"."""
    if dataset_id == "nope" or loop_name == "nope":
        raise HTTPException(status_code=404, detail="unknown dataset or loop")
    return _simulate_stroke_record()


@pytest.fixture
def client() -> TestClient:
    """A TestClient with the valve router mounted on a bare FastAPI app."""
    app = FastAPI()
    app.include_router(build_valve_router(_fake_loader))
    return TestClient(app)


def _record_csv_text() -> str:
    """The synthetic record as a 't_s,op,pv' CSV text with a header row."""
    t_s, op, pv = _simulate_stroke_record()
    rows = ["t_s,op,pv"]
    rows += [f"{t:.3f},{o:.3f},{p:.3f}" for t, o, p in zip(t_s, op, pv, strict=True)]
    return "\n".join(rows) + "\n"


# --- POST /valve-test/plan --------------------------------------------------------------


def test_plan_returns_the_step_count_and_total_time(client: TestClient) -> None:
    response = client.post("/valve-test/plan", json=VALID_PLAN_BODY)

    assert response.status_code == 200
    assert response.json()["n_steps"] == len(response.json()["steps"])
    assert response.json()["total_s"] > 0


def test_plan_procedure_starts_manual_and_ends_return_auto(client: TestClient) -> None:
    codes = [
        step["code"]
        for step in client.post("/valve-test/plan", json=VALID_PLAN_BODY).json()["procedure"]
    ]

    assert codes[0] == "manual"
    assert codes[-1] == "return_auto"


def test_plan_with_string_op_start_is_422_plan_invalid_on_op_start(client: TestClient) -> None:
    response = client.post("/valve-test/plan", json={"op_start": "50", "dwell_s": 120})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "plan_invalid"
    assert response.json()["detail"]["field"] == "op_start"
    assert isinstance(response.json()["detail"]["message"], str)


def test_plan_with_zero_dwell_is_422_on_dwell_s(client: TestClient) -> None:
    response = client.post("/valve-test/plan", json={"op_start": 50.0, "dwell_s": 0})

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "dwell_s"


# --- POST /datasets/{id}/loops/{loop}/valve-test/analyse --------------------------------


def test_analyse_identifies_a_gain_close_to_the_process_gain(client: TestClient) -> None:
    response = client.post(
        "/datasets/ds/loops/L/valve-test/analyse", json={"plan": VALID_PLAN_BODY}
    )

    assert response.status_code == 200
    assert response.json()["result"]["gain"] == pytest.approx(PROCESS_GAIN_PV_PER_PERCENT, abs=0.1)


def test_analyse_reports_a_deadband_bracket(client: TestClient) -> None:
    response = client.post(
        "/datasets/ds/loops/L/valve-test/analyse", json={"plan": VALID_PLAN_BODY}
    )

    assert response.json()["result"]["deadband_bracket"] is not None


def test_analyse_series_lists_have_equal_length_at_most_600(client: TestClient) -> None:
    series = client.post(
        "/datasets/ds/loops/L/valve-test/analyse", json={"plan": VALID_PLAN_BODY}
    ).json()["record"]["series"]
    lengths = {len(series[key]) for key in ("t_s", "op", "pv")}

    assert lengths == {min(lengths)} or True  # structure check below
    assert all(len(series[key]) <= MAX_SERIES_POINTS for key in ("t_s", "op", "pv"))
    assert len({len(series[key]) for key in ("t_s", "op", "pv")}) == 1


def test_analyse_with_window_narrows_the_record(client: TestClient) -> None:
    response = client.post(
        "/datasets/ds/loops/L/valve-test/analyse",
        json={"plan": VALID_PLAN_BODY, "start_s": 0.0, "end_s": 600.0},
    )

    assert response.status_code == 200
    assert response.json()["record"]["n_samples"] <= 601
    assert response.json()["record"]["end_s"] <= 600.0


def test_analyse_with_non_numeric_start_is_422_window_invalid(client: TestClient) -> None:
    response = client.post(
        "/datasets/ds/loops/L/valve-test/analyse",
        json={"plan": VALID_PLAN_BODY, "start_s": "early"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "window_invalid"
    assert response.json()["detail"]["field"] == "window"


def test_analyse_without_plan_is_422_plan_invalid(client: TestClient) -> None:
    response = client.post("/datasets/ds/loops/L/valve-test/analyse", json={})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "plan_invalid"
    assert response.json()["detail"]["field"] == "plan"


def test_analyse_of_unknown_dataset_is_404(client: TestClient) -> None:
    response = client.post(
        "/datasets/nope/loops/L/valve-test/analyse", json={"plan": VALID_PLAN_BODY}
    )

    assert response.status_code == 404


def test_analyse_of_unknown_loop_is_404(client: TestClient) -> None:
    response = client.post(
        "/datasets/ds/loops/nope/valve-test/analyse", json={"plan": VALID_PLAN_BODY}
    )

    assert response.status_code == 404


# --- POST /valve-test/analyse-csv -------------------------------------------------------


def test_analyse_csv_of_the_record_identifies_the_same_gain(client: TestClient) -> None:
    response = client.post(
        "/valve-test/analyse-csv", json={"plan": VALID_PLAN_BODY, "csv_text": _record_csv_text()}
    )

    assert response.status_code == 200
    assert response.json()["result"]["gain"] == pytest.approx(PROCESS_GAIN_PV_PER_PERCENT, abs=0.1)


def test_analyse_csv_with_semicolon_and_decimal_comma_parses(client: TestClient) -> None:
    t_s, op, pv = _simulate_stroke_record()
    rows = ["t;op;pv"]
    rows += [
        f"{t:.3f};{o:.3f};{p:.3f}".replace(".", ",") for t, o, p in zip(t_s, op, pv, strict=True)
    ]
    text = "\n".join(rows) + "\n"

    response = client.post(
        "/valve-test/analyse-csv", json={"plan": VALID_PLAN_BODY, "csv_text": text}
    )

    assert response.status_code == 200
    assert response.json()["result"]["gain"] is not None


def test_analyse_csv_without_text_is_422(client: TestClient) -> None:
    response = client.post("/valve-test/analyse-csv", json={"plan": VALID_PLAN_BODY})

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "csv_text"


def test_analyse_csv_with_columns_not_an_object_is_422_csv_columns_missing(
    client: TestClient,
) -> None:
    response = client.post(
        "/valve-test/analyse-csv",
        json={"plan": VALID_PLAN_BODY, "csv_text": _record_csv_text(), "columns": [1, 2]},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "csv_columns_missing"


def test_analyse_csv_with_too_few_rows_is_422_csv_no_numeric_rows(client: TestClient) -> None:
    rows = ["t_s,op,pv"]
    rows += [f"{i}.0,10.0,1.0" for i in range(CSV_MIN_ROWS - 5)]

    response = client.post(
        "/valve-test/analyse-csv",
        json={"plan": VALID_PLAN_BODY, "csv_text": "\n".join(rows) + "\n"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "csv_no_numeric_rows"


def test_analyse_csv_over_the_size_limit_is_422_csv_too_large(client: TestClient) -> None:
    response = client.post(
        "/valve-test/analyse-csv",
        json={"plan": VALID_PLAN_BODY, "csv_text": "a" * CSV_TOO_LARGE_BYTES},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "csv_too_large"
