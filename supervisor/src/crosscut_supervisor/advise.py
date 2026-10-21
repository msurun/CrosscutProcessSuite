"""Turn a fuzzy rule base and one process snapshot into a gated, explained advice (ADR 010, S5).

Fail closed: a blocked gate or a bad input yields a 'hold' advice without magnitude so the log
shows why nothing was advised. The module is pure: it never reads files and never writes to a plant.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from crosscut_fuzzy.model import FuzzySystem, Rule
from crosscut_fuzzy.payload import infer_payload

from crosscut_supervisor.config import SupervisorConfig
from crosscut_supervisor.gates import GateResult, gate_inputs_ok


@dataclass(frozen=True)
class Reason:
    """One rule that explains the advice: id, readable sentence and firing strength."""

    rule_id: str
    sentence: str
    strength: float


@dataclass(frozen=True)
class Advice:
    """An advisory record of kind 'advice' (see schemas/advisory-record.schema.json)."""

    advice_id: str
    t_ns: int
    target_loop: str
    direction: str
    magnitude: float | None
    activation: float
    explanation: tuple[Reason, ...]
    inputs: Mapping[str, float | None]
    gate: GateResult
    rulebase_sha256: str

    def to_record(self) -> dict[str, Any]:
        """Schema-valid record; ``prev_sha256`` is empty, ``AuditLog.append`` fills the chain."""
        return {
            "kind": "advice",
            "advice_id": self.advice_id,
            "t_ns": self.t_ns,
            "target_loop": self.target_loop,
            "direction": self.direction,
            "magnitude": self.magnitude,
            "activation": self.activation,
            "explanation": [dataclasses.asdict(reason) for reason in self.explanation],
            "inputs": dict(self.inputs),
            "gate": {"state": self.gate.state, "reasons": list(self.gate.reasons)},
            "rulebase_sha256": self.rulebase_sha256,
            "prev_sha256": "",
        }


def rulebase_sha256(system: FuzzySystem) -> str:
    """SHA-256 of the canonical JSON (sorted keys, compact) of the whole rule base."""
    text = json.dumps(
        dataclasses.asdict(system), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def advise(
    system: FuzzySystem,
    config: SupervisorConfig,
    snapshot: Mapping[str, float | None],
    gate: GateResult,
    t_ns: int,
) -> Advice | None:
    """Advice for one snapshot, a blocked 'hold' record, or None when silent or mode is off.

    Display clamp: it is applied to the signed crisp value (clamp to [lo, hi]); the magnitude is
    the absolute value of the clamped number and the direction follows the clamped sign, so a
    clamp that excludes one side can turn a push into 'hold'. ``abs`` is never clamped itself.
    """
    if config.mode == "off":
        return None
    sha = rulebase_sha256(system)
    advice_id = hashlib.sha256(f"{config.id}|{sha}|{t_ns}".encode()).hexdigest()
    inputs = _recorded_inputs(system, snapshot)
    gate = _merged_gate(system, snapshot, gate)
    if gate.state == "blocked":
        return Advice(advice_id, t_ns, config.target_loop, "hold", None, 0.0, (), inputs, gate, sha)
    return _evaluated(system, config, (advice_id, t_ns, inputs, gate, sha))


def _evaluated(
    system: FuzzySystem, config: SupervisorConfig, meta: tuple[Any, ...]
) -> Advice | None:
    """Run the fuzzy system on the (valid) inputs and build the advice, or None when silent."""
    advice_id, t_ns, inputs, gate, sha = meta
    values = {key: float(val) for key, val in inputs.items() if val is not None}
    payload = infer_payload(system, values)
    crisp = payload["outputs"][config.output_id]["crisp"]
    activation = min(1.0, max(payload["firing"].values(), default=0.0))
    if crisp is None or abs(crisp) <= config.silent_band or activation < config.min_activation:
        return None
    low, high = config.display_clamp
    clamped = min(max(float(crisp), low), high)
    direction = "increase" if clamped > 0 else "decrease" if clamped < 0 else "hold"
    return Advice(
        advice_id, t_ns, config.target_loop, direction, abs(clamped), activation,
        _explanation(system, payload), inputs, gate, sha,
    )


def _recorded_inputs(
    system: FuzzySystem, snapshot: Mapping[str, float | None]
) -> dict[str, float | None]:
    """Snapshot values of the system inputs; NaN and missing become None (JSON has no NaN)."""
    result: dict[str, float | None] = {}
    for variable in system.inputs:
        value = snapshot.get(variable.id)
        result[variable.id] = None if value is None or math.isnan(value) else float(value)
    return result


def _merged_gate(
    system: FuzzySystem, snapshot: Mapping[str, float | None], gate: GateResult
) -> GateResult:
    """The caller's gate plus input-validity reasons; any input reason blocks (fail closed)."""
    ranges = {variable.id: (variable.low, variable.high) for variable in system.inputs}
    problems = gate_inputs_ok(snapshot, ranges)
    if not problems:
        return gate
    return GateResult("blocked", tuple(sorted(set(gate.reasons) | set(problems))))


def _explanation(system: FuzzySystem, payload: Mapping[str, Any]) -> tuple[Reason, ...]:
    """Dominant rules (strongest first) with their readable sentences."""
    rules = {rule.id: rule for rule in system.rules}
    firing = payload["firing"]
    return tuple(
        Reason(rule_id, _sentence(rules[rule_id]), float(firing[rule_id]))
        for rule_id in payload["dominant"]
    )


def _sentence(rule: Rule) -> str:
    """'IF <input> IS <term> AND ... THEN <output> IS <term>' from the rule's ids."""
    joiner = f" {rule.operator.upper()} "
    condition = joiner.join(f"{c.variable} IS {c.term}" for c in rule.conditions)
    return f"IF {condition} THEN {rule.consequent.variable} IS {rule.consequent.term}"
