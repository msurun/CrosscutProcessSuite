"""Supervisor advice as a setpoint write proposal to the Write Gateway (ADR 014 section 7).

Rules (each refusal is an HTTP error with a stable code, nothing is sent unless all pass):
* the caller holds ``gw.propose``; the supervisor mode is ``confirm`` or ``supervised``;
* ``confirm``: the gateway must be in ``confirm`` (the proposal queues for a human);
* ``supervised``: the caller also holds ``gw.mode.up.supervised`` and the gateway is supervised;
* the advice is fresh (``max_advice_age_s``), has a timestamp and belongs to the target loop;
* the new setpoint is the LIVE setpoint plus the advised delta, |delta| <= ``max_step``;
* each advice id is sent at most once (``<root>/_supervisor/proposed.json``).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from crosscut_supervisor.audit import AuditLog
from crosscut_supervisor.config import SupervisorConfig
from crosscut_supervisor.proposal import (
    ProposalContext,
    ProposalRefusal,
    SetpointProposal,
    build_from_delta,
)
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from crosscut_api.auth.actor import ActorContext
from crosscut_api.gateway_client import FileGatewayClient
from crosscut_api.gateway_routes import _gateway_errors as gateway_errors

PROPOSED_FILE = "proposed.json"
SUPERVISED_PERMISSION = "gw.mode.up.supervised"
NS_PER_S = 1_000_000_000
FUTURE_TOLERANCE_NS = 5 * NS_PER_S
MANUAL_REASON_MAX = 200
MANUAL_PREFIX = "operator-supplied:"
OUTCOME_UNKNOWN = "outcome_unknown_check_audit"


class SupervisorProposeRequest(BaseModel):
    """Propose logged advice (``advice_id``, or the latest) or one bounded manual move."""

    model_config = ConfigDict(extra="forbid")

    advice_id: str | None = None
    direction: Literal["increase", "decrease"] | None = None
    magnitude: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    reason: str | None = Field(default=None, max_length=MANUAL_REASON_MAX)

    @model_validator(mode="after")
    def _manual_is_complete(self) -> SupervisorProposeRequest:
        """A manual move needs direction and magnitude together and excludes an advice id."""
        if (self.direction is None) != (self.magnitude is None):
            raise ValueError("direction and magnitude go together")
        if self.advice_id and self.direction is not None:
            raise ValueError("advice_id excludes direction and magnitude")
        return self


def refuse(status: int, code: str) -> HTTPException:
    """An HTTP refusal whose detail is the stable code."""
    return HTTPException(status_code=status, detail=code)


def require_actor(actor: ActorContext | None) -> ActorContext:
    """The actor holding ``gw.propose`` (403 otherwise; analysis.run alone is not enough)."""
    if actor is None:
        raise refuse(403, "forbidden")
    actor.require("gw.propose")
    return actor


def check_modes(supervisor_mode: str, gateway_mode: str | None, actor: ActorContext) -> None:
    """Enforce the supervisor mode x gateway mode x role rule (see the module docstring)."""
    if supervisor_mode == "off":
        raise refuse(409, "supervisor mode is off")
    if supervisor_mode == "advisory":
        raise refuse(409, "mode_advisory_only")
    if supervisor_mode == "supervised":
        actor.require(SUPERVISED_PERMISSION)
    if gateway_mode != supervisor_mode:
        raise refuse(409, "gateway_mode_mismatch")


def gateway_mode_of(client: FileGatewayClient) -> str | None:
    """The gateway's mode from its state file; 503 when the state cannot be read."""
    try:
        mode = client.mode()
    except (OSError, KeyError, ValueError, TypeError):
        raise refuse(503, "gateway state unreadable") from None
    return mode if isinstance(mode, str) else None


def check_fresh(record: dict[str, Any], config: SupervisorConfig, now_ns: int) -> None:
    """Refuse (409 ``advice_stale``) a missing or invalid timestamp, a stale or future advice."""
    stamp = record.get("t_ns")
    if isinstance(stamp, bool) or not isinstance(stamp, int):
        raise refuse(409, "advice_stale")
    age_ns = now_ns - stamp
    if age_ns > config.max_advice_age_s * NS_PER_S or age_ns < -FUTURE_TOLERANCE_NS:
        raise refuse(409, "advice_stale")


def _positive_number(value: object) -> bool:
    """True for a real number above zero (a bool is not one)."""
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0


def delta_of(record: dict[str, Any]) -> tuple[float, str]:
    """Signed delta and reason sentence of an advice record (422 for hold or no magnitude)."""
    direction, magnitude = record.get("direction", "hold"), record.get("magnitude")
    if direction not in ("increase", "decrease") or not _positive_number(magnitude):
        raise refuse(422, "advice is hold or has no magnitude")
    explanation = record.get("explanation") or []
    sentence = str(explanation[0].get("sentence", "")) if explanation else "supervisor advice"
    size = float(cast(float, magnitude))
    return (size if direction == "increase" else -size), sentence


