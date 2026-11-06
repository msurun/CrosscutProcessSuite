"""HTTP routes of the advisory supervisor (ADR 010): configs, one-off advice, replay, audit log.

Configs are kept in ``<data root>/_supervisor``, advisory logs in ``<data root>/_advisory/<id>``.
The only writes are a config (PUT) and log appends (replay with ``record`` and ack). Nothing
here reaches a plant: the supervisor advises, a human decides.
"""

from __future__ import annotations

import dataclasses
import json
import math
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
from crosscut_supervisor.advise import Advice
from crosscut_supervisor.audit import AckRequest, AuditError, AuditLog, ack
from crosscut_supervisor.config import (
    SupervisorConfig,
    SupervisorConfigError,
    check_against_system,
    load_config,
)
from crosscut_supervisor.proposal import build_setpoint_proposal
from crosscut_supervisor.replay import (
    ReplayData,
    ReplayError,
    ReplaySettings,
    advise_at,
    advise_series,
    replay_to_log,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.gateway_client import FileGatewayClient

CONFIG_DIR_NAME = "_supervisor"
LOG_DIR_NAME = "_advisory"
FUZZY_DIR_NAME = "_fuzzy"
SID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
DEFAULT_WINDOW_S = 1800.0
DEFAULT_STEP_S = 300.0
Sid = Annotated[str, PathParam(pattern=SID_PATTERN)]
ActorDep = Annotated[ActorContext, Depends(actor_of)]
SecondsLoader = Callable[[str], tuple[np.ndarray, dict[str, Any]]]
LoopsLoader = Callable[[str], list[LoopTags]]
GatewayProvider = Callable[[], FileGatewayClient | None]
T = TypeVar("T")


class AdviseRequest(BaseModel):
    """The moment to advise at, and whether to submit setpoint write proposals."""

    t_s: float | None = None
    propose: bool = False


class SupervisorProposeRequest(BaseModel):
    """Parameters to propose supervisor advice as a setpoint write proposal (ADR 014 section 7)."""

    current_sp: float
    target_tag: str | None = None
    advice_id: str | None = None
    direction: str | None = None
    magnitude: float | None = None
    reason: str | None = None


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

    def __init__(
        self,
        root: Path,
        load_seconds: SecondsLoader,
        load_loops: LoopsLoader,
        gateway_provider: GatewayProvider | None = None,
    ) -> None:
        self.root = root
        self.load_seconds = load_seconds
        self.load_loops = load_loops
        self.gateway_provider = gateway_provider

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

    def post_advise(
        self,
        dataset_id: str,
        sid: Sid,
        request: AdviseRequest,
        actor: ActorDep = None,
    ) -> dict[str, Any]:
        """Advise once on the window ending at ``t_s``; optionally propose write to gateway."""
        config, system = self._config_and_system(sid)
        data = self._data(dataset_id, request.t_s)
        t_end = float(data.t_s[-1])
        window = (t_end, DEFAULT_WINDOW_S)
        advice, gate = _guarded(
            lambda: advise_at(system, config, (data, self._loops(dataset_id, config)), window)
        )
        proposal_result: dict[str, Any] | None = None
        if request.propose and advice is not None and advice.direction != "hold":
            proposal_result = self._propose_advice_on_dataset(config, advice, data, actor)
        return {
            "advice": None if advice is None else advice.to_record(),
            "gate": {"state": gate.state, "reasons": list(gate.reasons)},
            "proposal": proposal_result,
        }

    def _propose_advice_on_dataset(
        self,
        config: SupervisorConfig,
        advice: Advice,
        data: ReplayData,
        actor: ActorContext | None,
    ) -> dict[str, Any]:
        """Propose an evaluated advice on a dataset to the Write Gateway."""
        client = self._gateway_client()
        target_tag = self._resolve_target_tag(config, None)
        current_sp = self._read_sp_from_data(data, target_tag, config.target_loop)
        actor_ctx = actor or ActorContext(actor=f"supervisor:{config.id}", roles=("operator",))
        proposal = build_setpoint_proposal(
            advice=advice,
            current_sp=current_sp,
            target_tag=target_tag,
            proposer=actor_ctx.actor,
        )
        if proposal is None:
            return {"accepted": False, "reason_code": "hold"}
        args = proposal.to_gateway_args()
        decision = client.propose(args, actor_ctx)
        return {"proposal": args, "decision": decision}

    def _read_sp_from_data(
        self, data: ReplayData, target_tag: str, target_loop: str
    ) -> float:
        """Read the current setpoint from the dataset series for target_tag or loop."""
        for candidate in (target_tag, f"{target_loop}.SP", f"{target_loop}_sp"):
            if candidate in data.columns and len(data.columns[candidate]) > 0:
                val = float(data.columns[candidate][-1])
                if not math.isnan(val):
                    return val
        return 0.0

    def post_propose(
        self,
        sid: Sid,
        body: SupervisorProposeRequest,
        actor: ActorDep = None,
    ) -> dict[str, Any]:
        """Propose supervisor advice as a setpoint write proposal to Write Gateway.

        Follows ADR 014 section 7: proposals flow to Write Gateway in confirm or
        supervised mode.

        # In plain words:
        Resolves the setpoint target tag and recommended adjustment from either a logged
        advice record or explicit parameters. Adds the signed delta to current_sp, binds
        the reason from the dominant fuzzy rule, and sends the proposal to Write Gateway.
        In confirm mode this queues the proposal for operator review; in supervised mode
        it writes directly to the control system.
        """
        config = _config_or_422(self.get_supervisor(sid))
        if config.mode == "off":
            raise HTTPException(status_code=409, detail="supervisor mode is off")

        client = self._gateway_client()
        target_tag = self._resolve_target_tag(config, body.target_tag)
        delta_sp, reason_text, advice_id, t_ns = self._resolve_delta_and_reason(sid, body)
        new_sp = body.current_sp + delta_sp
        actor_ctx = actor or ActorContext(
            actor=f"supervisor:{sid}",
            roles=("operator",),
            session="0" * 16,
            source_ip="127.0.0.1",
            stepup=False,
            permissions=None,
        )

        proposal_args = {
            "target_tag": target_tag,
            "value": new_sp,
            "proposer": actor_ctx.actor or f"supervisor:{sid}",
            "t_ns": time.time_ns(),
            "reason": reason_text,
        }
        try:
            decision = client.propose(proposal_args, actor_ctx)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "proposal": proposal_args,
            "decision": decision,
            "advice_id": advice_id,
        }

    def _gateway_client(self) -> FileGatewayClient:
        """Return the active Write Gateway client or raise HTTP 503."""
        if self.gateway_provider is None:
            raise HTTPException(status_code=503, detail="Write Gateway not configured")
        client = self.gateway_provider()
        if client is None:
            raise HTTPException(status_code=503, detail="Write Gateway is offline or stale")
        return client

    def _resolve_target_tag(self, config: SupervisorConfig, override: str | None) -> str:
        """Resolve the setpoint target tag from override, config, or site catalog."""
        if override:
            return override
        if config.target_tag:
            return config.target_tag
        sp_tag = self._lookup_site_sp(config.target_loop)
        if sp_tag:
            return sp_tag
        return config.target_loop

    def _lookup_site_sp(self, loop_id: str) -> str | None:
        """Look up the setpoint tag of a loop from the site catalog if present."""
        site_file = self.root / "_site" / "site.json"
        if not site_file.is_file():
            return None
        try:
            site_doc = json.loads(site_file.read_text(encoding="utf-8"))
            for loop in site_doc.get("loops", []):
                if loop.get("id") == loop_id or loop.get("name") == loop_id:
                    return loop.get("sp") or None
        except Exception:
            return None
        return None

    def _resolve_delta_and_reason(
        self, sid: str, body: SupervisorProposeRequest
    ) -> tuple[float, str, str, int]:
        """Extract signed setpoint delta, reason, advice_id, and timestamp."""
        if body.advice_id:
            return self._delta_from_advice_id(sid, body.advice_id)
        if body.direction and body.magnitude is not None:
            mag = float(body.magnitude)
            delta = mag if body.direction == "increase" else (
                -mag if body.direction == "decrease" else 0.0
            )
            if delta == 0.0:
                raise HTTPException(status_code=422, detail="direction is hold or delta is zero")
            now_ns = time.time_ns()
            reason = body.reason or f"Supervisor {sid} proposal: {body.direction} {body.magnitude}"
            return delta, reason, f"manual-{now_ns}", now_ns
        return self._delta_from_latest_advice(sid)

    def _delta_from_advice_id(self, sid: str, advice_id: str) -> tuple[float, str, str, int]:
        """Extract delta and reason from a specific advice record in the audit log."""
        record = self._log(sid).find_advice(advice_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"unknown advice: {advice_id}")
        direction, mag = record.get("direction", "hold"), record.get("magnitude")
        if direction == "hold" or mag is None or mag <= 0:
            raise HTTPException(status_code=422, detail="advice is hold or has no magnitude")
        delta = float(mag) if direction == "increase" else -float(mag)
        explanations = record.get("explanation", [])
        reason = explanations[0]["sentence"] if explanations else f"Supervisor {sid} advice"
        return delta, reason, advice_id, int(record.get("t_ns", time.time_ns()))

    def _delta_from_latest_advice(self, sid: str) -> tuple[float, str, str, int]:
        """Extract delta and reason from the latest advice record in the audit log."""
        records = [r for r in self._log(sid).records() if r.get("kind") == "advice"]
        if not records:
            raise HTTPException(status_code=422, detail="no advice records in audit log")
        last = records[-1]
        advice_id = str(last.get("advice_id", ""))
        return self._delta_from_advice_id(sid, advice_id)

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
    root: Path,
    load_seconds: SecondsLoader,
    load_loops: LoopsLoader,
    gateway_provider: GatewayProvider | None = None,
) -> APIRouter:
    """Routes for supervisor configs and logs under ``root`` and for advice on its datasets.

    Args:
        root: The data root (also holds the fuzzy rule bases the configs refer to).
        load_seconds: Reads a dataset into (time in seconds, columns by tag).
        load_loops: The control loops of a dataset (module 1 definition), 404 if unknown.
        gateway_provider: Optional provider returning an active FileGatewayClient.
    """
    router = APIRouter()
    endpoints = _SupervisorEndpoints(root, load_seconds, load_loops, gateway_provider)
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
        (f"{one}/propose", "POST", endpoints.post_propose),
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
