"""Pure state machine of one controller: off, standby, on, shed.

``switch_on`` needs healthy guards. From ``on`` the machine drops to ``shed`` when a guard
fails; from ``shed`` it returns to ``standby`` by itself once the guards pass, and never
straight back to ``on``: the operator has to switch on again. ``switch_off`` always wins.
Entering ``on`` runs the controller's ``initialise`` (done by the host, see ``enters_on``).
"""

from __future__ import annotations

from dataclasses import dataclass

OFF, STANDBY, ON, SHED = "off", "standby", "on", "shed"
STATES = (OFF, STANDBY, ON, SHED)
SWITCH_ON, SWITCH_OFF, STANDBY_CMD = "switch_on", "switch_off", "standby"
COMMANDS = (SWITCH_ON, SWITCH_OFF, STANDBY_CMD)
DEFAULT_MAX_OVERRUNS = 3


@dataclass(frozen=True)
class Health:
    """What the guards look at in one cycle."""

    comm_loss: bool = False
    unavailable_mvs: tuple[str, ...] = ()
    any_cv_good: bool = True
    advisory_only: bool = False
    overrun_limit: bool = False

    def problem(self) -> str | None:
        """First failing guard as a reason code, ``None`` when all pass."""
        checks = (
            (self.comm_loss, "comm_loss"),
            (bool(self.unavailable_mvs), "mv_unavailable"),
            (not self.any_cv_good, "no_good_cv"),
            (self.advisory_only, "advisory_only"),
            (self.overrun_limit, "overruns"),
        )
        return next((name for failed, name in checks if failed), None)


def _switch_on(state: str, health: Health) -> tuple[str, str]:
    """Result of ``switch_on``: on when guards pass, else standby (shed stays shed)."""
    problem = health.problem()
    if problem is None:
        return ON, SWITCH_ON
    return (SHED if state == SHED else STANDBY), problem


def _automatic(state: str, health: Health) -> tuple[str, str]:
    """Result of a cycle without a command."""
    problem = health.problem()
    if state == ON:
        return (ON, "running") if problem is None else (SHED, problem)
    if state == SHED:
        return (STANDBY, "recovered") if problem is None else (SHED, problem)
    return state, state


def transition(state: str, command: str | None, health: Health) -> tuple[str, str]:
    """Return ``(new_state, reason)`` for the current state, an optional command and health."""
    if state not in STATES or (command is not None and command not in COMMANDS):
        raise ValueError(f"unknown state {state!r} or command {command!r}")
    if command == SWITCH_OFF:
        return OFF, SWITCH_OFF
    if command == SWITCH_ON and state != ON:
        return _switch_on(state, health)
    if command == STANDBY_CMD:
        return STANDBY, STANDBY_CMD
    return _automatic(state, health)


def enters_on(old_state: str, new_state: str) -> bool:
    """True when the move starts the controller (the host then calls ``initialise``)."""
    return new_state == ON and old_state != ON
