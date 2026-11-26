"""Fuzzy controller initialisation tracks fresh operator setpoints.

The incremental controller has previous-output state, with no integral accumulator.
"""

from runtime.tests.test_fuzzy_controller import OR_RULES, _make, _statuses


def test_stale_previous_output_is_replaced_and_the_first_move_is_zero() -> None:
    controller = _make(OR_RULES)
    controller.base_sp = {"mv1": 99.0}
    controller.initialise(_statuses(9, 9, sp=42))
    result = controller.step(_statuses(9, 9, sp=42))
    assert controller.base_sp == {"mv1": 42}
    assert result.moves[0].value == 42
    assert result.explanation == "bumpless_initialisation"


def test_the_first_move_uses_the_operator_value_changed_after_switch_on() -> None:
    controller = _make(OR_RULES)
    controller.initialise(_statuses(9, 9, sp=42))
    result = controller.step(_statuses(9, 9, sp=61))
    assert result.moves[0].value == 61
    assert controller.base_sp == {"mv1": 61}
    assert controller.step(_statuses(9, 9, sp=61)).moves[0].value > 61


def test_handover_back_reinitialises_previous_output() -> None:
    controller = _make(OR_RULES)
    controller.initialise(_statuses(9, 9, sp=42))
    controller.step(_statuses(9, 9, sp=42))
    controller.step(_statuses(9, 9, sp=42))
    controller.initialise(_statuses(9, 9, sp=73))
    assert controller.step(_statuses(9, 9, sp=73)).moves[0].value == 73
    assert controller.base_sp == {"mv1": 73}
