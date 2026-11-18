"""Tests of the fuzzy controller on the APC core (Phase 2.5, step 6)."""

from __future__ import annotations

from typing import Any

import pytest
from crosscut_fuzzy.model import system_from_dict
from crosscut_runtime.controllers.fuzzy import ControllerBindingError, FuzzyController
from crosscut_runtime.variable_status import BAD, GOOD, VariableStatus

TERMS_IN = [
    {"name": "low", "shape": "trap", "params": [0, 0, 2, 4]},
    {"name": "high", "shape": "trap", "params": [6, 8, 10, 10]},
]
TERMS_OUT = [
    {"name": "down", "shape": "tri", "params": [-10, -10, -5]},
    {"name": "up", "shape": "tri", "params": [5, 10, 10]},
]


def _system(rules: list[dict[str, Any]]) -> Any:
    """Two inputs, one output (a delta from -10 to 10)."""
    inputs = [
        {"id": name, "low": 0, "high": 10, "terms": TERMS_IN} for name in ("cv1", "cv2")
    ]
    out = {"id": "mv1", "low": -10, "high": 10, "terms": TERMS_OUT}
    doc = {"name": "t", "inputs": inputs, "outputs": [out], "rules": rules}
    return system_from_dict(doc)


def _rule(operator: str) -> list[dict[str, Any]]:
    """One rule: either CV high pushes the MV up."""
    return [{
        "id": "r1",
        "if": [{"variable": "cv1", "is": "high"}, {"variable": "cv2", "is": "high"}],
        "operator": operator,
        "then": {"variable": "mv1", "is": "up"},
    }]


OR_RULES = _rule("or")
AND_RULES = _rule("and")


def _doc(limits: dict[str, Any] | None = None) -> dict[str, Any]:
    """Controller entry with two CVs and one MV."""
    mv: dict[str, Any] = {"id": "mv1", "role": "MV", "binding": {"loop": "L1"}}
    mv["limits"] = limits if limits is not None else {}
    return {"id": "c1", "type": "fuzzy", "variables": [
        {"id": "cv1", "role": "CV", "binding": {"tag": "t1"}},
        {"id": "cv2", "role": "CV", "binding": {"tag": "t2"}},
        mv,
    ]}


def _statuses(cv1: float, cv2: float, sp: float = 50.0, bad: str | None = None) -> list[Any]:
    """Statuses of the three variables; ``bad`` names one CV that is bad."""

    def one(name: str, value: float) -> VariableStatus:
        status = BAD if name == bad else GOOD
        reasons = ("quality",) if name == bad else ()
        return VariableStatus(name, name, status, reasons, value, "t")

    mv = VariableStatus("mv1", "pv", GOOD, (), 49.0, "t", sp)
    return [one("cv1", cv1), one("cv2", cv2), mv]


def _make(rules: list[dict[str, Any]], limits: dict[str, Any] | None = None) -> FuzzyController:
    """A controller on a two-input rule base."""
    return FuzzyController(_doc(limits), _system(rules), {"mv1": "sp.tag"})


def test_binding_error_for_input_without_variable() -> None:
    doc = _doc()
    doc["variables"] = [v for v in doc["variables"] if v["id"] != "cv2"]
    with pytest.raises(ControllerBindingError, match="cv2"):
        FuzzyController(doc, _system(OR_RULES), {"mv1": "sp.tag"})


def test_binding_error_for_output_that_is_not_an_mv() -> None:
    doc = _doc()
    doc["variables"][2] = {"id": "mv1", "role": "CV", "binding": {"tag": "t3"}}
    with pytest.raises(ControllerBindingError, match="mv1"):
        FuzzyController(doc, _system(OR_RULES), {"mv1": "sp.tag"})


def test_binding_error_without_gateway_target() -> None:
    with pytest.raises(ControllerBindingError, match="target"):
        FuzzyController(_doc(), _system(OR_RULES), {})


def test_delta_is_added_to_current_setpoint() -> None:
    result = _make(OR_RULES).step(_statuses(9.0, 9.0, sp=50.0))
    assert len(result.moves) == 1
    move = result.moves[0]
    assert move.target_tag == "sp.tag" and move.value > 50.0
    assert "IF cv1 IS high" in result.explanation and move.reason


def test_delta_clamped_by_move_max() -> None:
    free = _make(OR_RULES).step(_statuses(9.0, 9.0)).moves[0].value
    limited = _make(OR_RULES, {"move_max": 1.0}).step(_statuses(9.0, 9.0)).moves[0].value
    assert free > 51.0 and limited == pytest.approx(51.0)


def test_target_clamped_by_operator_limits_then_eng() -> None:
    operator = {"operator": {"lo": 40.0, "hi": 52.0}, "eng": {"lo": 0.0, "hi": 100.0}}
    assert _make(OR_RULES, operator).step(_statuses(9.0, 9.0)).moves[0].value == 52.0
    eng_only = {"eng": {"lo": 0.0, "hi": 53.0}}
    assert _make(OR_RULES, eng_only).step(_statuses(9.0, 9.0)).moves[0].value == 53.0


def test_no_move_when_setpoint_already_at_limit() -> None:
    limits = {"operator": {"lo": 40.0, "hi": 50.0}}
    result = _make(OR_RULES, limits).step(_statuses(9.0, 9.0, sp=50.0))
    assert result.moves == () and "hold" in result.explanation


def test_bad_cv_dropped_other_stays() -> None:
    result = _make(OR_RULES).step(_statuses(1.0, 9.0, bad="cv1"))
    assert len(result.moves) == 1 and "cv2 IS high" in result.moves[0].reason


def test_bad_cv_in_and_rule_gives_insufficient_inputs() -> None:
    result = _make(AND_RULES).step(_statuses(9.0, 9.0, bad="cv2"))
    assert result.moves == () and result.explanation == "insufficient_inputs"


def test_all_inputs_bad_gives_insufficient_inputs() -> None:
    statuses = _statuses(9.0, 9.0)
    statuses[0] = VariableStatus("cv1", "t1", BAD, ("stale",), None, None)
    statuses[1] = VariableStatus("cv2", "t2", BAD, ("stale",), None, None)
    assert _make(OR_RULES).step(statuses).explanation == "insufficient_inputs"


def test_bad_mv_gives_no_move() -> None:
    statuses = _statuses(9.0, 9.0)
    statuses[2] = VariableStatus("mv1", "pv", BAD, ("stale",), None, None, None)
    assert _make(OR_RULES).step(statuses).moves == ()


def test_initialise_records_base_setpoint_and_moves_nothing() -> None:
    controller = _make(OR_RULES)
    controller.initialise(_statuses(9.0, 9.0, sp=42.0))
    assert controller.base_sp == {"mv1": 42.0}
