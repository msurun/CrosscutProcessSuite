"""HTTP routes of the advisory supervisor (ADR 010): configs, one-off advice, replay, audit log.

Configs are kept in ``<data root>/_supervisor``, advisory logs in ``<data root>/_advisory/<id>``.
The only writes are a config (PUT) and log appends (replay with ``record`` and ack). Nothing
here reaches a plant: the supervisor advises, a human decides.
"""

from __future__ import annotations

import dataclasses
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, TypeVar

import numpy as np
from crosscut_fuzzy.library import load_document
from crosscut_fuzzy.model import FuzzyModelError, FuzzySystem, system_from_dict
from crosscut_fuzzy.versions import load_version
from crosscut_loops.overview import LoopTags
from crosscut_supervisor.audit import AckRequest, AuditError, AuditLog, ack
from crosscut_supervisor.config import (
    SupervisorConfig,
    SupervisorConfigError,
    check_against_system,
    load_config,
)
from crosscut_supervisor.replay import (
    ReplayData,
    ReplayError,
    ReplaySettings,
    advise_at,
    advise_series,
    replay_to_log,
)
from fastapi import APIRouter, HTTPException, Query
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

CONFIG_DIR_NAME = "_supervisor"
LOG_DIR_NAME = "_advisory"
FUZZY_DIR_NAME = "_fuzzy"
SID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
DEFAULT_WINDOW_S = 1800.0
DEFAULT_STEP_S = 300.0
Sid = Annotated[str, PathParam(pattern=SID_PATTERN)]
SecondsLoader = Callable[[str], tuple[np.ndarray, dict[str, Any]]]
LoopsLoader = Callable[[str], list[LoopTags]]
T = TypeVar("T")


class AdviseRequest(BaseModel):
    """The moment to advise at, in seconds from the first sample (None = end of the record)."""

    t_s: float | None = None


class SupervisorReplayRequest(BaseModel):
    """Part of a record to replay (seconds from the first sample), window and step in seconds."""

    start_s: float | None = None
    end_s: float | None = None
    window_s: Annotated[float, Field(gt=0)] = DEFAULT_WINDOW_S
    step_s: Annotated[float, Field(gt=0)] = DEFAULT_STEP_S
    record: bool = False


class AckBody(BaseModel):
    """An operator's decision about one logged advice."""

    decision: str
    reason_code: str
    who: str
    note: str = ""


