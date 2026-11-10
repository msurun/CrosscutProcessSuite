"""Fuzzy controller on the APC core (Phase 2.5, step 6).

Binds a fuzzy rule base to the variables of a site ``controllers[]`` entry (fuzzy variable id ==
controller variable id). A fuzzy output is a delta added to the MV's current setpoint; the only
limits are the catalogue limits of the MV (``move_max``, operator range, else engineering range).
A bad input is dropped together with the rules that need it; no move is made when no rule is left.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from typing import Any

from crosscut_fuzzy.model import AND, FuzzySystem, Rule
from crosscut_fuzzy.payload import infer_payload
from crosscut_supervisor.advise import dominant_reasons

from crosscut_runtime.controllers.protocol import Move, StepResult
from crosscut_runtime.variable_status import BAD, VariableStatus

INPUT_ROLES = ("CV", "DV", "ICV")
INSUFFICIENT = "insufficient_inputs"
MAX_SENTENCES = 2


class ControllerBindingError(ValueError):
    """The rule base does not fit the controller's variables (the message says where)."""


def _bind(system: FuzzySystem, variables: Sequence[Mapping[str, Any]]) -> None:
    """Check that every fuzzy input is a CV/DV/ICV and every output an MV of the controller."""
    roles = {var["id"]: var["role"] for var in variables}
    for item in system.inputs:
        if roles.get(item.id) not in INPUT_ROLES:
            raise ControllerBindingError(f"fuzzy input {item.id!r} has no CV/DV/ICV variable")
    for item in system.outputs:
        if roles.get(item.id) != "MV":
            raise ControllerBindingError(f"fuzzy output {item.id!r} has no MV variable")


def _reduced(system: FuzzySystem, dropped: frozenset[str]) -> FuzzySystem:
    """The system without dropped inputs: AND rules needing one are off, OR rules lose a clause."""
    inputs = tuple(i for i in system.inputs if i.id not in dropped)
    rules = tuple(_reduced_rule(rule, dropped) for rule in system.rules)
    return dataclasses.replace(system, inputs=inputs, rules=rules)


def _reduced_rule(rule: Rule, dropped: frozenset[str]) -> Rule:
    """One rule without the clauses on dropped inputs (switched off when it cannot stand)."""
    kept = tuple(c for c in rule.conditions if c.variable not in dropped)
    if len(kept) == len(rule.conditions):
        return rule
    if rule.operator == AND or not kept:
        return dataclasses.replace(rule, enabled=False)
    return dataclasses.replace(rule, conditions=kept)


def _clamp(value: float, bounds: Mapping[str, float] | None) -> float:
    """Value limited to ``{"lo", "hi"}``; unchanged without bounds."""
    return value if bounds is None else min(max(value, bounds["lo"]), bounds["hi"])


class FuzzyController:
    """Implements the Controller protocol for a fuzzy rule base."""

    def __init__(
        self,
        controller_doc: Mapping[str, Any],
        system: FuzzySystem,
        mv_targets: Mapping[str, str],
    ) -> None:
        """Bind the rule base to the controller; ControllerBindingError when it does not fit."""
        self.id = str(controller_doc["id"])
        variables = controller_doc["variables"]
        _bind(system, variables)
        self._system = system
        self._limits = {v["id"]: v.get("limits", {}) for v in variables}
        self._targets = {out.id: mv_targets.get(out.id) for out in system.outputs}
        missing = [name for name, tag in self._targets.items() if not tag]
        if missing:
            raise ControllerBindingError(f"no gateway target for MV {missing[0]!r}")
        self.base_sp: dict[str, float] = {}

    def apply_limits(self, variables: Sequence[Mapping[str, Any]]) -> None:
        """Take the limits of the effective variables (catalogue plus operator overrides)."""
        self._limits = {v["id"]: v.get("limits", {}) for v in variables}

    def initialise(self, statuses: Sequence[VariableStatus]) -> None:
        """Record the current setpoints as the base (bumpless: no move is made here)."""
        self.base_sp = {
            s.variable_id: s.sp_value
            for s in statuses
            if s.variable_id in self._targets and s.sp_value is not None
        }

    def step(self, statuses: Sequence[VariableStatus]) -> StepResult:
        """One cycle: infer on the usable inputs, then turn each output delta into a move."""
        by_id = {s.variable_id: s for s in statuses}
        usable = {
            i.id: by_id[i.id].value
            for i in self._system.inputs
            if i.id in by_id and by_id[i.id].status != BAD and _finite(by_id[i.id].value)
        }
        dropped = frozenset(i.id for i in self._system.inputs) - usable.keys()
        system = _reduced(self._system, dropped)
        if not usable or not any(rule.enabled for rule in system.rules):
            return StepResult((), INSUFFICIENT)
        payload = infer_payload(system, {k: float(v) for k, v in usable.items() if v is not None})
        return self._result(system, payload, by_id)

    def _result(
        self, system: FuzzySystem, payload: Mapping[str, Any], by_id: Mapping[str, VariableStatus]
    ) -> StepResult:
        """Moves for every output of an inference, with one explanation."""
        why = "; ".join(r.sentence for r in dominant_reasons(system, payload)[:MAX_SENTENCES])
        moves, notes = [], []
        for out in self._system.outputs:
            move, note = self._move(out.id, payload["outputs"][out.id]["crisp"], by_id, why)
            moves += [move] if move else []
            notes.append(note)
        return StepResult(tuple(moves), " | ".join(notes) + (f" [{why}]" if why else ""))

    def _move(
        self, mv_id: str, crisp: float | None, by_id: Mapping[str, VariableStatus], why: str
    ) -> tuple[Move | None, str]:
        """Move of one MV and its note: setpoint plus delta, limited by move_max and operator."""
        status = by_id.get(mv_id)
        if crisp is None:
            return None, f"{mv_id}: no rule fired"
        if status is None or status.status == BAD or status.sp_value is None:
            return None, f"{mv_id}: MV not usable"
        limits = self._limits[mv_id]
        step_max = limits.get("move_max")
        delta = crisp if step_max is None else min(max(crisp, -step_max), step_max)
        bounds = limits.get("operator") or limits.get("eng")
        target = _clamp(status.sp_value + delta, bounds)
        if math.isclose(target, status.sp_value):
            return None, f"{mv_id}: hold"
        note = f"{mv_id}: {target - status.sp_value:+.4g}"
        return Move(mv_id, str(self._targets[mv_id]), target, why or note), note


def _finite(value: float | None) -> bool:
    """True for a real number."""
    return value is not None and math.isfinite(value)
