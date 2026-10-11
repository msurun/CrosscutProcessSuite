"""Fault-injection wrapper that corrupts what a client reads from a plant.

Faults are applied to the raw snapshot of the wrapped plant, in the order of the faults list.
Each fault is active from ``start_s`` to ``end_s`` (inclusive of the start, exclusive of the end).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from crosscut_sim.core import BAD, Plant, Scenario

FAULT_KINDS = ("freeze", "drift", "spike", "bad_quality", "dropout")
SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class Fault:
    """A fault to be applied to a tag.

    ``kind`` must be one of FAULT_KINDS. ``start_s`` and ``end_s`` bound the fault window.
    ``magnitude`` is the size of the fault effect (units per hour for drift). ``probability`` is the
    chance of a spike fault being applied (0.0 to 1.0).
    """

    kind: str
    tag_id: str
    start_s: float
    end_s: float
    magnitude: float = 0.0
    probability: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in FAULT_KINDS:
            raise ValueError(f"unknown fault kind: {self.kind}")
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be greater than start_s")


class FaultyPlant:
    """Wrapper that corrupts what a client reads from a plant."""

    def __init__(self, plant: Plant, faults: list[Fault]) -> None:
        self._plant = plant
        self._faults = faults
        self._rng: np.random.Generator | None = None
        self._freeze_memory: dict[str, tuple[float, int]] = {}
        self._snapshot: dict[str, tuple[float, int]] = {}

        for fault in faults:
            if fault.tag_id not in plant.tags:
                raise KeyError(f"unknown tag: {fault.tag_id}")

    @property
    def tags(self) -> Any:
        """Return the wrapped plant's tag catalog."""
        return self._plant.tags

    @property
    def time_s(self) -> float:
        """Return the wrapped plant's current time."""
        return self._plant.time_s

    def reset(self, seed: int, scenario: Scenario | None = None) -> None:
        """Reset the wrapped plant and the fault RNG."""
        self._plant.reset(seed, scenario)
        self._rng = np.random.default_rng([seed, 0xFA17])
        self._freeze_memory.clear()
        self._snapshot = self._plant.snapshot()
        self._apply_faults()

    def step(self) -> None:
        """Step the wrapped plant and recompute the faulted snapshot."""
        self._plant.step()
        self._snapshot = self._plant.snapshot()
        self._apply_faults()

    def read(self, tag_id: str) -> tuple[float, int]:
        """Return the cached faulted reading of ``tag_id``."""
        if tag_id not in self._snapshot:
            raise KeyError(f"unknown tag: {tag_id}")
        return self._snapshot[tag_id]

    def write(self, tag_id: str, value: float) -> None:
        """Write a tag to the wrapped plant."""
        self._plant.write(tag_id, value)

    def snapshot(self) -> dict[str, tuple[float, int]]:
        """Return a copy of the cached faulted snapshot."""
        return self._snapshot.copy()

    def _apply_faults(self) -> None:
        """Apply all faults to the snapshot."""
        for fault in self._faults:
            if fault.start_s <= self.time_s < fault.end_s:
                self._apply_fault(fault)

    def _apply_fault(self, fault: Fault) -> None:
        """Apply a single fault to the snapshot."""
        if fault.tag_id not in self._snapshot:
            return

        value, quality = self._snapshot[fault.tag_id]

        if fault.kind == "freeze":
            value, quality = self._apply_freeze(fault, value, quality)
        elif fault.kind == "drift":
            value = self._apply_drift(fault, value)
        elif fault.kind == "spike":
            value = self._apply_spike(fault, value)
        elif fault.kind == "bad_quality":
            quality = self._apply_bad_quality(quality)
        elif fault.kind == "dropout":
            value, quality = self._apply_dropout()

        self._snapshot[fault.tag_id] = (value, quality)

    def _apply_freeze(self, fault: Fault, value: float, quality: int) -> tuple[float, int]:
        """Apply the freeze fault."""
        if fault.tag_id not in self._freeze_memory:
            self._freeze_memory[fault.tag_id] = (value, quality)
        return self._freeze_memory[fault.tag_id]

    def _apply_drift(self, fault: Fault, value: float) -> float:
        """Apply the drift fault."""
        return value + fault.magnitude * (self.time_s - fault.start_s) / SECONDS_PER_HOUR

    def _apply_spike(self, fault: Fault, value: float) -> float:
        """Apply the spike fault."""
        if self._rng is None:
            raise RuntimeError("RNG not initialized")
        if self._rng.random() < fault.probability:
            sign = 1.0 if self._rng.random() < 0.5 else -1.0
            return value + fault.magnitude * sign
        return value

    def _apply_bad_quality(self, quality: int) -> int:
        """Apply the bad quality fault."""
        return BAD

    def _apply_dropout(self) -> tuple[float, int]:
        """Apply the dropout fault."""
        return (float("nan"), BAD)
