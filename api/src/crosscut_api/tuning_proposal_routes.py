"""HTTP routes of the tuning write path: propose, list, approve, reject, roll back (ADR 014).

A proposal is a record in <data root>/_tuning/proposals (see tuning_store). Creating one rebuilds
the tuning report, reads the CURRENT parameter values live through the connector of the loop's
loop_kpi job, builds the record with crosscut_loops.tuning_proposal and sends the signed command
propose_params to the Write Gateway process through FileGatewayClient. Approve and reject send
the gateway key of the record. The gateway decides and writes; this module only keeps the
record in step with what the gateway reports. It must not import crosscut_gateway.

Error codes (HTTPException detail): 404 unknown_proposal / unknown_loop, 409 no_kpi_job,
no_live_values, no_param_targets, not_queued, not_applied, 422 the ProposalRefused code,
403 self_approval or forbidden, 428 step-up, 503 gateway not running.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol

from crosscut_connectors.registry import connector_from_source
from crosscut_loops.tuning_proposal import (
    ProposalRefused,
    ProposalRequest,
    Scaling,
    Stamp,
    build_proposal,
    build_rollback,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.gateway_routes import _gateway_errors as gateway_errors
from crosscut_api.tuning_build import (
    ConnectorFactory,
    ReportSpec,
    Sources,
    build_report,
    pv_span_of,
    read_current,
    running_kpi_job,
    site_loop,
    wanted_targets,
)
from crosscut_api.tuning_gateway import (
    FORBIDDEN_REFUSALS,
    KEEPS_QUEUED,
    applied_block,
    decision_status,
    external_change,
    ns_to_iso,
    param_targets,
    propose_args,
    queued_key,
    safe_code,
)
from crosscut_api.tuning_store import (
    LockedRecord,
    ProposalNotFound,
    ProposalStore,
    Record,
    StoreBusy,
    TransitionRefused,
    merged_view,
)

ActorDep = Annotated[ActorContext, Depends(actor_of)]
IDENTIFIER = r"^[A-Za-z0-9_.:-]+$"
AUDIT_LIMIT = 1000
POLL_S = 0.05
REFUSAL_STATUSES = (403, 409, 422)
Snapshot = tuple[list[dict[str, Any]], list[dict[str, Any]]]


class HistoryWindow(BaseModel):
    """A window of the runtime history store (UTC)."""

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _ordered(self) -> HistoryWindow:
        """The window must have a positive length."""
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class ProposalBody(BaseModel):
    """What to propose: the data window (a dataset or the history), vendor form and method."""

    vendor_form: str = Field(min_length=1, max_length=64)
    method: Literal["simc", "amigo", "amigo_pid"]
    reason: str = Field(min_length=1, max_length=1000)
    dataset_id: str | None = None
    history: HistoryWindow | None = None
    start_s: float | None = None
    end_s: float | None = None
    robustness: float = Field(default=0.5, ge=0.0, le=1.0)
    step_test_id: str | None = Field(default=None, pattern=IDENTIFIER, max_length=128)
    pv_span: float | None = Field(default=None, gt=0.0)
    out_span: float = Field(default=100.0, gt=0.0)

    @model_validator(mode="after")
    def _one_window(self) -> ProposalBody:
        """Exactly one of dataset_id and history names the data."""
        if (self.dataset_id is None) == (self.history is None):
            raise ValueError("give exactly one of dataset_id and history")
        return self

    def spec(self, pv_span: float | None) -> ReportSpec:
        """The report inputs, with the PV span to normalise the ABB gain with."""
        window = None if self.history is None else (self.history.start, self.history.end)
        return ReportSpec(
            self.dataset_id, window, self.start_s, self.end_s, self.robustness,
            pv_span, self.out_span,
        )  # fmt: skip


class RollbackBody(BaseModel):
    """Optional reason text of a rollback."""

    reason: str = Field(default="rollback", min_length=1, max_length=1000)


class TuningGateway(Protocol):
    """What the tuning routes need from the gateway client."""

    def live_policy(self) -> dict[str, Any] | None:
        """The verified live policy {"document", "pin"}, or None."""

    def pending_params(self) -> list[dict[str, Any]]:
        """The queued PID parameter sets, each with its key and proposal_id."""

    def audit(self, limit: int) -> dict[str, Any]:
        """The newest audit records and the chain flag."""

    def propose_params(
        self, args: dict[str, Any], actor: ActorContext | None = None
    ) -> dict[str, Any]:
        """Send propose_params; returns the decision {accepted, reason_code}."""

    def approve(self, key: str, actor: ActorContext | None = None) -> dict[str, Any]:
        """Approve a queued set; returns the decision {accepted, reason_code}."""

    def reject(self, key: str, actor: ActorContext | None = None) -> None:
        """Discard a queued set."""


@dataclass(frozen=True)
class TuningDeps:
    """Collaborators of the tuning routes (replaced by fakes in tests)."""

    sources: Sources
    provider: Callable[[], TuningGateway | None]
    connector_factory: ConnectorFactory = connector_from_source
    clock: Callable[[], float] = time.time
    wait_s: float = 3.0
    store: ProposalStore = field(init=False)

    def __post_init__(self) -> None:
        """Open the proposal store of the data root."""
        object.__setattr__(self, "store", ProposalStore(self.sources.root))


@contextmanager
def _store_errors() -> Iterator[None]:
    """Translate store failures into HTTP errors."""
    try:
        yield
    except ProposalNotFound as err:
        raise HTTPException(status_code=404, detail="unknown_proposal") from err
    except TransitionRefused as err:
        raise HTTPException(status_code=409, detail=f"transition_refused: {err}") from err
    except StoreBusy as err:
        raise HTTPException(status_code=503, detail="proposal_busy") from err


def _poll(probe: Callable[[], Any], wait_s: float) -> Any:
    """The first truthy result of ``probe`` within ``wait_s`` seconds, else None."""
    deadline = time.monotonic() + wait_s
    while True:
        result = probe()
        if result or time.monotonic() >= deadline:
            return result or None
        time.sleep(POLL_S)


def _has_status(actual: str, wanted: str) -> bool:
    """True when ``actual`` is ``wanted`` or a ``wanted:<detail>`` status (e.g. refused:x)."""
    return actual == wanted or actual.startswith(f"{wanted}:")


def _proposal_refused(error: ProposalRefused) -> HTTPException:
    """HTTP 422 carrying the ProposalRefused code and message."""
    return HTTPException(status_code=422, detail={"code": error.code, "message": error.message})


class _Endpoints:
    """Route handlers bound to the collaborators."""

    def __init__(self, deps: TuningDeps) -> None:
        self.deps = deps
        self.store = deps.store
        self._wait = deps.wait_s

    def _gw(self) -> TuningGateway:
        """The running gateway client, or HTTP 503."""
        gateway = self.deps.provider()
        if gateway is None:
            raise HTTPException(status_code=503, detail="gateway not running")
        return gateway

    def _now_ns(self) -> int:
        """The current time in UTC nanoseconds."""
        return int(self.deps.clock() * 1e9)

    def _stamp(self, actor: ActorContext) -> Stamp:
        """A fresh record id and creation stamp for the acting engineer."""
        now = datetime.fromtimestamp(self.deps.clock(), UTC)
        return Stamp(str(uuid.uuid4()), actor.actor, now)

    def _view(self, record: Record) -> Record:
        """The record merged with its review file."""
        return merged_view(record, self.store.read_review(record["id"]))

    def _change(self, proposal_id: str, mutate: Callable[[Record], Record | None]) -> Record:
        """Apply ``mutate`` to the record under its lock; None from it means no change."""
        with self.store.exclusive(proposal_id) as locked:
            new = mutate(locked.record)
            return locked.record if new is None else locked.save(new)

    def _close(self, proposal_id: str, status: str) -> Record:
        """Move an open record to a terminal status (no-op when it is no longer open)."""

        def mutate(record: Record) -> Record | None:
            if record["status"] not in ("draft", "queued"):
                return None
            return {**record, "status": status}

        return self._change(proposal_id, mutate)

    # -- create ----------------------------------------------------------------------------

    def post_proposal(self, loop_id: str, body: ProposalBody, actor: ActorDep) -> Record:
        """POST /loops/{loop_id}/tuning/proposals: build, store and send a proposal."""
        actor.require("gw.propose")
        gateway = self._gw()
        sources = self.deps.sources
        site, loop_doc = site_loop(sources.root, loop_id)
        job = running_kpi_job(sources.root, loop_id, self.deps.clock())
        targets = self._targets(gateway, loop_id, body.method)
        span = body.pv_span or pv_span_of(site, loop_doc)
        report, window = build_report(sources, loop_doc, body.spec(span))
        current = read_current(site, str(job["source"]), targets, self.deps.connector_factory)
        scaling = Scaling(span, body.out_span)
        request = ProposalRequest(
            loop_id, body.vendor_form, body.method, targets, window, body.step_test_id, scaling
        )
        record = self._build(report, request, current, actor)
        return self._store_and_send(gateway, record, (actor, body.reason))

    def _build(
        self, report: Any, request: ProposalRequest, current: dict[str, float], actor: ActorContext
    ) -> Record:
        """The draft record of the proposal; 422 with the ProposalRefused code when refused."""
        try:
            return build_proposal(report, request, current, self._stamp(actor))
        except ProposalRefused as error:
            raise _proposal_refused(error) from error

    def _targets(self, gateway: TuningGateway, loop_id: str, method: str) -> dict[str, str]:
        """The policy target tag per parameter the method writes; 409 when there are none."""
        with gateway_errors():
            policy = gateway.live_policy()
        targets = wanted_targets(method, param_targets(policy, loop_id))
        if not targets:
            raise HTTPException(status_code=409, detail="no_param_targets")
        return targets

    def _store_and_send(
        self, gateway: TuningGateway, record: Record, sender: tuple[ActorContext, str]
    ) -> Record:
        """Save a new draft, send it to the gateway and record the gateway's decision."""
        actor, reason = sender
        with _store_errors():
            self.store.create(record)
        args = propose_args(record, actor.actor, time.time_ns(), reason)
        try:
            with gateway_errors(value_error_status=422):
                decision = gateway.propose_params(args, actor=actor)
        except HTTPException as error:
            if error.status_code in REFUSAL_STATUSES:
                self._close(record["id"], f"refused:{safe_code(str(error.detail))}")
            raise
        return self._record_decision(gateway, record, decision)

    def _record_decision(
        self, gateway: TuningGateway, record: Record, decision: dict[str, Any]
    ) -> Record:
        """Store the status and gateway key the decision implies; return view plus decision."""
        status = decision_status(decision)
        key = None
        if status == "queued":
            key = _poll(lambda: queued_key(gateway.pending_params(), record["id"]), self._wait)
            status = "queued" if key else "draft"  # no key visible yet: GET reconciles it later
        with _store_errors():
            saved = self._change(
                record["id"], lambda r: {**r, "status": status, "gateway_key": key}
            )
        return {**self._view(saved), "decision": decision}

    # -- read ------------------------------------------------------------------------------

    def get_proposals(self, loop_id: str | None = None, status: str | None = None) -> list[Record]:
        """GET /tuning/proposals: records (newest first), filtered by loop and status."""
        snapshot = self._snapshot()
        views = [self._view(self._refresh(r, snapshot)) for r in self.store.list_records()]
        if loop_id is not None:
            views = [v for v in views if v["loop_id"] == loop_id]
        if status is not None:
            views = [v for v in views if _has_status(v["status"], status)]
        return views

    def get_proposal(self, proposal_id: str) -> Record:
        """GET /tuning/proposals/{id}: the record merged with its review."""
        with _store_errors():
            record = self.store.get(proposal_id)
        return self._view(self._refresh(record, self._snapshot()))

    def _snapshot(self) -> Snapshot | None:
        """(pending parameter sets, audit records) of the gateway, or None when unreadable."""
        gateway = self.deps.provider()
        if gateway is None:
            return None
        try:
            return gateway.pending_params(), list(gateway.audit(AUDIT_LIMIT)["records"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _refresh(self, record: Record, snapshot: Snapshot | None) -> Record:
        """Bring a record in step with the gateway: late key, lost queue entry, outside change."""
        if snapshot is None:
            return record
        try:
            return self._change(record["id"], self._reconciler(*snapshot))
        except (ProposalNotFound, TransitionRefused, StoreBusy):
            return record

    def _reconciler(
        self, pending: list[dict[str, Any]], audit: list[dict[str, Any]]
    ) -> Callable[[Record], Record | None]:
        """The change that reconciles one record with a gateway snapshot (None = nothing)."""

        def mutate(record: Record) -> Record | None:
            status = record["status"]
            key = queued_key(pending, record["id"])
            if status == "draft" and key is not None:
                return {**record, "status": "queued", "gateway_key": key}
            if status == "queued" and key is None and self._expired(record):
                return {**record, "status": "expired"}
            if status == "applied":
                return self._flag_external(record, audit)
            return None

        return mutate

    def _expired(self, record: Record) -> bool:
        """True when the record's expiry time has passed."""
        return bool(ns_to_iso(self._now_ns()) >= record["expires_at"])

    @staticmethod
    def _flag_external(record: Record, audit: list[dict[str, Any]]) -> Record | None:
        """Set applied.invalid when the audit shows the DCS value changed outside the path."""
        applied = record["applied"]
        if applied.get("invalid") or not external_change(audit, record):
            return None
        return {**record, "applied": {**applied, "invalid": "param_changed_externally"}}

    # -- approve / reject / rollback -------------------------------------------------------

    def post_approve(self, proposal_id: str, actor: ActorDep) -> Record:
        """POST /tuning/proposals/{id}/approve: a second person approves; the gateway applies."""
        actor.require("gw.approve.tuning")
        gateway = self._gw()
        with _store_errors(), self.store.exclusive(proposal_id) as locked:
            record = locked.record
            self._require_status(record, "queued")
            if record["created_by"] == actor.actor:
                raise HTTPException(status_code=403, detail="self_approval")
            self._approve_at_gateway(gateway, locked, actor)
            applied = self._applied_values(gateway, record, actor)
            saved = locked.save({**record, "status": "applied", "applied": applied})
        return self._view(saved)

    @staticmethod
    def _require_status(record: Record, expected: str) -> None:
        """409 not_queued / not_applied unless the record has the status (queued needs a key)."""
        if record["status"] != expected:
            raise HTTPException(status_code=409, detail=f"not_{expected}")
        if expected == "queued" and not record["gateway_key"]:
            raise HTTPException(status_code=409, detail="no_gateway_key")

    def _approve_at_gateway(
        self, gateway: TuningGateway, locked: LockedRecord, actor: ActorContext
    ) -> None:
        """Send approve for the record's key; map refusals to HTTP and to the record status."""
        try:
            with gateway_errors():
                decision = gateway.approve(locked.record["gateway_key"], actor=actor)
        except HTTPException as error:
            if error.status_code == 404:  # the gateway no longer holds the set
                locked.save({**locked.record, "status": "expired"})
            raise
        if not decision.get("accepted"):
            self._refused_approve(locked, str(decision.get("reason_code", "refused")))

    @staticmethod
    def _refused_approve(locked: LockedRecord, code: str) -> None:
        """Raise the HTTP error of a refused approve; close the record unless it stays queued."""
        if code in FORBIDDEN_REFUSALS:
            raise HTTPException(status_code=403, detail=code)
        if code not in KEEPS_QUEUED:
            status = "expired" if code == "expired" else f"refused:{safe_code(code)}"
            locked.save({**locked.record, "status": status})
        raise HTTPException(status_code=409, detail=code)

    def _applied_values(
        self, gateway: TuningGateway, record: Record, actor: ActorContext
    ) -> Record:
        """The applied block from the gateway audit (item values when the audit lags behind).

        The gateway answers accepted only after every write was read back within tolerance, so
        the item values are a sound fallback when state.json has not caught up with the audit.
        """

        def probe() -> Record | None:
            return applied_block(gateway.audit(AUDIT_LIMIT)["records"], record, actor.actor)

        block: Record | None = _poll(probe, self._wait)
        if block is not None:
            return block
        items = record["items"]
        return {
            "from_read": {i["target"]: i["from"] for i in items},
            "to_read": {i["target"]: i["to"] for i in items},
            "t": ns_to_iso(self._now_ns()),
            "approver": actor.actor,
        }

    def post_reject(self, proposal_id: str, actor: ActorDep) -> Record:
        """POST /tuning/proposals/{id}/reject: discard a draft or queued proposal."""
        actor.require("gw.reject")
        with _store_errors(), self.store.exclusive(proposal_id) as locked:
            record = locked.record
            if record["status"] not in ("draft", "queued"):
                raise HTTPException(status_code=409, detail="not_open")
            if record["gateway_key"]:
                self._reject_at_gateway(locked, actor)
            saved = locked.save({**record, "status": "rejected"})
        return self._view(saved)

    def _reject_at_gateway(self, locked: LockedRecord, actor: ActorContext) -> None:
        """Send reject for the key; a key the gateway no longer holds closes the record."""
        gateway = self._gw()
        try:
            with gateway_errors():
                gateway.reject(locked.record["gateway_key"], actor=actor)
        except HTTPException as error:
            if error.status_code == 404:
                locked.save({**locked.record, "status": "expired"})
            raise

    def post_rollback(
        self, proposal_id: str, actor: ActorDep, body: RollbackBody | None = None
    ) -> Record:
        """POST /tuning/proposals/{id}/rollback: propose putting the audited old values back."""
        actor.require("gw.propose")
        gateway = self._gw()
        with _store_errors():
            original = self.store.get(proposal_id)
        self._require_status(original, "applied")
        try:
            record = build_rollback(original, self._stamp(actor))
        except ProposalRefused as error:
            raise _proposal_refused(error) from error
        reason = (body or RollbackBody()).reason
        return self._store_and_send(gateway, record, (actor, reason))


def build_tuning_proposal_router(deps: TuningDeps) -> APIRouter:
    """Construct the router of the tuning proposal routes."""
    endpoints = _Endpoints(deps)
    router = APIRouter()
    create = "/loops/{loop_id}/tuning/proposals"
    router.add_api_route(create, endpoints.post_proposal, methods=["POST"], status_code=201)
    router.add_api_route("/tuning/proposals", endpoints.get_proposals, methods=["GET"])
    router.add_api_route("/tuning/proposals/{proposal_id}", endpoints.get_proposal, methods=["GET"])
    action = "/tuning/proposals/{proposal_id}"
    router.add_api_route(f"{action}/approve", endpoints.post_approve, methods=["POST"])
    router.add_api_route(f"{action}/reject", endpoints.post_reject, methods=["POST"])
    router.add_api_route(
        f"{action}/rollback", endpoints.post_rollback, methods=["POST"], status_code=201
    )
    return router