class _SupervisorEndpoints:
    """The supervisor route handlers, bound to the data root and the dataset loaders."""

    def __init__(self, root: Path, load_seconds: SecondsLoader, load_loops: LoopsLoader) -> None:
        self.root = root
        self.load_seconds = load_seconds
        self.load_loops = load_loops

    def list_supervisors(self) -> list[str]:
        """Ids of the saved supervisor configurations, sorted."""
        folder = self.root / CONFIG_DIR_NAME
        return sorted(path.stem for path in folder.glob("*.json")) if folder.is_dir() else []

    def get_supervisor(self, sid: Sid) -> dict[str, Any]:
        """One saved configuration as stored (404 when unknown)."""
        path = self._config_path(sid)
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"unknown supervisor: {sid}")
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return document

    def put_supervisor(self, sid: Sid, document: dict[str, Any]) -> dict[str, Any]:
        """Validate and save a configuration (422 with the reason when it is not acceptable)."""
        config = _config_or_422(document)
        if config.id != sid:
            raise HTTPException(status_code=422, detail=f"id: {config.id!r} does not match {sid!r}")
        system = self._system_or_none(config)
        if system is not None:
            _check_or_422(config, system)
        _write_json_atomic(self._config_path(sid), document)
        return document

    def post_advise(self, dataset_id: str, sid: Sid, request: AdviseRequest) -> dict[str, Any]:
        """Advise once on the window ending at ``t_s``; the log is not written."""
        config, system = self._config_and_system(sid)
        data = self._data(dataset_id, request.t_s)
        t_end = float(data.t_s[-1])
        window = (t_end, DEFAULT_WINDOW_S)
        advice, gate = _guarded(
            lambda: advise_at(system, config, (data, self._loops(dataset_id, config)), window)
        )
        return {
            "advice": None if advice is None else advice.to_record(),
            "gate": {"state": gate.state, "reasons": list(gate.reasons)},
        }

    def post_replay(
        self, dataset_id: str, sid: Sid, request: SupervisorReplayRequest
    ) -> dict[str, Any]:
        """Replay the supervisor over the record; with ``record`` the advices go to the log."""
        config, system = self._config_and_system(sid)
        data = self._data(dataset_id, request.end_s)
        settings = ReplaySettings(request.window_s, request.step_s, request.start_s)
        advices = _guarded(
            lambda: advise_series(
                system, config, data, self._loops(dataset_id, config), settings
            )
        )
        written = replay_to_log(advices, self._log(sid)) if request.record else 0
        return {"advices": [advice.to_record() for advice in advices], "recorded": written}

    def get_log(self, sid: Sid, since_index: Annotated[int, Query(ge=0)] = 0) -> dict[str, Any]:
        """Log records from ``since_index`` on, plus the verification of the whole chain."""
        self.get_supervisor(sid)
        log = self._log(sid)
        records = log.records()
        return {
            "records": records[since_index:],
            "total": len(records),
            "chain": dataclasses.asdict(log.verify()),
        }

    def post_ack(self, sid: Sid, advice_id: str, body: AckBody) -> dict[str, Any]:
        """Append the operator's decision about a logged advice; return the stored record."""
        self.get_supervisor(sid)
        log = self._log(sid)
        if log.find_advice(advice_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown advice: {advice_id}")
        request = AckRequest(
            advice_id, body.decision, body.reason_code, body.who, time.time_ns(), body.note
        )
        try:
            ack(log, request)
        except AuditError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return log.records()[-1]

    def _config_path(self, sid: str) -> Path:
        """File of one configuration (``sid`` was checked against SID_PATTERN by the route)."""
        return self.root / CONFIG_DIR_NAME / f"{sid}.json"

    def _log(self, sid: str) -> AuditLog:
        """The advisory log of one supervisor."""
        return AuditLog(self.root / LOG_DIR_NAME / sid / "log.jsonl")

    def _system_or_none(self, config: SupervisorConfig) -> FuzzySystem | None:
        """The fuzzy system a config points to (its pinned version when set), None if unknown."""
        user_dir = self.root / FUZZY_DIR_NAME
        try:
            if config.fuzzy_version_id is not None:
                document = load_version(
                    config.fuzzy_system_id, config.fuzzy_version_id, user_dir
                )
            else:
                document = load_document(config.fuzzy_system_id, user_dir)
            return system_from_dict(document)
        except FileNotFoundError:
            return None
        except FuzzyModelError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def _config_and_system(self, sid: str) -> tuple[SupervisorConfig, FuzzySystem]:
        """The saved config and its fuzzy system (404 when either is unknown)."""
        config = _config_or_422(self.get_supervisor(sid))
        system = self._system_or_none(config)
        if system is None:
            raise HTTPException(
                status_code=404, detail=f"unknown fuzzy system: {config.fuzzy_system_id}"
            )
        return config, system

    def _data(self, dataset_id: str, end_s: float | None) -> ReplayData:
        """The record in seconds, cut after ``end_s`` (422 when nothing is left)."""
        t_s, columns = self.load_seconds(dataset_id)
        keep = np.ones(len(t_s), dtype=bool) if end_s is None else t_s <= end_s
        if not keep.any():
            raise HTTPException(status_code=422, detail="no samples up to the requested time")
        return ReplayData(t_s[keep], {tag: values[keep] for tag, values in columns.items()})

    def _loops(self, dataset_id: str, config: SupervisorConfig) -> list[LoopTags]:
        """The dataset's loops; 404 when a gating or target loop is not among them."""
        loops = self.load_loops(dataset_id)
        known = {loop.name for loop in loops}
        for name in [config.target_loop, *(gate.loop for gate in config.gates)]:
            if name not in known:
                raise HTTPException(status_code=404, detail=f"unknown loop: {name}")
        return loops


def build_supervisor_router(
    root: Path, load_seconds: SecondsLoader, load_loops: LoopsLoader
) -> APIRouter:
    """Routes for supervisor configs and logs under ``root`` and for advice on its datasets.

    Args:
        root: The data root (also holds the fuzzy rule bases the configs refer to).
        load_seconds: Reads a dataset into (time in seconds, columns by tag).
        load_loops: The control loops of a dataset (module 1 definition), 404 if unknown.
    """
    router = APIRouter()
    endpoints = _SupervisorEndpoints(root, load_seconds, load_loops)
    for path, method, handler in _route_table(endpoints):
        router.add_api_route(path, handler, methods=[method])
    return router


def _route_table(endpoints: _SupervisorEndpoints) -> list[tuple[str, str, Callable[..., Any]]]:
    """The (path, HTTP method, handler) of every supervisor route."""
    one = "/supervisors/{sid}"
    on_dataset = "/datasets/{dataset_id}/supervisor/{sid}"
    return [
        ("/supervisors", "GET", endpoints.list_supervisors),
        (one, "GET", endpoints.get_supervisor),
        (one, "PUT", endpoints.put_supervisor),
        (f"{on_dataset}/advise", "POST", endpoints.post_advise),
        (f"{on_dataset}/replay", "POST", endpoints.post_replay),
        (f"{one}/log", "GET", endpoints.get_log),
        (f"{one}/log/{{advice_id}}/ack", "POST", endpoints.post_ack),
    ]


def _config_or_422(document: dict[str, Any]) -> SupervisorConfig:
    """The validated config, or HTTP 422 with the SupervisorConfigError message."""
    try:
        return load_config(document)
    except SupervisorConfigError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _check_or_422(config: SupervisorConfig, system: FuzzySystem) -> None:
    """Require the config's output to exist in the system, else HTTP 422."""
    try:
        check_against_system(config, system)
    except SupervisorConfigError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _guarded(action: Callable[[], T]) -> T:
    """Run a supervisor computation; unusable input (replay or fuzzy errors) becomes HTTP 422."""
    try:
        return action()
    except (ReplayError, FuzzyModelError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    """Write a JSON file so a reader never sees half of it (temporary file, then replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
