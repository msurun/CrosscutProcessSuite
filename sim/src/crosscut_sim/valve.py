"""Two-parameter valve stiction model (deadband and slip jump), used as a loop fault.

A sticky valve ignores small changes of the controller output, then breaks free and jumps.
The loop cycles around the set-point; this is the ground truth the stiction detector must find.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class StictionSpec:
    """Size of the stiction, in % of valve travel.

    ``deadband`` is how far the command must move away from the valve position before the valve
    breaks free; ``jump`` (0 <= jump <= deadband) is how much of that gap the valve closes when it
    slips. ``deadband == 0`` means a healthy valve that follows the command exactly.
    """

    deadband: float = 0.0
    jump: float = 0.0

    def __post_init__(self) -> None:
        if self.deadband < 0 or not 0.0 <= self.jump <= max(self.deadband, 0.0):
            raise ValueError("stiction needs 0 <= jump <= deadband")

    @property
    def active(self) -> bool:
        """True when the valve really sticks."""
        return self.deadband > 0.0


class StictionValve:
    """Maps the controller command to the real valve position with stick-slip behaviour."""

    def __init__(self, spec: StictionSpec, position: float = 0.0) -> None:
        """Start at ``position`` (same unit as the command) with the given stiction."""
        self.spec = spec
        self.position = position

    def move(self, command: float) -> float:
        """Return the valve position after the command is applied for one step.

        The valve holds while ``|command - position| <= deadband``. Once the gap exceeds it,
        the valve slips to ``command - sign * (deadband - jump)``: it ends up still lagging the
        command by ``deadband - jump``, so it sticks again and the next move needs a new build-up.
        """
        gap = command - self.position
        if abs(gap) > self.spec.deadband:
            self.position = command - np.sign(gap) * (self.spec.deadband - self.spec.jump)
        return self.position
