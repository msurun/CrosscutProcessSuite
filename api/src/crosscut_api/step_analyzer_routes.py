"""HTTP route of the step analyzer: detect, fit and judge the step tests of a loop or a driver tag.

The route only reads a recorded dataset and returns the analysis payload of the design
``docs/design/step-analyzer.md``; nothing here writes to a plant. Input mistakes come back as 422.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import numpy as np
from crosscut_loops.step_analyzer import analyze_steps
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

#: (dataset id, loop name) -> StepRecord; raises HTTPException(404) for an unknown dataset/loop.
RecordLoader = Callable[[str, str], "StepRecord"]
#: (dataset id, driver tag, output tag) -> StepRecord with the driver as OUT and the output as PV.
DriverLoader = Callable[[str, str, str], "StepRecord"]

#: A step test analysis needs at most a few dozen logbook lines; more is a client mistake.
MAX_LOGBOOK_ENTRIES = 500
MAX_LOG_ENTRY_LEN = 200
MODEL_KINDS = ("auto", "fopdt", "ipdt")


@dataclass(frozen=True)
class StepRecord:
    """One loop of a dataset, ready for the analyzer.

    Arrays are sample-aligned: ``t_s`` (s, monotonic), ``pv``, ``sp``, ``out`` (plant units)
    and ``mode`` (0 = manual, 1 = auto). ``origin_utc_s`` is the UTC epoch second of ``t_s[0]``, so
    event timestamps can be reported; ``test_windows`` are the sidecar ``test_windows.json`` rows.
    """

    t_s: np.ndarray
    pv: np.ndarray
    sp: np.ndarray
    out: np.ndarray
    mode: np.ndarray
    origin_utc_s: float
    unit: str
    process_kind: str
    test_windows: list[dict]


class LogbookEntry(BaseModel):
    """One logbook line sent by the operator: an ISO UTC time and a free-text description."""

    time_utc: str
    text: str = ""  # description of what happened; may be empty


class StepsBody(BaseModel):
    """Request body of ``POST /datasets/{dataset_id}/steps``."""

    loop: str | None = Field(default=None, min_length=1)  # loop name as the dataset knows it
    driver: str | None = Field(default=None, min_length=1)  # a stepped non-loop tag (pump speed)
    output: str | None = Field(default=None, min_length=1)  # the tag that responds to the driver
    model: Literal["auto", "fopdt", "ipdt"] = "auto"  # "auto" picks the better of FOPDT/IPDT by BIC
    logbook: list[LogbookEntry] = Field(default_factory=list, max_length=MAX_LOGBOOK_ENTRIES)


def _bad_value(error: ValueError) -> HTTPException:
    """The 422 response for a ValueError raised by the analyzer: a stable code and the message."""
    detail = {"code": "steps_analysis_failed", "message": str(error)}
    return HTTPException(status_code=422, detail=detail)


def _record_for(
    body: StepsBody, dataset_id: str, load: RecordLoader, load_driver: DriverLoader | None
):
    """The record of a loop, or of a driver/output tag pair; 422 unless exactly one is given."""
    has_pair = body.driver is not None and body.output is not None
    if (body.loop is None) == (not has_pair) or (body.driver is None) != (body.output is None):
        detail = {"code": "steps_target", "message": "give either loop, or driver and output"}
        raise HTTPException(status_code=422, detail=detail)
    if body.loop is not None:
        return body.loop, load(dataset_id, body.loop)
    if load_driver is None or body.driver is None or body.output is None:
        detail = {"code": "steps_target", "message": "driver mode is not available"}
        raise HTTPException(status_code=422, detail=detail)
    return f"{body.driver} -> {body.output}", load_driver(dataset_id, body.driver, body.output)


def build_step_analyzer_router(
    load: RecordLoader, load_driver: DriverLoader | None = None
) -> APIRouter:
    """Route of the step analyzer; the loaders read the sample arrays of a loop or a tag pair."""
    router = APIRouter()

    @router.post("/datasets/{dataset_id}/steps")
    def analyze_dataset_steps(
        dataset_id: str, body: Annotated[StepsBody, Body()]
    ) -> dict[str, Any]:
        """Detect, fit and judge the step tests of one loop; returns the JSON-safe payload."""
        name, record = _record_for(body, dataset_id, load, load_driver)
        try:
            return analyze_steps(
                record.t_s,
                record.pv,
                record.sp,
                record.out,
                record.mode,
                loop_id=name,
                process_kind=record.process_kind,
                unit=record.unit,
                origin_utc_s=record.origin_utc_s,
                test_windows=record.test_windows,
                logbook=[entry.model_dump() for entry in body.logbook],
                model=body.model,
            )
        except ValueError as error:
            raise _bad_value(error) from error

    return router