def write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    """Write a JSON file so a reader never sees half of it (temporary file, then replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class ProposedStore:
    """Advice ids already sent to the gateway, with the outcome, in ``proposed.json``."""

    def __init__(self, root: Path) -> None:
        self._path = root / "_supervisor" / PROPOSED_FILE
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return document if isinstance(document, dict) else {}

    def get(self, advice_id: str) -> dict[str, Any] | None:
        """The stored entry of an advice id, or None."""
        with self._lock:
            entry = self._load().get(advice_id)
        return entry if isinstance(entry, dict) else None

    def reserve(self, advice_id: str, entry: dict[str, Any]) -> dict[str, Any] | None:
        """Store ``entry`` unless the id exists; return the existing entry in that case."""
        with self._lock:
            document = self._load()
            if advice_id in document:
                return dict(document[advice_id])
            write_json_atomic(self._path, {**document, advice_id: entry})
        return None

    def put(self, advice_id: str, entry: dict[str, Any] | None) -> None:
        """Replace the entry of an id, or remove it with None."""
        with self._lock:
            document = self._load()
            document.pop(advice_id, None)
            if entry is not None:
                document[advice_id] = entry
            write_json_atomic(self._path, document)


def already_proposed(previous: dict[str, Any]) -> HTTPException:
    """409 ``already_proposed`` carrying the stored result of the earlier send."""
    return HTTPException(status_code=409, detail={"code": "already_proposed", "previous": previous})


class _OutcomeUnknownError(Exception):
    """The gateway did not answer in time: the proposal may or may not have been applied."""


def _propose_mapped(
    client: FileGatewayClient, args: dict[str, Any], actor: ActorContext
) -> dict[str, Any]:
    """Call the gateway; a timeout becomes _OutcomeUnknownError, other errors real HTTP codes."""
    try:
        with gateway_errors(value_error_status=422):
            return client.propose(args, actor)
    except HTTPException as error:
        if error.status_code == 504:
            raise _OutcomeUnknownError from None
        raise


def send_once(
    client: FileGatewayClient,
    store: ProposedStore,
    proposal: SetpointProposal,
    actor: ActorContext,
) -> dict[str, Any]:
    """Send the proposal once per advice id; map gateway failures to real HTTP codes.

    A timeout keeps the id burnt (a supervised proposal may have been applied): 504
    ``outcome_unknown_check_audit``. Any other failure releases the id (nothing was applied).
    """
    args = proposal.to_gateway_args()
    entry: dict[str, Any] = {"status": "sending", "proposal": args}
    previous = store.reserve(proposal.advice_id, entry)
    if previous is not None:
        raise already_proposed(previous)
    try:
        decision = _propose_mapped(client, args, actor)
    except _OutcomeUnknownError:
        store.put(proposal.advice_id, {**entry, "status": OUTCOME_UNKNOWN})
        raise HTTPException(status_code=504, detail=OUTCOME_UNKNOWN) from None
    except BaseException:
        store.put(proposal.advice_id, None)
        raise
    store.put(proposal.advice_id, {**entry, "status": "sent", "decision": decision})
    return decision


def manual_delta(body: SupervisorProposeRequest, max_step: float) -> tuple[float, str, str]:
    """(delta, sentence, advice id) of a manual move bounded by ``max_step``."""
    magnitude = float(body.magnitude or 0.0)
    if magnitude > max_step:
        raise refuse(409, "delta_too_large")
    text = body.reason or f"manual {body.direction} {magnitude}"
    delta = magnitude if body.direction == "increase" else -magnitude
    return delta, f"{MANUAL_PREFIX} {text}", f"manual-{time.time_ns()}"


def build_or_409(
    advice_id: str, delta: float, sentence: str, ctx: ProposalContext
) -> SetpointProposal:
    """The proposal, or HTTP 409 with the refusal code."""
    try:
        return build_from_delta(advice_id, delta, sentence, ctx)
    except ProposalRefusal as refusal:
        raise refuse(409, refusal.code) from None


def advice_record(log: AuditLog, advice_id: str | None) -> dict[str, Any]:
    """The named advice record, or the latest one in the log (404/422 when there is none)."""
    if advice_id:
        record = log.find_advice(advice_id)
        if record is None:
            raise refuse(404, f"unknown advice: {advice_id}")
        return record
    records = [r for r in log.records() if r.get("kind") == "advice"]
    if not records:
        raise refuse(422, "no advice records in audit log")
    return records[-1]
