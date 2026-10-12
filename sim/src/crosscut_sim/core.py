"""Simulator core: tags, scenarios, first-order-plus-dead-time elements and the Plant protocol.

Time base: all times are in seconds. Plants run on a fixed step ``Scenario.dt_s`` and are fully
deterministic for a given seed.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

SCHEMA_VERSION = "0.1.0"

# Quality codes (match the dataset contract: 0 Good, 1 Uncertain, 2 Bad).
GOOD = 0
UNCERTAIN = 1
BAD = 2

# Loop mode codes used by the MODE tags.
MAN = 0
AUTO = 1
CAS = 2


@dataclass(frozen=True)
class TagSpec:
    """Static description of one tag; maps one-to-one to an entry of ``tags.schema.json``."""

    id: str
    unit: str
    role: str
    type: str = "float"
    description: str = ""
    eng_min: float | None = None
    eng_max: float | None = None
    writable: bool = False
    sample_period_s: float = 1.0

    def to_dict(self, driver: str = "sim") -> dict[str, Any]:
        """Return the tag as a schema-conformant dict; ``driver`` names the data source.

        The dict mirrors the tag schema used by the configuration files and the
        API: ``id``/``name`` carry the tag path, ``source`` tells the poller where
        to read the value, and the optional engineering-range keys are only
        included when the tag actually declares a range.

        Returns:
            A new dict; mutating it does not change the tag object.
        """
        # The required schema keys are always present. ``id`` doubles as the
        # ``name`` and as the driver ``address`` because a tag is addressed by
        # its full path (e.g. ``line1.tank.level``).
        # ``unit`` is the physical unit of the value (e.g. ``"degC"``, ``"bar"``);
        # ``sample_period_s`` is the poll interval in seconds.
        doc: dict[str, Any] = {
            "id": self.id,
            "name": self.id,
            "description": self.description,
            "unit": self.unit,
            "type": self.type,
            "role": self.role,
            "source": {"driver": driver, "address": self.id},
            "sample_period_s": self.sample_period_s,
            "writable": self.writable,
        }
        # ``eng_min`` and ``eng_max`` (the engineering range, in ``unit``) are
        # optional: they are omitted rather than emitted as ``null`` so consumers
        # can distinguish "no range declared" from "range bound is zero".
        if self.eng_min is not None:
            doc["eng_min"] = self.eng_min
        if self.eng_max is not None:
            doc["eng_max"] = self.eng_max
        return doc


class TagCatalog:
    """Ordered collection of unique tag specifications."""

    def __init__(self, specs: Sequence[TagSpec]) -> None:
        self._specs: dict[str, TagSpec] = {}
        for spec in specs:
            if spec.id in self._specs:
                raise ValueError(f"duplicate tag id: {spec.id}")
            self._specs[spec.id] = spec

    def __iter__(self) -> Iterator[TagSpec]:
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, tag_id: object) -> bool:
        return tag_id in self._specs

    def __getitem__(self, tag_id: str) -> TagSpec:
        return self._specs[tag_id]

    def ids(self) -> list[str]:
        """Return the tag ids in catalog order."""
        return list(self._specs)

    def to_document(self) -> dict[str, Any]:
        """Return a document that validates against ``schemas/tags.schema.json``."""
        return {"schema_version": SCHEMA_VERSION, "tags": [spec.to_dict() for spec in self]}


@dataclass(frozen=True)
class Event:
    """Write ``value`` to ``tag_id`` when simulation time reaches ``t_s``."""

    t_s: float
    tag_id: str
    value: float


@dataclass(frozen=True)
class Scenario:
    """Run configuration of a plant."""

    name: str = "nominal"
    duration_s: float = 6 * 3600.0
    dt_s: float = 1.0
    measurement_noise: float = 1.0  # scale factor of the nominal sensor noise, 0 disables it
    disturbance_sigma: float = 0.0  # std of the stochastic feed disturbance (engineering units)
    disturbance_tau_s: float = 1800.0  # correlation time of the stochastic disturbance
    events: tuple[Event, ...] = ()
    # Plant-specific numeric options as (name, value) pairs; the first match wins.
    params: tuple[tuple[str, float], ...] = ()

    def param(self, name: str, default: float) -> float:
        """Return the plant-specific option ``name`` or ``default`` when it is not set."""
        for key, value in self.params:
            if key == name:
                return value
        return default

    def __post_init__(self) -> None:
        if self.dt_s <= 0 or self.duration_s <= 0:
            raise ValueError("dt_s and duration_s must be positive")
        if self.measurement_noise < 0 or self.disturbance_sigma < 0:
            raise ValueError("noise levels must be non-negative")


class Fopdt:
    """First-order lag with dead time, exactly discretized: ``y' = (K u(t - theta) - y) / tau``.

    ``update(u_k)`` consumes the input of the current step and returns the output of the next step.
    With a constant unit input applied from the first call, the output after ``j`` calls is
    ``K * (1 - a**(j - n))`` for ``j >= n`` (and 0 before), where ``a = exp(-dt/tau)`` and
    ``n = round(theta/dt)``. Variables are deviations from the operating point.
    """

    def __init__(
        self, gain: float, tau_s: float, delay_s: float, dt_s: float, y0: float = 0.0
    ) -> None:
        """Set up a discretised first-order lag (exponential) filter with dead time.

        Models a plant whose continuous transfer function is
        ``G(s) = gain / (1 + tau_s * s)`` followed by a pure transport delay
        of ``delay_s`` seconds, sampled every ``dt_s`` seconds.

        Args:
            gain: Steady-state ratio of output change to input change.
            tau_s: Time constant of the lag, in seconds; time to reach 63.2%
                (``1 - 1/e``) of a step response.
            delay_s: Dead time before the output reacts, in seconds.
            dt_s: Sampling interval, in seconds.
            y0: Initial filter output, in the same unit as the output signal.

        Raises:
            ValueError: If ``tau_s`` or ``dt_s`` is not positive, or ``delay_s``
                is negative.
        """
        if tau_s <= 0 or dt_s <= 0 or delay_s < 0:
            raise ValueError("tau_s and dt_s must be positive and delay_s non-negative")
        self.gain = gain

        # Discrete pole of the lag: sampling ``exp(-t/tau)`` at t = dt_s gives
        # the per-step decay factor, so the recurrence is
        # ``y[k] = a * y[k-1] + gain * (1 - a) * u_delayed[k]``.
        self._a = math.exp(-dt_s / tau_s)

        # Dead time quantised to a whole number of samples using round-to-nearest;
        # a delay shorter than half a step is dropped because it rounds to zero.
        delay_steps = round(delay_s / dt_s)

        # Ring buffer holding the last ``delay_steps`` inputs. ``maxlen`` makes
        # the deque evict the oldest value automatically when appending to a full
        # buffer, so the leftmost element is the input from ``delay_steps`` steps ago.
        # ``None`` when there is no delay, so the hot path can skip the buffer.
        self._buf: deque[float] | None = (
            deque([0.0] * delay_steps, maxlen=delay_steps) if delay_steps > 0 else None
        )

        # Current filter output, kept between calls so ``update`` is stateful.
        self.value = y0

    def update(self, u: float) -> float:
        """Consume the input ``u`` of this step and return the output of the next step.

        The filter is a first-order exponential moving average (EMA), also called a
        first-order low-pass filter. In plain words it keeps a running weighted
        average of past inputs, giving more weight to recent ones, so that abrupt
        changes are smoothed.

        ``self._a`` is the smoothing factor, unitless, in [0, 1): it is the fraction
        of the previous output that survives each step. ``self.gain`` is the unitless
        steady-state gain: after many constant inputs the output tends to
        ``gain * u``, not ``u``.

        ``self._buf`` is a fixed-length FIFO ring of the last inputs, used to delay
        the input by ``len(self._buf)`` steps (dead time). When it is ``None`` the
        filter has no delay and consumes itself.

        Returns the filtered output at this step, in the same unit as ``u``.
        """
        if self._buf is None:
            u_delayed = u
        else:
            # Shift the window: the leftmost element is the input from delay_steps steps ago;
            # store the new input at the right end, dropping the oldest.
            u_delayed = self._buf[0]
            self._buf.append(u)
        # Weighted recurrence of the EMA: new = a * old + (1 - a) * current input.
        # (1 - a) is the weight on the fresh sample; ``gain`` rescales the input.
        self.value = self._a * self.value + self.gain * (1.0 - self._a) * u_delayed
        return self.value


class Plant(Protocol):
    """Interface every simulated plant implements."""

    tags: TagCatalog
    time_s: float

    def reset(self, seed: int, scenario: Scenario | None = None) -> None:
        """Restore the nominal steady state at time 0 and seed all random generators."""

    def step(self) -> None:
        """Advance the simulation by ``scenario.dt_s``."""

    def read(self, tag_id: str) -> tuple[float, int]:
        """Return ``(value, quality)``; raise ``KeyError`` for unknown tags."""

    def write(self, tag_id: str, value: float) -> None:
        """Write a tag; ``KeyError`` for unknown tags, ``PermissionError`` if not writable now."""

    def snapshot(self) -> dict[str, tuple[float, int]]:
        """Return ``{tag_id: (value, quality)}`` for every tag."""
