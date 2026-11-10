"""Fakes and builders for the tuning proposal route tests (ADR 014 step 6).

A site with one loop and one source, a running loop_kpi job, a fake connector that returns the
current parameter values, a fake gateway that behaves like the real one where it matters (queue,
key, self-approval refusal, one apply per key, audit records) and a mini app with the real
app-level enforcer. Imported by sibling test modules as ``from tuning_fakes import ...``.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, FakeClock, csrf, login, seed_users
from crosscut_api import tuning_proposal_routes as routes
from crosscut_api.auth.actor import ActorContext
from crosscut_api.auth.deps import AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.tuning_build import Sources
from crosscut_api.tuning_proposal_routes import TuningDeps, build_tuning_proposal_router
from crosscut_connectors.base import LiveValue, SourceConnectionError
from crosscut_connectors.site import save_site
from crosscut_loops.tuning_proposal import WindowSpec
from crosscut_loops.tuning_report import TuningReport, report_from_model
from crosscut_loops.tuning_rules import FopdtModel
from crosscut_runtime.store import RuntimeStore
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

LOOP = "FIC-101"
KP = "FIC101.KP"
TI = "FIC101.TI"
START_VALUES = {KP: 0.5, TI: 200.0}  # a detuned loop; SIMC gives gain 1.25 and ti 100 s
MODEL = FopdtModel(gain=2.0, time_constant_s=100.0, delay_s=10.0)
USERS = {**DEFAULT_USERS, "eng2": ["engineer"], "lead1": ["lead"]}
BODY: dict[str, Any] = {
    "dataset_id": "ds1",
    "vendor_form": "siemens_pid_compact",
    "method": "simc",
    "reason": "loop oscillates after the feed change",
}


def site_document() -> dict[str, Any]:
    """A site with source ``dcs``, the loop FIC-101 and the PV tag with its range."""
    names = ("FIC101.PV", "FIC101.SP", "FIC101.OUT", "FIC101.MODE", KP, TI)
    tags = [{"id": t} for t in names]
    tags[0]["eng_limits"] = {"min": 0.0, "max": 200.0}
    loop = {"id": LOOP, "pv": "FIC101.PV", "sp": "FIC101.SP", "out": "FIC101.OUT",
            "mode": "FIC101.MODE", "vendor": "siemens_pid_compact"}  # fmt: skip
    source = {"id": "dcs", "driver": "opcua", "endpoint": "opc.tcp://127.0.0.1:4840"}
    return {"schema_version": 1, "site": {"name": "t"}, "tags": tags, "loops": [loop],
            "sources": [source]}  # fmt: skip


def write_runtime(
    root: Path, *, jobs: bool = True, running: bool = True, status: str = "ok"
) -> None:
    """Write jobs.json (a loop_kpi job of the loop) and a state.json of a running service."""
    job = {"id": "kpi", "kind": "loop_kpi", "source": "dcs", "loops": [LOOP],
           "period_s": 5, "window_s": 300, "enabled": True}  # fmt: skip
    store = RuntimeStore(root)
    store.save_jobs({"schema_version": 1, "jobs": [job] if jobs else []})
    stamp = datetime.now(UTC).isoformat()
    state = {"service": "running" if running else "stopped", "updated_at_utc": stamp,
             "jobs": {"kpi": {"status": status}}}  # fmt: skip
    store.save_state(state)


def policy_document() -> dict[str, Any]:
    """The live policy view: gain and ti parameter targets of the loop."""
    base = {"kind": "pid_param", "loop": LOOP, "vendor_form": "siemens_pid_compact"}
    return {"targets": {KP: {**base, "param": "gain", "unit": "OUT/PV"},
                        TI: {**base, "param": "ti", "unit": "s"}}}  # fmt: skip


class FakeConnector:
    """Read-only connector that returns the plant values of the fake gateway."""

    def __init__(self, values: dict[str, float], quality: int = 0, fail: bool = False) -> None:
        """Serve ``values`` with the given quality code, or fail like a lost connection."""
        self.values, self.quality, self.fail = values, quality, fail

    def read_live(self, tags: list[str]) -> dict[str, LiveValue]:
        """Return a LiveValue per known tag."""
        if self.fail:
            raise SourceConnectionError("no connection")
        stamp = datetime.now(UTC).isoformat()
        return {t: LiveValue(self.values[t], self.quality, stamp) for t in tags if t in self.values}


class FakeGateway:
    """In-memory gateway: queue with keys, self-approval refusal, one apply per key, audit."""

    def __init__(self) -> None:
        """Start with the detuned plant values and nothing queued."""
        self.values = dict(START_VALUES)
        self.pending: dict[str, dict[str, Any]] = {}
        self.audit_log: list[dict[str, str]] = []
        self.lock = threading.Lock()
        self.apply_count = 0
        self.apply_delay_s = 0.0
        self.refuse_propose: str | None = None
        self.refuse_approve: str | None = None
        self.sent: list[dict[str, Any]] = []
        self.chain_ok = True
        self.state_down = False  # state.json unreadable: snapshot() raises
        self.hide_applied = False  # state.json lags behind the audit: no applied_params yet
        self.timeout_after_apply = False  # the set is applied, but the reply never arrives
        self.unaudited = False  # the set is applied, the audit sink failed
        self.open_intents: list[dict[str, Any]] = []
        self.store_damaged = False
        self.resolve_refusal: str | None = None

    def live_policy(self) -> dict[str, Any] | None:
        """The pinned live policy with the two parameter targets."""
        return {"document": policy_document(), "pin": {}}

    def pending_params(self) -> list[dict[str, Any]]:
        """Summaries of the queued sets, like state.json pending_params."""
        return [{"key": k, "kind": "pid_param", "proposal_id": e["args"]["proposal_id"],
                 "loop_id": e["args"]["loop_id"], "proposer": e["proposer"],
                 "items": e["args"]["items"]} for k, e in self.pending.items()]  # fmt: skip

    def audit(self, limit: int) -> dict[str, Any]:
        """The newest audit records."""
        return {"records": list(self.audit_log)[-limit:], "chain_ok": self.chain_ok}

    def snapshot(self) -> dict[str, Any]:
        """One consistent read like state.json: pending sets, applied map, param events."""
        if self.state_down:
            raise OSError("state.json unreadable")
        applied: dict[str, Any] = {}
        for row in ([] if self.hide_applied else self.audit_log):
            if row["event"] != "param_write":
                continue
            entry = applied.setdefault(row["proposal_id"], {
                "key": row["key"], "applied_from": {}, "applied_to": {}, "t_ns": 0,
                "approver": row["actor"], "status": "applied"})  # fmt: skip
            entry["applied_from"][row["tag"]] = float(row["applied_from"])
            entry["applied_to"][row["tag"]] = float(row["applied_to"])
            entry["t_ns"] = max(entry["t_ns"], int(row["t_ns"]))
        events = [
            {**r, "target": r["tag"]} for r in self.audit_log if r["event"].startswith("param_")
        ]
        return {"pending_params": self.pending_params(), "applied_params": applied,
                "param_events": events[-200:], "chain_ok": self.chain_ok}  # fmt: skip

    def propose_params(
        self, args: dict[str, Any], actor: ActorContext | None = None
    ) -> dict[str, Any]:
        """Queue a set (key = hash of the arguments) unless refused."""
        assert actor is not None
        self.sent.append(args)
        if actor.actor.startswith("svc:"):
            raise PermissionError("service_cannot_propose_tuning")
        if self.refuse_propose is not None:
            return {"accepted": False, "reason_code": self.refuse_propose}
        key = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()
        self.pending[key] = {"args": args, "proposer": actor.actor}
        return {"accepted": True, "reason_code": "queued", "clamped_value": None}

    def approve(self, key: str, actor: ActorContext | None = None) -> dict[str, Any]:
        """Check permission and self-approval, then apply the set once."""
        assert actor is not None
        with self.lock:
            entry = self.pending.get(key)
            if entry is None:
                raise KeyError(f"unknown pending proposal key: {key}")
            if not actor.can("gw.approve.tuning"):
                raise PermissionError("missing_permission:gw.approve.tuning")
            if entry["proposer"] == actor.actor:
                return {"accepted": False, "reason_code": "self_approval"}
            time.sleep(self.apply_delay_s)
            del self.pending[key]
            result = self._apply(key, entry["args"], actor.actor)
        if self.timeout_after_apply and result["accepted"]:
            raise TimeoutError("gateway did not answer")
        return result

    def _apply(self, key: str, args: dict[str, Any], approver: str) -> dict[str, Any]:
        """Write the items when the plant still holds every ``from`` value (else from_mismatch)."""
        items = args["items"]
        if self.refuse_approve or any(self.values[i["target"]] != i["from"] for i in items):
            return {"accepted": False, "reason_code": self.refuse_approve or "from_mismatch"}
        for item in items:
            if not self.unaudited:
                self.audit_log.append(self._write_record(key, item, args["proposal_id"], approver))
            self.values[item["target"]] = item["to"]
        self.apply_count += 1
        reason = "applied_unaudited" if self.unaudited else "applied"
        return {"accepted": True, "reason_code": reason, "clamped_value": None}

    def _write_record(
        self, key: str, item: dict[str, Any], proposal_id: str, approver: str
    ) -> dict[str, str]:
        """An audit record of event param_write, as the real gateway writes it."""
        return {
            "seq": str(len(self.audit_log)),
            "t_ns": str(time.time_ns()),
            "event": "param_write",
            "tag": item["target"],
            "key": key,
            "proposal_id": proposal_id,
            "actor": approver,
            "applied_from": str(item["from"]),
            "applied_to": str(item["to"]),
        }

    def reject(self, key: str, actor: ActorContext | None = None) -> None:
        """Drop a queued set."""
        if self.pending.pop(key, None) is None:
            raise KeyError(f"unknown pending proposal key: {key}")

    def external_change(self, tag: str, value: float) -> None:
        """Someone changes ``tag`` at the DCS: the plant moves and the audit says so."""
        self.values[tag] = value
        self.audit_log.append({"seq": str(len(self.audit_log)), "t_ns": str(time.time_ns()),
                               "event": "param_changed_externally", "tag": tag})  # fmt: skip

    def list_open_intents(
        self, actor: ActorContext | None = None
    ) -> dict[str, Any]:
        """List open write intents or damaged status."""
        if self.store_damaged:
            return {"store_state": "damaged", "intents": []}
        return {"store_state": "ok", "intents": list(self.open_intents)}

    def resolve_intent(
        self, key: str, actor: ActorContext | None = None
    ) -> dict[str, Any]:
        """Resolve an open write intent; check permission and return decision."""
        if actor is not None and not actor.can("gw.approve.tuning"):
            raise PermissionError("missing_permission:gw.approve.tuning")
        if self.store_damaged:
            return {"accepted": False, "reason_code": "intent_store_unreadable"}
        if self.resolve_refusal is not None:
            return {"accepted": False, "reason_code": self.resolve_refusal}
        matching = [i for i in self.open_intents if i.get("key") == key]
        if not matching:
            return {"accepted": False, "reason_code": "intent_not_open"}
        self.open_intents = [i for i in self.open_intents if i.get("key") != key]
        self.audit_log.append({
            "event": "intent_resolved",
            "key": key,
            "actor": actor.actor if actor else "tester",
            "t_ns": str(time.time_ns()),
        })
        return {"accepted": True, "reason_code": "resolved"}


class Provider:
    """Hands out the gateway while it is marked up."""

    def __init__(self, gateway: Any) -> None:
        """Bind to a gateway; it starts up."""
        self.gateway, self.up = gateway, True

    def __call__(self) -> Any:
        """The gateway, or None while down."""
        return self.gateway if self.up else None


@dataclass
class World:
    """The mini app with its collaborators."""

    app: FastAPI
    gateway: Any
    provider: Provider
    deps: TuningDeps
    connector: FakeConnector
    root: Path


def no_dataset(_dataset_id: str) -> Any:
    """Dataset loader of tests that patch the report (never called)."""
    raise AssertionError("dataset loader must not be called")


def build_world(
    root: Path,
    gateway: Any,
    *,
    auth: bool = True,
    clock: Callable[[], float] = time.time,
    connector: Any = None,
    wait_s: float = 0.3,
) -> World:
    """Site, runtime files and a mini app with the tuning router (and the real enforcer)."""
    save_site(root, site_document())
    write_runtime(root)
    live_values = getattr(gateway, "values", dict(START_VALUES))
    connector = connector or FakeConnector(live_values)  # the live plant
    provider = Provider(gateway)
    deps = TuningDeps(Sources(root, no_dataset, no_dataset), provider,
                      lambda _source: connector, clock, wait_s=wait_s)  # fmt: skip
    if auth:
        seed_users(root, USERS)
        ctx = build_auth_context(root, TEST_CONFIG, FakeClock())
        app = FastAPI(dependencies=[Depends(make_enforcer(AuthGuards(ctx), ctx))])
        app.include_router(build_auth_router_for(ctx))
    else:
        app = FastAPI()
    app.include_router(build_tuning_proposal_router(deps))
    return World(app, gateway, provider, deps, connector, root)


def patch_report(monkeypatch: pytest.MonkeyPatch, blocked: str | None = None) -> None:
    """Replace the report builder by a fixed model report (no data windows needed)."""

    def fake(*_args: Any) -> tuple[TuningReport, WindowSpec]:
        report = report_from_model(LOOP, MODEL)
        report.blocked_reason = blocked
        now = datetime.now(UTC)
        return report, WindowSpec(now - timedelta(hours=2), now - timedelta(hours=1), "ds1")

    monkeypatch.setattr(routes, "build_report", fake)


class Session:
    """A logged-in client of one user."""

    def __init__(self, world: World, username: str) -> None:
        """Log ``username`` in on a fresh client."""
        self.client = TestClient(world.app)
        self.payload = login(self.client, username)

    def call(self, method: str, path: str, body: Any = None) -> Any:
        """Send a request with the session's CSRF header."""
        return self.client.request(method, path, json=body, headers=csrf(self.payload))
