"""HTTP routes of the guided valve stroke test: plan, analyse a dataset window, analyse a CSV.

The test is a procedure the operator carries out by hand; nothing here writes to a plant. The
analysis only reads a recorded record (a window of a dataset, or a CSV sent in the request body
and kept in memory). Input mistakes come back as 422 with a stable ``code`` the UI translates.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

import numpy as np
from crosscut_loops.valve_payload import (
    ValveInputError,
    analyse_window,
    parse_csv_record,
    plan_from_request,
    plan_payload,
)
from fastapi import APIRouter, Body, HTTPException

#: (dataset id, loop name) -> (t_s, op, pv); raises HTTPException(404) for an unknown dataset/loop.
LoopRecordLoader = Callable[[str, str], tuple[np.ndarray, np.ndarray, np.ndarray]]

PLAN_KEY = "plan"
WINDOW_KEYS = ("start_s", "end_s")


def _unprocessable(error: ValveInputError) -> HTTPException:
    """The 422 response for an input mistake: a stable code, the English message and the field."""
    detail = {"code": error.code, "message": str(error), "field": error.field}
    return HTTPException(status_code=422, detail=detail)


def _plan_of(body: dict[str, Any]) -> Any:
    """The StrokePlan named by the request's ``plan`` object; ValveInputError when it is wrong."""
    plan = body.get(PLAN_KEY)
    if not isinstance(plan, dict):
        raise ValveInputError("plan_invalid", "the request needs a 'plan' object", PLAN_KEY)
    return plan_from_request(plan)


def _window_of(body: dict[str, Any]) -> tuple[float | None, float | None]:
    """The optional (start_s, end_s) window of the request; numbers only."""
    values: list[float | None] = []
    for key in WINDOW_KEYS:
        value = body.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int | float)):
            raise ValveInputError("window_invalid", f"{key} must be a number", "window")
        values.append(None if value is None else float(value))
    return values[0], values[1]


def build_valve_router(load_record: LoopRecordLoader) -> APIRouter:
    """Routes of the valve stroke test; ``load_record`` reads a loop's OUT and PV from a dataset."""
    router = APIRouter()

    @router.post("/valve-test/plan")
    def make_plan(body: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        """Build a stroke test plan and the operator procedure from the test settings."""
        try:
            return plan_payload(plan_from_request(body))
        except ValveInputError as error:
            raise _unprocessable(error) from error

    @router.post("/datasets/{dataset_id}/loops/{loop_name}/valve-test/analyse")
    def analyse_dataset(
        dataset_id: str, loop_name: str, body: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """Analyse a stroke test recorded in a window of the dataset (default: the whole record)."""
        try:
            plan, window = _plan_of(body), _window_of(body)
            t_s, op, pv = load_record(dataset_id, loop_name)
            return analyse_window(t_s, op, pv, plan, window)
        except ValveInputError as error:
            raise _unprocessable(error) from error

    @router.post("/valve-test/analyse-csv")
    def analyse_csv(body: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        """Analyse a stroke test from CSV text (t, OP, PV); parsed in memory, nothing is stored."""
        try:
            plan = _plan_of(body)
            columns = body.get("columns")
            if columns is not None and not isinstance(columns, dict):
                raise ValveInputError(
                    "csv_columns_missing", "'columns' must be an object", "columns"
                )
            text = body.get("csv_text")
            if not isinstance(text, str):
                raise ValveInputError(
                    "csv_no_numeric_rows", "the request needs 'csv_text'", "csv_text"
                )
            t_s, op, pv = parse_csv_record(text, columns)
            return analyse_window(t_s, op, pv, plan)
        except ValveInputError as error:
            raise _unprocessable(error) from error

    return router
