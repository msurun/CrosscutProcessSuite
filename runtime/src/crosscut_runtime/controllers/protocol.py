"""The contract between the controller host and a controller implementation.

A controller never writes to a plant. It returns moves; the host hands them to the gateway
as proposals.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from crosscut_runtime.variable_status import VariableStatus


@dataclass(frozen=True)
class Move:
    """One proposed change of a manipulated variable."""

    variable_id: str
    target_tag: str
    value: float
    reason: str


@dataclass(frozen=True)
class StepResult:
    """Moves of one cycle and a short plain-language explanation.

    ``diagnostics`` is optional plain JSON for the console (MPC: limits, predictions, active
    constraints); ``shed`` asks the host to shed the controller to base control.
    """

    moves: tuple[Move, ...]
    explanation: str
    diagnostics: Mapping[str, Any] | None = None
    shed: bool = False


class Controller(Protocol):
    """An advanced controller driven by the host, one ``step`` per cycle."""

    id: str

    def initialise(self, statuses: Sequence[VariableStatus]) -> None:
        """Take the current values as the starting point (bumpless start)."""
        ...

    def step(self, statuses: Sequence[VariableStatus]) -> StepResult:
        """Compute one cycle; variables with status ``bad`` must be left out."""
        ...
