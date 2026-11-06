"""HTTP routes of the advisory supervisor (ADR 010): configs, one-off advice, replay, audit log.

Configs are kept in ``<data root>/_supervisor``, advisory logs in ``<data root>/_advisory/<id>``.
The writes are a config (PUT), log appends (replay with ``record`` and ack) and, only through
``POST /supervisors/{sid}/propose`` (see supervisor_propose), setpoint proposals to the Write
Gateway. Dataset replay and advice never reach the gateway: the supervisor advises, a human decides.
"""

from __future__ import annotations

import dataclasses
import json
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
from crosscut_supervisor.proposal import ProposalContext
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
from pydantic import BaseModel, ConfigDict, Field

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.gateway_client import FileGatewayClient
from crosscut_api.supervisor_live import catalog_sp_tag, read_live_sp
from crosscut_api.supervisor_propose import (
    ProposedStore,
    SupervisorProposeRequest,
    advice_record,
    already_proposed,
    build_or_409,
    check_fresh,
    check_modes,
    delta_of,
    gateway_mode_of,
    manual_delta,
    refuse,
    require_actor,
    send_once,
    write_json_atomic,
)

CONFIG_DIR_NAME = "_supervisor"
LOG_DIR_NAME = "_advisory"
FUZZY_DIR_NAME = "_fuzzy"
SID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
RESERVED_SIDS = frozenset({"proposed"})  # proposed.json lives beside the configs
DEFAULT_WINDOW_S = 1800.0
DEFAULT_STEP_S = 300.0
Sid = Annotated[str, PathParam(pattern=SID_PATTERN)]
ActorDep = Annotated[ActorContext, Depends(actor_of)]
SecondsLoader = Callable[[str], tuple[np.ndarray, dict[str, Any]]]
LoopsLoader = Callable[[str], list[LoopTags]]
GatewayProvider = Callable[[], FileGatewayClient | None]
T = TypeVar("T")


class AdviseRequest(BaseModel):
    """The moment to advise at. There is no ``propose`` here: replay never reaches the gateway."""

    model_config = ConfigDict(extra="forbid")

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
        self._proposed = ProposedStore(root)

    def list_supervisors(self) -> list[str]:
        """Ids of the saved supervisor configurations, sorted."""
        folder = self.root / CONFIG_DIR_NAME
        if not folder.is_dir():
            return []
        return sorted(p.stem for p in folder.glob("*.json") if p.stem not in RESERVED_SIDS)

    def get_supervisor(self, sid: Sid) -> dict[str, Any]:
        """One saved configuration as stored (404 when unknown)."""
        path = self._config_path(sid)
        if sid in RESERVED_SIDS or not path.is_file():
            raise HTTPException(status_code=404, detail=f"unknown supervisor: {sid}")
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return document

    def put_supervisor(self, sid: Sid, document: dict[str, Any]) -> dict[str, Any]:
        """Validate and save a configuration (422 with the reason when it is not acceptable)."""
        config = _config_or_422(document)
        if sid in RESERVED_SIDS:
            raise HTTPException(status_code=422, detail=f"id: {sid!r} is reserved")
        if config.id != sid:
            raise HTTPException(status_code=422, detail=f"id: {config.id!r} does not match {sid!r}")
        system = self._system_or_none(config)
        if system is not None:
            _check_or_422(config, system)
        write_json_atomic(self._config_path(sid), document)
        return document

    def post_advise(
        self, dataset_id: str, sid: Sid, request: AdviseRequest
    ) -> dict[str, Any]:
        """Advise once on the window ending at ``t_s``; advice only, nothing is proposed."""
        config, system = self._config_and_system(sid)
        data = self._data(dataset_id, request.t_s)
        window = (float(data.t_s[-1]), DEFAULT_WINDOW_S)
        advice, gate = _guarded(
            lambda: advise_at(system, config, (data, self._loops(dataset_id, config)), window)
        )
        return {
            "advice": None if advice is None else advice.to_record(),
            "gate": {"state": gate.state, "reasons": list(gate.reasons)},
        }

    def post_propose(
        self, sid: Sid, body: SupervisorProposeRequest, actor: ActorDep
    ) -> dict[str, Any]:
        """Propose logged advice as a setpoint write proposal (rules: supervisor_propose).

        The new setpoint is the live setpoint (site connector) plus the advised delta. In confirm
        mode the proposal queues for human approval; in supervised mode it is applied directly.
        """
        who = require_actor(actor)
        config = _config_or_422(self.get_supervisor(sid))
        client = self._gateway_client()
        check_modes(config.mode, gateway_mode_of(client), who)
        if config.max_step is None:
            raise refuse(409, "max_step_unset")
        advice_id, delta, sentence = self._resolve_move(sid, config, body)
        self._refuse_if_proposed(advice_id)
        ctx = self._context(config, who, config.max_step)
        proposal = build_or_409(advice_id, delta, sentence, ctx)
        decision = send_once(client, self._proposed, proposal, who)
        return {
            "proposal": proposal.to_gateway_args(),
            "decision": decision,
            "advice_id": advice_id,
            "mode": config.mode,
            "queues_for_approval": config.mode == "confirm",
        }

    def _resolve_move(
        self, sid: str, config: SupervisorConfig, body: SupervisorProposeRequest
    ) -> tuple[str, float, str]:
        """(advice id, signed delta, reason sentence) of a fresh advice or a bounded manual move."""
        if body.direction is not None:
            delta, sentence, advice_id = manual_delta(body, float(config.max_step or 0.0))
            return advice_id, delta, sentence
        record = advice_record(self._log(sid), body.advice_id)
        if record.get("target_loop") != config.target_loop:
            raise refuse(409, "advice_loop_mismatch")
        check_fresh(record, config, time.time_ns())
        delta, sentence = delta_of(record)
        return str(record["advice_id"]), delta, sentence

    def _refuse_if_proposed(self, advice_id: str) -> None:
        """409 ``already_proposed`` with the previous result when the advice was sent before."""
        previous = self._proposed.get(advice_id)
        if previous is not None:
            raise already_proposed(previous)

    def _context(
        self, config: SupervisorConfig, actor: ActorContext, max_step: float
    ) -> ProposalContext:
        """Live setpoint, target tag and send time for the proposal (409 when unavailable)."""
        tag = self._resolve_target_tag(config)
        live = read_live_sp(self.root, tag)
        return ProposalContext(live, tag, actor.actor, max_step, time.time_ns())

    def _gateway_client(self) -> FileGatewayClient:
        """Return the active Write Gateway client or raise HTTP 503."""
        if self.gateway_provider is None:
            raise HTTPException(status_code=503, detail="Write Gateway not configured")
        client = self.gateway_provider()
        if client is None:
            raise HTTPException(status_code=503, detail="Write Gateway is offline or stale")
        return client

    def _resolve_target_tag(self, config: SupervisorConfig) -> str:
        """The setpoint tag from the supervisor config or the site catalogue, never a request."""
        tag = config.target_tag or catalog_sp_tag(self.root, config.target_loop)
        if not tag:
            raise refuse(409, "no_target_tag")
        return tag

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
