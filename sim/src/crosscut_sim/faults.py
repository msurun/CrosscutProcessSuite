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
        """Wrap ``plant`` with its ``faults``, failing fast on a fault that names an unknown tag.

        Initialises the per-run state:

        * ``_rng`` is the fault random number generator; it stays None until ``reset`` seeds it.
        * ``_freeze_memory`` remembers the reading a tag showed when its freeze began, so the
          same reading is reported for as long as the freeze is active.
        * ``_snapshot`` is the faulted snapshot returned by ``read`` and ``snapshot``.

        Raises:
            KeyError: if a fault references a tag id that the plant does not
                define; the message names the offending tag id.
        """
        self._plant = plant
        self._faults = faults
        self._rng: np.random.Generator | None = None

        # tag_id -> (frozen value, quality) captured when the freeze began; the
        # value is recalled on every later read while the fault is active.
        self._freeze_memory: dict[str, tuple[float, int]] = {}

        # tag_id -> (value, quality) of the current faulted snapshot. This cache
        # is what read() and snapshot() return.
        self._snapshot: dict[str, tuple[float, int]] = {}

        # Validate every fault up front so a typo surfaces here, at wiring time,
        # rather than midway through a simulation run.
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
        """Reset the wrapped plant and the fault RNG.

        Called at the start of every episode. The fault RNG is seeded from
        ``seed`` so that a run is fully reproducible: same seed, same faults.
        """
        # Hand the episode seed to the plant first, so plant state and fault
        # decisions are driven by the same episode seed.
        self._plant.reset(seed, scenario)

        # Separate RNG for the fault injector, seeded from the episode seed and
        # the constant 0xFA17 (a fixed tag, so the fault stream differs from any
        # other RNG the plant may build from the same episode seed).
        # default_rng accepts a list of integers and hashes them into one seed.
        self._rng = np.random.default_rng([seed, 0xFA17])

        self._freeze_memory.clear()

        # Capture the freshly reset plant state, then inject faults so that the
        # episode's very first observation already reflects the fault draw.
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
        """Apply a single fault to the snapshot.

        The snapshot maps each tag_id (the unique name of a sensor or device reading) to a
        (value, quality) pair, and it is the model's current picture of the plant, which the
        simulation evolves by writing corrupted readings back into it.

        This method is how one fault is injected: when a fault names a tag that is not present
        it is silently ignored, otherwise the tagged reading is replaced by its corrupted form.
        It mutates the snapshot in place and returns nothing.
        """
        # A fault can reference a tag the model does not have (for example a removed sensor),
        # so treating a missing tag as "nothing to do" keeps a stale fault from being fatal.
        if fault.tag_id not in self._snapshot:
            return

        # Unpack the reading into its two parts before corrupting it: `value` is the physical
        # measurement in the tag's own unit (degrees, bar, cubic metres per hour, ...) and
        # `quality` says how much the reading can be trusted, not its magnitude.
        value, quality = self._snapshot[fault.tag_id]
        # `_corrupt` decides the corrupted reading; the result is written back under the same
        # tag, so the snapshot keeps its invariant of exactly one reading per tag_id.
        self._snapshot[fault.tag_id] = self._corrupt(fault, value, quality)

    def _corrupt(self, fault: Fault, value: float, quality: int) -> tuple[float, int]:
        """Return the faulted ``(value, quality)`` pair for the kind of ``fault``.

        This is the dispatcher of the sensor fault-injection model: a real sensor
        reports a measured ``value`` together with a quality code, and each
        ``fault`` alters one of the two. Faults that distort the measurement keep
        the quality untouched, faults that only damage the quality keep the value
        untouched, and ``dropout`` (the sensor stops answering) affects both.
        Unknown kinds are not an error: the input is passed through unchanged, so
        a misspelled kind degrades to "no fault" instead of crashing the stream.
        """
        # "freeze": the sensor keeps reporting whatever it was reading when the
        # fault started. Only the freeze helper knows that stuck value, so it
        # owns both the value and the quality.
        if fault.kind == "freeze":
            return self._apply_freeze(fault, value, quality)
        # "drift": a bias growing linearly with time since start_s is added to the value; the
        # reading is still considered trustworthy, so the quality code is left as it was.
        if fault.kind == "drift":
            return self._apply_drift(fault, value), quality
        # "spike": one large outlier is added on top of the value; quality is
        # again preserved because a spike is a momentary value error.
        if fault.kind == "spike":
            return self._apply_spike(fault, value), quality
        # "bad_quality": the number is still plausible but must not be trusted,
        # so only the quality code is downgraded (always to BAD).
        if fault.kind == "bad_quality":
            return value, self._apply_bad_quality()
        # "dropout": the sensor sends nothing at all. The helper returns the
        # conventional (value, quality) pair for a missing sample, hence the
        # whole result replaces the pair instead of one of its members.
        if fault.kind == "dropout":
            return self._apply_dropout()
        # Any unrecognised kind: hand the reading back exactly as received.
        return value, quality

    def _apply_freeze(self, fault: Fault, value: float, quality: int) -> tuple[float, int]:
        """Apply the freeze fault."""
        if fault.tag_id not in self._freeze_memory:
            self._freeze_memory[fault.tag_id] = (value, quality)
        return self._freeze_memory[fault.tag_id]

    def _apply_drift(self, fault: Fault, value: float) -> float:
        """Apply the drift fault: bias = magnitude (units/hour) * hours since the fault started."""
        return value + fault.magnitude * (self.time_s - fault.start_s) / SECONDS_PER_HOUR

    def _apply_spike(self, fault: Fault, value: float) -> float:
        """Apply the spike fault.

        A spike is an occasional, large, symmetric perturbation of a single sample:
        with probability ``fault.probability`` we add or subtract ``fault.magnitude``,
        otherwise the sample passes through untouched.

        Args:
            fault: The spike definition; ``probability`` is a dimensionless
                fraction in [0, 1] and ``magnitude`` is expressed in the
                same unit as ``value``.
            value: The clean sample, in whatever unit the caller uses.

        Returns:
            The possibly perturbed sample, in the unit of ``value``.

        Raises:
            RuntimeError: If the random number generator was never initialized.
        """
        if self._rng is None:
            raise RuntimeError("RNG not initialized")
        # One uniform draw from [0, 1) decides whether this sample is hit at all:
        # P(hit) = fault.probability, so a value of 0.02 means roughly 1 in 50 samples.
        if self._rng.random() < fault.probability:
            # Second independent draw picks the direction; 0.5 gives equal odds of
            # an upward (+1) and a downward (-1) spike, keeping the distortion unbiased.
            sign = 1.0 if self._rng.random() < 0.5 else -1.0
            return value + fault.magnitude * sign
        return value

    def _apply_bad_quality(self) -> int:
        """Apply the bad quality fault."""
        return BAD

    def _apply_dropout(self) -> tuple[float, int]:
        """Apply the dropout fault."""
        return (float("nan"), BAD)
