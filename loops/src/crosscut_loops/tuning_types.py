"""Input types of the tuning payload: the user's request and one data window.

Kept apart from ``tuning_payload`` so that the model-specific payload builders (FOPDT and
IPDT) can share them without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from crosscut_loops.tuning_report import DEFAULT_ROBUSTNESS


@dataclass(frozen=True)
class TuningRequest:
    """What the user chose: the window (None = best suggestion) and the robustness slider.

    ``max_swing`` (largest tolerated PV swing, PV units) and ``load_step_pct`` (expected load
    step, % OUT) are only used for integrating loops; give both or neither, both positive.
    """

    start_s: float | None = None
    end_s: float | None = None
    robustness: float = DEFAULT_ROBUSTNESS
    stiction_suspected: bool = False
    max_swing: float | None = None
    load_step_pct: float | None = None

    def __post_init__(self) -> None:
        """Reject a swing limit without a load step (or the reverse) and non-positive values."""
        given = [v for v in (self.max_swing, self.load_step_pct) if v is not None]
        if len(given) == 1:
            raise ValueError("max_swing and load_step_pct must be given together")
        if any(not value > 0.0 for value in given):
            raise ValueError("max_swing and load_step_pct must be positive")


@dataclass(frozen=True)
class WindowData:
    """One data window of a loop: time stamps, controller output, process value, sample time."""

    t_s: np.ndarray
    controller_output: np.ndarray
    process_value: np.ndarray
    dt_s: float
