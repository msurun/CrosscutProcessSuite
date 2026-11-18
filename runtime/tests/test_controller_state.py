"""Exhaustive transition tests of the controller state machine (Phase 2.5, step 5)."""

from __future__ import annotations

import pytest
from crosscut_runtime.controllers.state import (
    COMMANDS,
    OFF,
    ON,
    SHED,
    STANDBY,
    STATES,
    Health,
    enters_on,
    transition,
)

GOOD = Health()
PROBLEMS = {
    "comm_loss": Health(comm_loss=True),
    "mv_unavailable": Health(unavailable_mvs=("mv1",)),
    "no_good_cv": Health(any_cv_good=False),
    "advisory_only": Health(advisory_only=True),
    "overruns": Health(overrun_limit=True),
}


def test_health_problem_order() -> None:
    assert GOOD.problem() is None
    for reason, health in PROBLEMS.items():
        assert health.problem() == reason
    both = Health(comm_loss=True, advisory_only=True)
    assert both.problem() == "comm_loss"


@pytest.mark.parametrize("state", STATES)
def test_switch_off_from_any_state(state: str) -> None:
    for health in (GOOD, *PROBLEMS.values()):
        assert transition(state, "switch_off", health) == (OFF, "switch_off")


@pytest.mark.parametrize("state", [OFF, STANDBY, SHED])
def test_switch_on_with_good_guards(state: str) -> None:
    assert transition(state, "switch_on", GOOD) == (ON, "switch_on")


@pytest.mark.parametrize("reason", PROBLEMS)
def test_switch_on_refused_from_off_and_standby(reason: str) -> None:
    for state in (OFF, STANDBY):
        assert transition(state, "switch_on", PROBLEMS[reason]) == (STANDBY, reason)


@pytest.mark.parametrize("reason", PROBLEMS)
def test_switch_on_refused_in_shed_stays_shed(reason: str) -> None:
    assert transition(SHED, "switch_on", PROBLEMS[reason]) == (SHED, reason)


def test_switch_on_while_on_changes_nothing_when_healthy() -> None:
    assert transition(ON, "switch_on", GOOD) == (ON, "running")


def test_switch_on_while_on_sheds_when_unhealthy() -> None:
    assert transition(ON, "switch_on", PROBLEMS["comm_loss"]) == (SHED, "comm_loss")


@pytest.mark.parametrize("state", STATES)
def test_standby_command(state: str) -> None:
    assert transition(state, "standby", GOOD) == (STANDBY, "standby")
    assert transition(state, "standby", PROBLEMS["comm_loss"]) == (STANDBY, "standby")


def test_on_stays_on_when_healthy() -> None:
    assert transition(ON, None, GOOD) == (ON, "running")


@pytest.mark.parametrize("reason", PROBLEMS)
def test_on_sheds_on_every_problem(reason: str) -> None:
    assert transition(ON, None, PROBLEMS[reason]) == (SHED, reason)


def test_shed_goes_to_standby_never_straight_to_on() -> None:
    assert transition(SHED, None, GOOD) == (STANDBY, "recovered")


@pytest.mark.parametrize("reason", PROBLEMS)
def test_shed_stays_while_unhealthy(reason: str) -> None:
    assert transition(SHED, None, PROBLEMS[reason]) == (SHED, reason)


@pytest.mark.parametrize("state", [OFF, STANDBY])
def test_idle_states_stay_without_command(state: str) -> None:
    for health in (GOOD, *PROBLEMS.values()):
        assert transition(state, None, health) == (state, state)


def test_every_state_command_pair_gives_a_known_state() -> None:
    for state in STATES:
        for command in (*COMMANDS, None):
            for health in (GOOD, *PROBLEMS.values()):
                assert transition(state, command, health)[0] in STATES


def test_unknown_state_or_command_raises() -> None:
    with pytest.raises(ValueError):
        transition("bogus", None, GOOD)
    with pytest.raises(ValueError):
        transition(ON, "bogus", GOOD)


def test_enters_on_only_when_coming_from_another_state() -> None:
    assert enters_on(STANDBY, ON) and enters_on(SHED, ON) and enters_on(OFF, ON)
    assert not enters_on(ON, ON)
    assert not enters_on(ON, SHED)
