"""HTTP routes of the tuning write path: propose, list, approve, reject, roll back (ADR 014).

A proposal is a record in <data root>/_tuning/proposals (see tuning_store). Creating one rebuilds
the tuning report, reads the CURRENT parameter values live through the connector of the loop's
loop_kpi job, builds the record with crosscut_loops.tuning_proposal and sends the signed command
propose_params to the Write Gateway process through FileGatewayClient. Approve and reject send
the gateway key of the record. The gateway decides and writes; this module only keeps the
record in step with what the gateway reports. It must not import crosscut_gateway.

Error codes (HTTPException detail): 404 unknown_proposal / unknown_loop, 409 no_kpi_job,
no_live_values, no_param_targets, not_queued, applying, not_applied, applied_unverified,
foreign_pending, 422 the ProposalRefused code, 403 self_approval or forbidden, 428 step-up,
503 gateway not running / gateway_state_unreadable (nothing is changed then), 504 the gateway
did not answer an approve (the record is then ``applying``, never expired).
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
from fastapi import APIRouter, Depends, HTTPException, Query
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
    ForeignPending,
    GatewaySnapshot,
    applied_from_snapshot,
    decision_status,
    param_targets,
    propose_args,
    queued_key,
    safe_code,
    snapshot_of,
    trusted_applied,
    unverified_block,
)
from crosscut_api.tuning_reconcile import plan
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
MAX_LIMIT = 200
DEFAULT_LIMIT = 100
MAX_RECONCILE = 50
GET_LOCK_TIMEOUT_S = 2.0
POLL_S = 0.05
REFUSAL_STATUSES = (403, 409, 422)


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

    def snapshot(self) -> dict[str, Any]:
        """Pending sets, applied map, param events and chain flag from one read of state."""

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


class _Settled(Exception):
    """The gateway had already applied the set: carries the record stored as applied."""

    def __init__(self, record: Record) -> None:
        super().__init__("already applied")
        self.record = record


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
        """The record merged with its review file (only an applied record has one)."""
        review = self.store.read_review(record["id"]) if record["status"] == "applied" else None
        return merged_view(record, review)

    def _change(
        self,
        proposal_id: str,
        mutate: Callable[[Record], Record | None],
        timeout_s: float | None = None,
    ) -> Record:
        """Apply ``mutate`` to the record under its lock; None from it means no change."""
        with self.store.exclusive(proposal_id, timeout_s) as locked:
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
            key = self._wait_for_key(gateway, record)
            status = "queued" if key else "draft"  # no key visible yet: GET reconciles it later
        with _store_errors():
            saved = self._change(
                record["id"], lambda r: {**r, "status": status, "gateway_key": key}
            )
        return {**self._view(saved), "decision": decision}

    def _wait_for_key(self, gateway: TuningGateway, record: Record) -> str | None:
        """The key of the set the gateway queued for the record; 409 when the set is not ours."""
        try:
            key: str | None = _poll(
                lambda: queued_key(gateway.pending_params(), record), self._wait
            )
        except ForeignPending as error:
            with _store_errors():
                self._close(record["id"], "refused:foreign_pending")
            raise HTTPException(status_code=409, detail="foreign_pending") from error
        return key

    # -- read ------------------------------------------------------------------------------

    def get_proposals(
        self,
        loop_id: str | None = None,
        status: str | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[Record]:
        """GET /tuning/proposals: records (newest first), filtered, one page.

        Reconciles at most MAX_RECONCILE records that really need it (and only when the gateway
        state is readable); the others show their stored state. Nothing else is written.
        """
        records = self.store.list_records()
        if loop_id is not None:
            records = [r for r in records if r["loop_id"] == loop_id]
        views = [self._view(r) for r in self._reconciled(records)]
        if status is not None:
            views = [v for v in views if _has_status(v["status"], status)]
        return views[offset : offset + limit]

    def _reconciled(self, records: list[Record]) -> list[Record]:
        """The records, the first MAX_RECONCILE that need it brought in step with the gateway."""
        snap = self._snapshot()
        if snap is None:
            return records
        budget, out = MAX_RECONCILE, []
        for record in records:
            if budget > 0 and plan(record, snap, self._now_ns()) is not None:
                budget -= 1
                record = self._refresh(record, snap)
            out.append(record)
        return out

    def get_proposal(self, proposal_id: str) -> Record:
        """GET /tuning/proposals/{id}: the record merged with its review."""
        with _store_errors():
            record = self.store.get(proposal_id)
        return self._view(self._refresh(record, self._snapshot()))

    def _snapshot(self) -> GatewaySnapshot | None:
        """One consistent read of the gateway state, or None when it is down or unreadable."""
        gateway = self.deps.provider()
        if gateway is None:
            return None
        try:
            return snapshot_of(gateway.snapshot())
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _refresh(self, record: Record, snap: GatewaySnapshot | None) -> Record:
        """Bring a record in step with the gateway under a short lock; busy = stored state."""
        if snap is None or plan(record, snap, self._now_ns()) is None:
            return record
        try:
            return self._change(
                record["id"], lambda r: plan(r, snap, self._now_ns()), GET_LOCK_TIMEOUT_S
            )
        except (ProposalNotFound, TransitionRefused, StoreBusy):
            return record

    # -- approve ---------------------------------------------------------------------------

    def post_approve(self, proposal_id: str, actor: ActorDep) -> Record:
        """POST /tuning/proposals/{id}/approve: a second person approves; the gateway applies."""
        actor.require("gw.approve.tuning")
        gateway = self._gw()
        with _store_errors(), self.store.exclusive(proposal_id) as locked:
            if locked.record["status"] == "applying":
                return self._view(self._settle_applying(locked))
            record = locked.record
            self._require_status(record, "queued")
            if record["created_by"] == actor.actor:
                raise HTTPException(status_code=403, detail="self_approval")
            try:
                saved = self._approve_and_store(gateway, locked, actor)
            except _Settled as done:
                saved = done.record
        return self._view(saved)

    @staticmethod
    def _require_status(record: Record, expected: str) -> None:
        """409 not_queued / not_applied unless the record has the status (queued needs a key)."""
        if record["status"] != expected:
            raise HTTPException(status_code=409, detail=f"not_{expected}")
        if expected == "queued" and not record["gateway_key"]:
            raise HTTPException(status_code=409, detail="no_gateway_key")

    def _settle_applying(self, locked: LockedRecord) -> Record:
        """Reconcile an applying record with the audit; 409 applying while it is still unknown."""
        snap = self._snapshot()
        change = None if snap is None else plan(locked.record, snap, self._now_ns())
        if change is None:
            raise HTTPException(status_code=409, detail="applying")
        return locked.save(change)

    def _approve_and_store(
        self, gateway: TuningGateway, locked: LockedRecord, actor: ActorContext
    ) -> Record:
        """Send approve and store applied (audit values), or applying while the audit lags."""
        decision = self._approve_at_gateway(gateway, locked, actor)
        block = self._applied_block(gateway, locked.record, (actor, decision))
        if block is None:  # accepted, but the ledger does not show it yet: never made up
            return locked.save({**locked.record, "status": "applying"})
        return locked.save({**locked.record, "status": "applied", "applied": block})

    def _approve_at_gateway(
        self, gateway: TuningGateway, locked: LockedRecord, actor: ActorContext
    ) -> dict[str, Any]:
        """Send approve for the record's key; map refusals to HTTP and to the record status."""
        try:
            with gateway_errors():
                decision = gateway.approve(locked.record["gateway_key"], actor=actor)
        except HTTPException as error:
            if error.status_code == 504:  # the gateway may still apply it: never expired
                locked.save({**locked.record, "status": "applying"})
            elif error.status_code == 404:  # the gateway no longer holds the set
                self._unknown_key(locked)
            raise
        if not decision.get("accepted"):
            self._refused_approve(locked, str(decision.get("reason_code", "refused")))
        return decision

    def _unknown_key(self, locked: LockedRecord) -> None:
        """The gateway does not know the key: applied (the ledger says so) or expired, else 503.

        Raises _Settled when the ledger shows the set was applied; stores expired and returns when
        the settled gateway state shows it was not; 503 when that state cannot be read.
        """
        snap: GatewaySnapshot | None = _poll(lambda: self._settled(locked.record), self._wait)
        if snap is None:
            raise HTTPException(status_code=503, detail="gateway_state_unreadable")
        change = plan(locked.record, snap, self._now_ns())
        if change is not None and change["status"] == "applied":
            raise _Settled(locked.save(change))
        locked.save({**locked.record, "status": "expired"})

    def _settled(self, record: Record) -> GatewaySnapshot | None:
        """A readable snapshot that no longer holds the key as pending, or shows the set applied."""
        snap = self._snapshot()
        if snap is None:
            return None
        held = any(e.get("key") == record["gateway_key"] for e in snap.pending)
        return None if held and str(record["id"]) not in snap.applied else snap

    @staticmethod
    def _refused_approve(locked: LockedRecord, code: str) -> None:
        """Raise the HTTP error of a refused approve; close the record unless it stays queued."""
        if code in FORBIDDEN_REFUSALS:
            raise HTTPException(status_code=403, detail=code)
        if code not in KEEPS_QUEUED:
            status = "expired" if code == "expired" else f"refused:{safe_code(code)}"
            locked.save({**locked.record, "status": status})
        raise HTTPException(status_code=409, detail=code)

    def _applied_block(
        self, gateway: TuningGateway, record: Record, accepted: tuple[ActorContext, dict[str, Any]]
    ) -> Record | None:
        """The applied block: from the gateway ledger, or the unverified block, or None.

        ``applied_unaudited`` (the gateway wrote but could not audit) stores no values at all.
        None means the ledger does not show the set yet (state.json lags); it stays applying.
        """
        actor, decision = accepted
        if decision.get("reason_code") == "applied_unaudited":
            return unverified_block(record, actor.actor, self._now_ns())

        def probe() -> Record | None:
            snap = self._snapshot()
            return None if snap is None else applied_from_snapshot(snap, record, actor.actor)

        block: Record | None = _poll(probe, self._wait)
        return block

    # -- reject / rollback -----------------------------------------------------------------

    def post_reject(self, proposal_id: str, actor: ActorDep) -> Record:
        """POST /tuning/proposals/{id}/reject: discard a draft or queued proposal."""
        actor.require("gw.reject")
        with _store_errors(), self.store.exclusive(proposal_id) as locked:
            record = locked.record
            if record["status"] not in ("draft", "queued"):
                raise HTTPException(status_code=409, detail="not_open")
            key = record["gateway_key"] or self._held_key(record)
            if key:
                self._reject_at_gateway(locked, actor, key)
            saved = locked.save({**record, "status": "rejected"})
        return self._view(saved)

    def _held_key(self, record: Record) -> str | None:
        """The key of the set the gateway holds for a record with no key (None = holds none).

        503 when the gateway state cannot be read: rejecting locally while the gateway still
        holds the set would leave a live proposal nobody can see.
        """
        snap = self._snapshot()
        if snap is None:
            raise HTTPException(status_code=503, detail="gateway_state_unreadable")
        try:
            return queued_key(snap.pending, record)
        except ForeignPending as error:
            raise HTTPException(status_code=409, detail="foreign_pending") from error

    def _reject_at_gateway(self, locked: LockedRecord, actor: ActorContext, key: str) -> None:
        """Send reject for the key; a key the gateway no longer holds closes the record."""
        gateway = self._gw()
        try:
            with gateway_errors():
                gateway.reject(key, actor=actor)
        except HTTPException as error:
            if error.status_code == 404:
                try:
                    self._unknown_key(locked)
                except _Settled as done:
                    raise HTTPException(status_code=409, detail="not_open") from done
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
        original = self._fresh_applied(original)
        if not trusted_applied(original):
            raise HTTPException(status_code=409, detail="applied_unverified")
        try:
            record = build_rollback(original, self._stamp(actor))
        except ProposalRefused as error:
            raise _proposal_refused(error) from error
        reason = (body or RollbackBody()).reason
        return self._store_and_send(gateway, record, (actor, reason))

    def _fresh_applied(self, record: Record) -> Record:
        """The record after an outside-change check against the gateway now (503 if unreadable)."""
        snap = self._snapshot()
        if snap is None:
            raise HTTPException(status_code=503, detail="gateway_state_unreadable")
        return self._refresh(record, snap)


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
