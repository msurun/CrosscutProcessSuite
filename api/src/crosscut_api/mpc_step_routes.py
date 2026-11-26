"""Routes of the multi-MV step-test planner (MPC 7.1a): preview, confirm, advance, abort.

The plan is built by ``crosscut_mpc.step_planner`` from the catalogue variable model and the
pinned gateway policy, and is only offered when every step passes. Confirming stores the plan and
sends steps as normal gateway ``propose`` commands in ``confirm`` mode (see ``mpc_step_exec``);
there is no new write path and nothing is approved here. Permissions: preview, confirm and advance
need ``gw.propose``, reading needs ``gw.view``, abort needs ``gw.reject``. Every confirm, proposal
and abort is appended to the API audit first.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from crosscut_connectors.site import SiteError, load_site
from crosscut_mpc.step_planner import MvSpec, Plan, PlanSettings, build_plan
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import auth_dir
from crosscut_api.gateway_client import FileGatewayClient
from crosscut_api.mpc_step_exec import (
    Runner,
    abort,
    advance,
    all_plans,
    load_plan,
    running_plan,
    save_plan,
)
from crosscut_api.supervisor_live import catalog_sp_tag, read_live_sp

Doc = dict[str, Any]
GatewayProvider = Callable[[], FileGatewayClient | None]
ActorDep = Annotated[ActorContext, Depends(actor_of)]
MAX_MVS = 8
TAG_PATTERN = r"^[A-Za-z0-9_.:-]+$"


class MvRequest(BaseModel):
    """One MV of the test: a controller variable (role MV) and a signed amplitude."""

    model_config = ConfigDict(extra="forbid")
    controller_id: str = Field(min_length=1, max_length=128, pattern=TAG_PATTERN)
    variable_id: str = Field(min_length=1, max_length=128, pattern=TAG_PATTERN)
    amplitude: float = Field(allow_inf_nan=False)


class PlanRequest(BaseModel):
    """Plan type, MVs and timing; ``sample_s`` and ``switch_probability`` apply to ``gbn``."""

    model_config = ConfigDict(extra="forbid")
    plan_type: Literal["sequential", "gbn"]
    mvs: list[MvRequest] = Field(min_length=1, max_length=MAX_MVS)
    duration_s: float = Field(gt=0, allow_inf_nan=False)
    gap_s: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    sample_s: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    switch_probability: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    seed: int = Field(default=0, ge=0, le=2**31)


class ConfirmRequest(PlanRequest):
    """The previewed plan plus its digest: the operator confirms exactly what was shown."""

    digest: str = Field(min_length=64, max_length=64)


def refuse(status: int, detail: Any) -> HTTPException:
    """An HTTP refusal whose detail is a stable code (or a list of refusal rows)."""
    return HTTPException(status_code=status, detail=detail)


def _find_variable(root: Path, mv: MvRequest) -> Doc:
    """The MV variable of a site controller, or 404/422 with a stable code."""
    try:
        controllers = load_site(root).get("controllers", [])
    except SiteError:
        raise refuse(409, "no_site") from None
    for controller in controllers:
        if controller["id"] != mv.controller_id:
            continue
        for var in controller["variables"]:
            if var["id"] == mv.variable_id:
                if var["role"] != "MV":
                    raise refuse(422, f"not_an_mv:{mv.variable_id}")
                return dict(var)
    raise refuse(404, f"unknown_variable:{mv.controller_id}/{mv.variable_id}")


def _policy_targets(client: FileGatewayClient) -> Doc:
    """The setpoint targets of the pinned gateway policy (409 when none is pinned)."""
    try:
        live = client.live_policy()
    except (OSError, KeyError, ValueError, TypeError):
        raise refuse(503, "gateway state unreadable") from None
    document = (live or {}).get("document")
    if not isinstance(document, dict):
        raise refuse(409, "no_policy")
    targets = document.get("targets", document)
    return targets if isinstance(targets, dict) else {}


def _intersect(*ranges: tuple[float, float]) -> tuple[float, float]:
    """The overlap of engineering-unit ranges (low may exceed high: nothing is allowed)."""
    return max(r[0] for r in ranges), min(r[1] for r in ranges)


def _mv_spec(root: Path, targets: Doc, mv: MvRequest, read_sp: Callable[[str], float]) -> MvSpec:
    """MV bounds from the variable model and the policy, baseline from the live setpoint."""
    var = _find_variable(root, mv)
    tag = catalog_sp_tag(root, str((var.get("binding") or {}).get("loop", "")))
    if not tag:
        raise refuse(409, f"no_sp_tag:{mv.variable_id}")
    policy = targets.get(tag)
    if not isinstance(policy, dict) or policy.get("kind", "setpoint") != "setpoint":
        raise refuse(409, f"no_policy:{tag}")
    limits = var.get("limits", {})
    ranges: list[tuple[float, float]] = [tuple(policy["limits"])] + [
        (limits[k]["lo"], limits[k]["hi"]) for k in ("eng", "operator") if k in limits
    ]
    max_step = min(float(policy["max_step"]), float(limits.get("move_max", policy["max_step"])))
    return MvSpec(
        mv.variable_id, tag, read_sp(tag), mv.amplitude, _intersect(*ranges),
        max_step, float(policy.get("min_interval_s", 0.0)),
    )


def plan_digest(plan: Plan) -> str:
    """SHA-256 over (tag, time, value) of every step: what the operator reviewed."""
    rows = [[s.tag, s.at_s, s.value] for s in plan.steps]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def _step_rows(plan: Plan) -> list[Doc]:
    """Plain rows of the planned steps for the preview and the stored record."""
    return [
        {"index": s.index, "mv": s.mv, "tag": s.tag, "at_s": s.at_s, "value": s.value,
         "delta": s.delta}
        for s in plan.steps
    ]


class _Endpoints:
    """Handlers of the step-plan routes, bound to the data root and the gateway provider."""

    def __init__(
        self, root: Path, provider: GatewayProvider, read_sp: Callable[[str], float] | None,
        now_ns: Callable[[], int],
    ) -> None:
        """Bind the data root, the gateway provider, the live-SP reader and the clock."""
        self._root, self._provider, self._now_ns = root, provider, now_ns
        self._read_sp = read_sp or (lambda tag: read_live_sp(root, tag))
        self._lock = threading.Lock()

    def _client(self) -> FileGatewayClient:
        """The active gateway client, or 503."""
        client = self._provider()
        if client is None:
            raise refuse(503, "Write Gateway is offline or stale")
        return client

    def _plan(self, client: FileGatewayClient, body: PlanRequest) -> tuple[Plan, Doc]:
        """Build and validate the plan from live data (refusal rows are part of the result)."""
        targets = _policy_targets(client)
        specs = [_mv_spec(self._root, targets, mv, self._read_sp) for mv in body.mvs]
        settings = PlanSettings(
            body.plan_type, body.duration_s, body.gap_s, body.sample_s,
            body.switch_probability, body.seed,
        )
        return build_plan(specs, settings), {s.tag: s.baseline for s in specs}

    def preview(self, body: PlanRequest, actor: ActorDep) -> Doc:
        """POST /mpc/step-plans/preview: the validated schedule; sends nothing."""
        actor.require("gw.propose")
        client = self._client()
        plan, baselines = self._plan(client, body)
        return {
            "ok": plan.ok, "digest": plan_digest(plan) if plan.ok else None,
            "steps": _step_rows(plan), "baselines": baselines,
            "refusals": [vars(r) for r in plan.refusals],
            "gateway_mode": client.mode(),
            "total_s": max((s.at_s for s in plan.steps), default=0.0),
        }

    def confirm(self, body: ConfirmRequest, actor: ActorDep) -> Doc:
        """POST /mpc/step-plans: the operator confirms the previewed plan; step 1 is proposed."""
        actor.require("gw.propose")
        client = self._client()
        with self._lock:
            if client.mode() != "confirm":
                raise refuse(409, "gateway_not_confirm")
            if running_plan(self._root) is not None:
                raise refuse(409, "plan_running")
            plan, baselines = self._plan(client, body)
            if not plan.ok:
                raise refuse(409, [vars(r) for r in plan.refusals] or "empty_plan")
            if plan_digest(plan) != body.digest:
                raise refuse(409, "plan_changed")
            record = self._record(plan, baselines, body, actor)
            self._audit("mpc_step_plan_confirmed", actor, plan=record["id"], digest=body.digest)
            return self._run(record, actor, client)

    def _record(self, plan: Plan, baselines: Doc, body: PlanRequest, actor: ActorContext) -> Doc:
        """The stored plan record: schedule, baselines and per-step status (all 'planned')."""
        steps = [{**row, "status": "planned"} for row in _step_rows(plan)]
        return {
            "id": uuid.uuid4().hex[:12], "status": "running", "actor": actor.actor,
            "request": body.model_dump(exclude={"digest"}), "baselines": baselines,
            "steps": steps, "anchor_ns": self._now_ns(), "abort_reason": None, "displaced": [],
        }

    def _run(self, record: Doc, actor: ActorContext, client: FileGatewayClient) -> Doc:
        """Advance a record once and save it, whatever the outcome."""
        runner = Runner(client, actor, self._read_sp, self._now_ns,
                        lambda event, **f: self._audit(event, actor, **f))
        try:
            advance(record, runner)
        finally:
            save_plan(self._root, record)
        return record

    def list(self, actor: ActorDep) -> Doc:
        """GET /mpc/step-plans: stored plans, newest first."""
        actor.require("gw.view")
        return {"plans": list(reversed(all_plans(self._root)))}

    def get(self, plan_id: str, actor: ActorDep) -> Doc:
        """GET /mpc/step-plans/{plan_id}: one plan with per-step progress (read only)."""
        actor.require("gw.view")
        return self._load(plan_id)

    def advance(self, plan_id: str, actor: ActorDep) -> Doc:
        """POST /mpc/step-plans/{plan_id}/advance: resolve queued steps, send due ones."""
        actor.require("gw.propose")
        client = self._client()
        with self._lock:
            return self._run(self._load(plan_id), actor, client)

    def abort(self, plan_id: str, actor: ActorDep) -> Doc:
        """POST /mpc/step-plans/{plan_id}/abort: stop the plan; queued steps are rejected."""
        actor.require("gw.reject")
        client = self._client()
        with self._lock:
            record = self._load(plan_id)
            runner = Runner(client, actor, self._read_sp, self._now_ns,
                            lambda event, **f: self._audit(event, actor, **f))
            try:
                abort(record, runner, "operator_abort")
            finally:
                save_plan(self._root, record)
            return record

    def _load(self, plan_id: str) -> Doc:
        """A stored plan or 404."""
        record = load_plan(self._root, plan_id) if plan_id.isalnum() else None
        if record is None:
            raise refuse(404, "unknown_plan")
        return record

    def _audit(self, event: str, actor: ActorContext, **fields: str) -> None:
        """Append to the API audit; no audit line, no action (503)."""
        audit = AuthAudit(auth_dir(self._root) / AUDIT_FILE)
        try:
            audit.append(event, actor=actor.actor, source_ip=actor.source_ip, **fields)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=503, detail="audit_unavailable") from error


def build_step_plan_router(
    root: Path,
    provider: GatewayProvider,
    read_sp: Callable[[str], float] | None = None,
    now_ns: Callable[[], int] = time.time_ns,
) -> APIRouter:
    """Routes under ``/mpc/step-plans``; ``read_sp`` and ``now_ns`` are injectable for tests."""
    endpoints = _Endpoints(root, provider, read_sp, now_ns)
    router = APIRouter()
    base = "/mpc/step-plans"
    router.add_api_route(f"{base}/preview", endpoints.preview, methods=["POST"])
    router.add_api_route(base, endpoints.confirm, methods=["POST"])
    router.add_api_route(base, endpoints.list, methods=["GET"])
    router.add_api_route(f"{base}/{{plan_id}}", endpoints.get, methods=["GET"])
    router.add_api_route(f"{base}/{{plan_id}}/advance", endpoints.advance, methods=["POST"])
    router.add_api_route(f"{base}/{{plan_id}}/abort", endpoints.abort, methods=["POST"])
    return router
