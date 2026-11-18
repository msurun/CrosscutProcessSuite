"""Bounded manual-output tests owned by the Write Gateway (ADR 017).

Keep the restoration intent open for the entire test, including failed restores.
The engine tick supplies time; this module never changes a controller's mode.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from crosscut_gateway.actor import normalize_actor
from crosscut_gateway.engine_params import ParamEnv
from crosscut_gateway.interfaces import WriteDecision
from crosscut_gateway.param_intent_store import (
    ParamIntentItem,
    ParamIntentRecord,
    ParamIntentStore,
)

NANOSECONDS_PER_SECOND = 1_000_000_000  # ns per second
COMM_ERRORS = (ConnectionError, OSError, TimeoutError)
LOGGER = logging.getLogger(__name__)


class LoopNotManError(Exception):
    """The DCS loop was not in MAN immediately before an OUT write; nothing was written."""


class OutputPlant(Protocol):
    """Plant operations for output tests; there is deliberately no mode setter."""

    def read_out(self, tag: str) -> float:
        """Read live controller output in engineering units."""

    def write_out(self, tag: str, value: float) -> bool:
        """Write controller output; return whether the DCS accepted it."""

    def read_pv(self, tag: str) -> float:
        """Read live, good-quality process value in engineering units."""

    def loop_mode(self, tag: str) -> str:
        """Read the current DCS mode; only MAN permits a test."""


@dataclass(frozen=True)
class OutputPolicy:
    """Site bounds: output/PV engineering units and maximum duration in seconds."""

    loop: str
    limits: tuple[float, float]
    pv_limits: tuple[float, float]
    max_amplitude: float
    max_duration_s: float
    readback_tolerance: float


@dataclass(frozen=True)
class OutputRequest:
    """One explicit human confirmation of a signed output step, not an absolute OUT."""

    test_id: str
    target: str
    amplitude: float
    duration_s: float


@dataclass(frozen=True)
class ActiveTest:
    """Restoration baseline and deadline retained until a verified return."""

    request: OutputRequest
    baseline: float
    deadline_ns: int


def finite_number(value: object) -> bool:
    """Reject booleans, nonnumbers, NaN, infinity and overflowing integers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


