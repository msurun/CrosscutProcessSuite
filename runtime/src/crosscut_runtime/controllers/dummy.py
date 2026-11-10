"""A controller for tests: moves nothing, or the same fixed moves every cycle."""

from __future__ import annotations

from collections.abc import Sequence

from crosscut_runtime.controllers.protocol import Move, StepResult
from crosscut_runtime.variable_status import VariableStatus


class DummyController:
    """Counts calls and returns fixed moves; no control logic."""

    def __init__(self, controller_id: str, moves: Sequence[Move] = ()) -> None:
        """Create a dummy with the moves it returns on each ``step``."""
        self.id = controller_id
        self.moves = tuple(moves)
        self.initialised = 0
        self.steps = 0
        self.last_statuses: tuple[VariableStatus, ...] = ()

    def initialise(self, statuses: Sequence[VariableStatus]) -> None:
        """Count the bumpless start."""
        self.initialised += 1
        self.last_statuses = tuple(statuses)

    def step(self, statuses: Sequence[VariableStatus]) -> StepResult:
        """Return the fixed moves and remember the statuses it was given."""
        self.steps += 1
        self.last_statuses = tuple(statuses)
        return StepResult(self.moves, f"dummy step {self.steps}")
