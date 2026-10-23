"""HTTP route of the step analyzer: detect, fit and judge the step tests of one loop of a dataset.

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

    loop: str = Field(min_length=1)  # loop name as the dataset knows it
    model: Literal["auto", "fopdt", "ipdt"] = "auto"  # "auto" picks the better of FOPDT/IPDT by BIC
    logbook: list[LogbookEntry] = Field(default_factory=list, max_length=MAX_LOGBOOK_ENTRIES)


def _bad_value(error: ValueError) -> HTTPException:
    """The 422 response for a ValueError raised by the analyzer: a stable code and the message."""
    detail = {"code": "steps_analysis_failed", "message": str(error)}
    return HTTPException(status_code=422, detail=detail)


def build_step_analyzer_router(load: RecordLoader) -> APIRouter:
    """Route of the step analyzer; ``load`` reads the sample arrays of one loop of a dataset."""
    router = APIRouter()

    @router.post("/datasets/{dataset_id}/steps")
    def analyze_dataset_steps(
        dataset_id: str, body: Annotated[StepsBody, Body()]
    ) -> dict[str, Any]:
        """Detect, fit and judge the step tests of one loop; returns the JSON-safe payload."""
        record = load(dataset_id, body.loop)
        try:
            return analyze_steps(
                record.t_s,
                record.pv,
                record.sp,
                record.out,
                record.mode,
                loop_id=body.loop,
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