class OutputSteps:
    """Run bounded tests and retry interrupted restores without clearing their intent."""

    def __init__(self, env: ParamEnv, plant: OutputPlant, store: ParamIntentStore) -> None:
        """Read restart intents before accepting any output test."""
        self.env, self.plant, self.store = env, plant, store
        self.policies: dict[str, OutputPolicy] = {}
        self.active: dict[str, ActiveTest] = {}
        self.restore_reasons: dict[str, str] = {}
        self.seen: set[str] = {record.key for record in store.load_all()}
        self.states = {item.target: "reconcile_required"
                       for record in store.load_open() for item in record.items}
        for record in store.load_open():
            self._audit("intent_open_at_start", record.items[0].target, record.key)

    def configure(self, policies: dict[str, OutputPolicy]) -> None:
        """Replace site bounds only when no test or unresolved intent exists."""
        self.check_reload()
        open_targets = {item.target for record in self.store.load_open() for item in record.items}
        if (open_targets & set(self.policies)) - set(policies):
            raise ValueError("OUT policy reload blocked: target with open intent removed")
        self.policies = dict(policies)
        unresolved = {tag: state for tag, state in self.states.items()
                      if state == "reconcile_required"}
        self.states = {**unresolved, **{tag: self.states.get(tag, "enabled") for tag in policies}}

    def check_reload(self) -> None:
        """Refuse policy mutation while a baseline may still need restoration."""
        if self.active or (self.policies and self.store.load_open()):
            raise ValueError("OUT policy reload blocked: reconcile_required")

    def _audit(self, event: str, target: str, reason: str) -> None:
        """Write a gateway audit event; a failed audit propagates fail closed."""
        self.env.emit(f"out_{event}", {"tag": target, "reason_code": reason})

    def _refuse(self, request: OutputRequest, reason: str) -> WriteDecision:
        """Audit an explicit refusal without changing the plant."""
        self.env.emit("out_refused", {
            "tag": request.target, "reason_code": reason, "key": request.test_id,
            "amplitude": str(request.amplitude), "duration_s": str(request.duration_s),
        })
        return WriteDecision(accepted=False, reason_code=reason)

    def _request_reason(self, request: OutputRequest) -> str:
        """Check human confirmation and durable exclusions before any plant read."""
        if self.env.mode() != "confirm":
            return "out_requires_confirm_mode"
        if self.env.killed():
            return "killed"
        if not self.env.clock_started():
            return "clock_not_started"
        actor = self.env.actor()
        if not actor or normalize_actor(actor).startswith("svc:"):
            return "out_requires_human_confirmation"
        if request.target not in self.policies:
            return "no_policy"
        if self.store.has_open_for_loop(self.policies[request.target].loop):
            return "reconcile_required"
        if request.test_id in self.seen:
            return "duplicate_test"
        return self._bounds_reason(request)

    def _bounds_reason(self, request: OutputRequest) -> str:
        """Refuse rather than clamp amplitude and duration in site engineering units."""
        policy = self.policies[request.target]
        if not finite_number(request.amplitude) or not finite_number(request.duration_s):
            return "bad_value"
        if not 0 < abs(request.amplitude) <= policy.max_amplitude:
            return "amplitude_out_of_bounds"
        if not 0 < request.duration_s <= policy.max_duration_s:
            return "duration_out_of_bounds"
        return ""

    def start(self, request: OutputRequest) -> WriteDecision:
        """Confirm and apply one step; any uncertain write immediately triggers return."""
        reason = self._request_reason(request)
        if reason:
            return self._refuse(request, reason)
        try:
            return self._start_live(request)
        except LoopNotManError:
            self.abort(request.target, "loop_not_man")
            return self._refuse(request, "loop_not_man")
        except COMM_ERRORS:
            if request.target in self.active:
                self.abort(request.target, "comm_loss")
            return self._refuse(request, "comm_loss")

    def _start_live(self, request: OutputRequest) -> WriteDecision:
        """Validate the live baseline, persist intent, then perform and verify the step."""
        target = request.target
        reason = self._live_reason(target)
        baseline = self.plant.read_out(target)
        policy = self.policies[target]
        if reason or not self._output_in_bounds(policy, baseline, request.amplitude):
            return self._refuse(request, reason or "out_of_limits")
        self._persist(request, baseline)
        # Add the signed amplitude to the live OUT; both use the site's output unit.
        if self._live_reason(target):
            self.abort(target, "mode_or_pv_changed")
            return self._refuse(request, "mode_or_pv_changed")
        self._write_verified(target, baseline + request.amplitude)
        self._audit("started", target, request.test_id)
        return WriteDecision(accepted=True, reason_code="out_step_started")

    def _output_in_bounds(self, policy: OutputPolicy, baseline: float, amplitude: float) -> bool:
        """Require both pre-test OUT and stepped OUT to lie within site limits."""
        low, high = policy.limits
        return finite_number(baseline) and low <= baseline <= high and (
            low <= baseline + amplitude <= high
        )

    def _persist(self, request: OutputRequest, baseline: float) -> None:
        """Durably save the pre-test value before the first possible plant mutation."""
        deadline = self.env.now_ns() + int(request.duration_s * NANOSECONDS_PER_SECOND)
        item = ParamIntentItem(request.target, baseline, baseline + request.amplitude)
        record = ParamIntentRecord(
            request.test_id, self.policies[request.target].loop, (item,),
            datetime.now(UTC).isoformat(), proposer=self.env.actor() or "",
        )
        self.store.record_intent(record)
        self.active[request.target] = ActiveTest(request, baseline, deadline)
        self.seen.add(request.test_id)
        self.states[request.target] = "running"
        self.env.emit("out_intent", {
            "tag": request.target, "key": request.test_id, "baseline": str(baseline),
            "intended": str(item.to_value), "duration_s": str(request.duration_s),
        })

    def _live_reason(self, target: str) -> str:
        """Check live DCS mode; PV at or beyond either boundary trips, on every cycle."""
        if self.plant.loop_mode(target) != "MAN":
            return "loop_not_man"
        process_value = self.plant.read_pv(target)
        low, high = self.policies[target].pv_limits
        if not finite_number(process_value) or not low < process_value < high:
            return "pv_limit"
        return ""

    def _write_verified(self, target: str, value: float) -> None:
        """Write only while the loop is MAN (re-read right now) and verify by read-back."""
        if self.plant.loop_mode(target) != "MAN":
            raise LoopNotManError(target)
        if not self.plant.write_out(target, value):
            raise ConnectionError("OUT write refused; check DCS")
        actual = self.plant.read_out(target)
        tolerance = self.policies[target].readback_tolerance
        if not finite_number(actual) or abs(actual - value) > tolerance:
            raise ConnectionError("OUT read-back mismatch; check DCS")
        self.env.emit("out_write_verified", {
            "tag": target, "value": str(value), "read": str(actual),
            "key": self.active[target].request.test_id,
        })

    def tick(self) -> None:
        """Abort on trips or deadlines and retry failed returns on later cycles."""
        for target in tuple(self.active):
            try:
                reason = self._tick_reason(target)
            except COMM_ERRORS:
                reason = "comm_loss"
            if reason:
                self.abort(target, reason)

    def _tick_reason(self, target: str) -> str:
        """Give an existing return request priority over new trip observations."""
        if target in self.restore_reasons:
            return self.restore_reasons[target]
        if self.env.killed():
            return "killed"
        if self.env.mode() != "confirm":
            return "gateway_mode_changed"
        reason = self._live_reason(target)
        if reason:
            return reason
        if self.env.now_ns() >= self.active[target].deadline_ns:
            return "timeout"
        return ""

    def abort(self, target: str, reason: str) -> None:
        """Return pre-test OUT; retain and retry an unverified restoration."""
        self._recover_test(target)
        test = self.active[target]
        self.restore_reasons[target] = reason
        self.states[target] = "reconcile_required"
        # Even a full audit disk must not prevent the physical return attempt.
        try:
            self._audit("abort", target, reason)
        finally:
            self._restore(target, test)

    def _restore(self, target: str, test: ActiveTest) -> None:
        """Return OUT only if the DCS value is still ours; the DCS value otherwise wins."""
        try:
            hold = self._restore_hold(target, test)
            if hold:
                self._audit("restore_held", target, hold)
                return
        except COMM_ERRORS:
            self._audit("restore_failed", target, "reconcile_required:check_DCS")
            return
        self._finish_restore(target, test)

    def _restore_hold(self, target: str, test: ActiveTest) -> str:
        """Write the baseline when allowed; return a hold reason when the intent must stay."""
        tolerance = self.policies[target].readback_tolerance
        current = self.plant.read_out(target)
        if finite_number(current) and abs(current - test.baseline) <= tolerance:
            return ""  # already at the pre-test value: nothing to write
        intended = test.baseline + test.request.amplitude
        if not finite_number(current) or abs(current - intended) > tolerance:
            return "operator_changed_out"
        try:
            self._write_verified(target, test.baseline)
        except LoopNotManError:
            return "loop_not_man"
        return ""

    def _finish_restore(self, target: str, test: ActiveTest) -> None:
        """Close the intent even if the restoration audit fails, then re-raise that failure."""
        try:
            self._audit("restored", target, self.restore_reasons[target])
        except Exception:
            LOGGER.critical("OUT restored for %s but the audit write failed", target)
            raise
        finally:
            self.store.close_intent(test.request.test_id)
            del self.active[target]
            del self.restore_reasons[target]
            self.states[target] = "restored"

    def _recover_test(self, target: str) -> None:
        """Allow explicit restoration of a crash intent without accepting a new test."""
        if target in self.active:
            return
        for record in self.store.load_open():
            for item in record.items:
                if item.target == target and target in self.policies:
                    request = OutputRequest(record.key, target, item.to_value - item.from_value, 0)
                    self.active[target] = ActiveTest(request, item.from_value, self.env.now_ns())
                    return
        raise KeyError(f"No active OUT test or restoration intent for {target}")


def check_output_wiring(
    plant: OutputPlant, outputs: dict[str, OutputPolicy], others: set[str]
) -> None:
    """Refuse target-kind overlap or an adapter unable to monitor and return OUT."""
    if set(outputs) & others:
        raise ValueError("OUT test targets must be distinct from SP and PID targets")
    methods = ("read_out", "write_out", "read_pv", "loop_mode")
    if outputs and not all(callable(getattr(plant, method, None)) for method in methods):
        raise ValueError("OUT targets require live OUT, PV and mode reads and OUT writes")
    mapped = getattr(plant, "output_tags", None)
    if outputs and callable(mapped) and set(mapped()) != set(outputs):
        raise ValueError("OUT policy targets must match out_step plant-map targets")
