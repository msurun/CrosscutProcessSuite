"""Tests for supervisor advice (ADR 010, S5): silence, gating, direction, clamp, log."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from crosscut_fuzzy.model import system_from_dict
from crosscut_supervisor.advise import Advice, advise
from crosscut_supervisor.audit import AuditLog
from crosscut_supervisor.config import SupervisorConfig
from crosscut_supervisor.gates import GateResult
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = system_from_dict(
    json.loads((ROOT / "fuzzy" / "examples" / "mill_feed_supervisor.json").read_text("utf-8"))
)
SCHEMA = json.loads((ROOT / "schemas" / "advisory-record.schema.json").read_text("utf-8"))
CFG = SupervisorConfig(
    schema_version="1.0.0", id="mill", fuzzy_system_id="mill_feed_supervisor",
    output_id="feed_change", target_loop="FIC101", mode="advisory", gates=(),
    silent_band=0.5, min_activation=0.2, min_interval_s=60.0, display_clamp=(-10.0, 10.0),
)
OPEN = GateResult("open", ())
INCREASE = {"mill_power": 3000.0, "p80": 125.0}  # normal power, fine product: r3
DECREASE = {"mill_power": 3300.0, "p80": 150.0}  # high power: r1


def _advice(
    snapshot: dict[str, float | None] | None = None,
    config: SupervisorConfig = CFG,
    gate: GateResult = OPEN,
    t_ns: int = 1,
) -> Advice:
    """Advice that must not be silent."""
    result = advise(SYSTEM, config, snapshot or INCREASE, gate, t_ns)
    assert result is not None
    return result


def test_increase_and_decrease_direction() -> None:
    up, down = _advice(INCREASE), _advice(DECREASE)
    assert up.direction == "increase" and (up.magnitude or 0) > 0
    assert down.direction == "decrease" and (down.magnitude or 0) > 0


def test_silent_inside_band() -> None:
    quiet = {"mill_power": 3000.0, "p80": 150.0}  # r4 hold
    assert advise(SYSTEM, CFG, quiet, OPEN, 1) is None


def test_silent_below_min_activation() -> None:
    weak = {"mill_power": 3000.0, "p80": 138.0}  # r3 fires at about 0.77
    assert _advice(weak).activation < 0.9
    assert advise(SYSTEM, replace(CFG, min_activation=0.9), weak, OPEN, 1) is None
    assert advise(SYSTEM, replace(CFG, silent_band=100.0), INCREASE, OPEN, 1) is None


def test_mode_off_is_none() -> None:
    assert advise(SYSTEM, replace(CFG, mode="off"), INCREASE, OPEN, 1) is None


def test_blocked_gate_gives_hold() -> None:
    gate = GateResult("blocked", ("manual:FIC101",))
    result = _advice(gate=gate)
    assert (result.direction, result.magnitude, result.activation) == ("hold", None, 0.0)
    assert result.explanation == () and result.gate == gate


def test_nan_input_blocks() -> None:
    result = _advice({"mill_power": math.nan, "p80": 125.0})
    assert result.gate.state == "blocked" and "input_nan:mill_power" in result.gate.reasons
    assert result.magnitude is None and result.inputs["mill_power"] is None
    assert Draft202012Validator(SCHEMA).is_valid(result.to_record())


def test_out_of_range_and_missing_block() -> None:
    far = _advice({"mill_power": 9999.0, "p80": 125.0})
    assert "input_out_of_range:mill_power" in far.gate.reasons
    gone = _advice({"p80": 125.0})
    assert "input_missing:mill_power" in gone.gate.reasons


def test_degraded_gate_still_advises() -> None:
    result = _advice(gate=GateResult("degraded", ("oscillating:FIC101",)))
    assert result.direction == "increase" and result.gate.state == "degraded"


def test_clamp_applied() -> None:
    small = replace(CFG, display_clamp=(-1.0, 1.0))
    up, down = _advice(config=small), _advice(DECREASE, small)
    assert up.magnitude == 1.0 and up.direction == "increase"
    assert down.magnitude == 1.0 and down.direction == "decrease"


def test_clamp_to_zero_is_hold() -> None:
    result = _advice(config=replace(CFG, display_clamp=(-5.0, 0.0)))
    assert result.direction == "hold" and result.magnitude == 0.0


def test_explanation_strongest_first_and_readable() -> None:
    result = _advice()
    strengths = [reason.strength for reason in result.explanation]
    assert strengths == sorted(strengths, reverse=True)
    assert result.activation == pytest.approx(strengths[0])
    top = result.explanation[0]
    assert top.rule_id == "r3"
    expected = "IF mill_power IS normal AND p80 IS fine THEN feed_change IS increase_small"
    assert top.sentence == expected


def test_deterministic_id() -> None:
    assert _advice().advice_id == _advice().advice_id
    assert _advice(t_ns=2).advice_id != _advice(t_ns=1).advice_id
    assert _advice().to_record() == _advice().to_record()


def test_record_validates_and_chains(tmp_path: Path) -> None:
    validator = Draft202012Validator(SCHEMA)
    log = AuditLog(tmp_path / "log.jsonl")
    blocked = GateResult("blocked", ("x",))
    for advice in (_advice(), _advice(DECREASE, t_ns=2), _advice(gate=blocked, t_ns=3)):
        record = advice.to_record()
        assert validator.is_valid(record), list(validator.iter_errors(record))
        log.append(record)
    assert log.verify().ok and len(log.records()) == 3
