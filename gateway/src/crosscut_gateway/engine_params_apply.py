"""Apply sequence of a PID parameter set (ADR 014 section 4); no state, no audit.

Live pre-checks (loop mode, from values, policy), the writes in de-tuning order with read-back
after each, and the revert of what was already written. Out-of-range values are refused, never
clamped. Units: values and tolerances in the unit of the parameter.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any, TypeVar

from crosscut_gateway.interfaces import ParamControlSystem, ParamItem, ParamPolicy
from crosscut_gateway.policy import check_param_items

COMM_ERRORS = (ConnectionError, OSError, TimeoutError)

_T = TypeVar("_T")

# Rank by (decreasing, unchanged, increasing) value: lower gain, longer Ti and shorter Td
# detune the loop, so they are written first; raising gain or shortening Ti goes last.
_RANKS: dict[str, tuple[int, int, int]] = {
    "gain": (0, 3, 6),
    "ti": (5, 3, 1),
    "td": (2, 3, 4),
    "tf": (3, 3, 3),
}
_NEUTRAL_RANK = (3, 3, 3)


class ParamCommError(Exception):
    """A transport error while talking to the control system about ``target``."""

    def __init__(self, target: str) -> None:
        """Remember the target whose access failed."""
        super().__init__(target)
        self.target = target


@dataclass(frozen=True)
class LiveCheck:
    """Result of the live pre-checks: refusal codes (empty = pass) and a short detail text."""

    codes: tuple[str, ...] = ()
    detail: str = ""
    current: Mapping[str, float] = field(default_factory=dict)  # values read, by target


@dataclass(frozen=True)
class WriteOutcome:
    """Result of writing a set: ``code`` is ``applied`` or the failure that stopped it.

    ``written`` lists the targets that were (possibly) written before a failure and
    ``revert_failed`` those among them that could not be restored.
    """

    ok: bool
    code: str
    failed_target: str = ""
    written: tuple[str, ...] = ()
    revert_failed: tuple[str, ...] = ()
    read_back: Mapping[str, float] = field(default_factory=dict)  # value read after each write


@dataclass
class _Progress:
    """What a write sequence has done so far: items written and values read back."""

    done: list[ParamItem] = field(default_factory=list)
    reads: dict[str, float] = field(default_factory=dict)


def detune_rank(item: ParamItem) -> int:
    """Write rank of an item; lower ranks are written first (de-tuning before tuning up)."""
    sign = (item.to_value > item.from_value) - (item.to_value < item.from_value)
    return _RANKS.get(item.param, _NEUTRAL_RANK)[sign + 1]


def detune_order(items: Sequence[ParamItem]) -> list[ParamItem]:
    """Items in the fixed write order: lower gain, longer Ti, shorter Td, Tf, longer Td,
    shorter Ti, higher gain. Items of equal rank keep their given order."""
    return sorted(items, key=detune_rank)


def within(actual: object, expected: float, tolerance: float) -> bool:
    """True when ``actual`` is a finite number within ``tolerance`` of ``expected``."""
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return False
    return bool(math.isfinite(actual) and abs(actual - expected) <= tolerance)


def stored_value(plant: ParamControlSystem, tag: str, value: float) -> float:
    """The value a read-back should show after writing ``value`` to ``tag``.

    A parameter node of data type Float holds a float32, so the plant returns the written
    value rounded to float32; the plant may say so with an optional ``param_data_type(tag)``
    method returning ``"Float"`` or ``"Double"``. Without it, or for Double, ``value`` is exact.
    """
    probe: Any = getattr(plant, "param_data_type", None)
    if not callable(probe) or probe(tag) != "Float":
        return value
    try:
        return float(struct.unpack("f", struct.pack("f", value))[0])
    except (OverflowError, struct.error):
        return value


def _guard(target: str, call: Callable[[], _T]) -> _T:
    """Run a plant call; a transport error becomes ParamCommError for ``target``."""
    try:
        return call()
    except COMM_ERRORS as exc:
        raise ParamCommError(target) from exc


def _mode_refusal(
    plant: ParamControlSystem, policies: Mapping[str, ParamPolicy], items: Sequence[ParamItem]
) -> LiveCheck | None:
    """Refuse when the loop mode of any item is outside its ``allowed_loop_modes``."""
    for item in items:
        policy = policies[item.target]
        mode = _guard(item.target, partial(plant.loop_mode, item.target))
        if mode not in policy.allowed_loop_modes:
            return LiveCheck(("mode_not_allowed",), f"{item.target}={mode}")
    return None


def _read_all(plant: ParamControlSystem, items: Sequence[ParamItem]) -> dict[str, float]:
    """Read every item's current value."""
    return {
        item.target: _guard(item.target, partial(plant.read_param, item.target))
        for item in items
    }


def _mismatch(
    plant: ParamControlSystem,
    policies: Mapping[str, ParamPolicy],
    items: Sequence[ParamItem],
    current: Mapping[str, float],
) -> LiveCheck | None:
    """Refuse when a live value differs from the item's ``from`` by more than the tolerance."""
    for item in items:
        tolerance = policies[item.target].readback_tolerance
        expected = stored_value(plant, item.target, item.from_value)
        if not within(current[item.target], expected, tolerance):
            read = ";".join(f"{tag}={value}" for tag, value in current.items())
            return LiveCheck(("from_mismatch",), f"read {read}")
    return None


def live_check(
    plant: ParamControlSystem,
    policies: Mapping[str, ParamPolicy],
    items: Sequence[ParamItem],
    *,
    exempt_ratio: bool = False,
) -> LiveCheck:
    """Loop mode, from values and policy checks against the live control system; no writes.

    Raises ParamCommError on a transport error.
    """
    if not items or any(item.target not in policies for item in items):
        return LiveCheck(tuple(check_param_items(policies, items, {}, exempt_ratio=exempt_ratio)))
    refusal = _mode_refusal(plant, policies, items)
    if refusal is not None:
        return refusal
    current = _read_all(plant, items)
    refusal = _mismatch(plant, policies, items, current)
    if refusal is not None:
        return refusal
    return LiveCheck(
        tuple(check_param_items(policies, items, current, exempt_ratio=exempt_ratio)),
        "",
        current,
    )


def _revert_one(plant: ParamControlSystem, policy: ParamPolicy, item: ParamItem) -> bool:
    """Write the ``from`` value back and confirm it by read-back; False on any failure."""
    try:
        if not plant.write_param(item.target, item.from_value):
            return False
        read = plant.read_param(item.target)
    except Exception:  # noqa: BLE001 - after a write any failure must count as "not restored"
        return False
    expected = stored_value(plant, item.target, item.from_value)
    return within(read, expected, policy.readback_tolerance)


def _revert(
    plant: ParamControlSystem,
    policies: Mapping[str, ParamPolicy],
    done: Sequence[ParamItem],
    failure: tuple[str, str],
) -> WriteOutcome:
    """Restore the ``from`` values of ``done`` (newest first); report which could not be."""
    failed = tuple(
        item.target
        for item in reversed(done)
        if not _revert_one(plant, policies[item.target], item)
    )
    code, target = failure
    return WriteOutcome(False, code, target, tuple(i.target for i in done), failed)


def revert_items(
    plant: ParamControlSystem, policies: Mapping[str, ParamPolicy], items: Sequence[ParamItem]
) -> tuple[str, ...]:
    """Best-effort restore of the ``from`` values of ``items`` after an unexpected error.

    Returns the targets that could not be confirmed restored (all of them if the policies fail).
    """
    try:
        return _revert(plant, policies, items, ("plant_error", "")).revert_failed
    except Exception:  # noqa: BLE001 - whatever fails here, nothing is confirmed restored
        return tuple(item.target for item in items)


def _write_one(
    plant: ParamControlSystem, policy: ParamPolicy, item: ParamItem, progress: _Progress
) -> str | None:
    """Write one item and read it back; the failure code, or None. The item joins ``done``
    before the call (a failed call may still have written it) and leaves it when refused."""
    progress.done.append(item)
    try:
        if not plant.write_param(item.target, item.to_value):
            progress.done.pop()
            return "write_refused"
        read = plant.read_param(item.target)
    except Exception:  # noqa: BLE001 - a half-done write set must be reverted, whatever failed
        return "comm_loss"
    if isinstance(read, (int, float)) and not isinstance(read, bool):
        progress.reads[item.target] = float(read)
    expected = stored_value(plant, item.target, item.to_value)
    if within(read, expected, policy.readback_tolerance):
        return None
    return "readback_mismatch"


def write_set(
    plant: ParamControlSystem, policies: Mapping[str, ParamPolicy], items: Sequence[ParamItem]
) -> WriteOutcome:
    """Write all items in de-tuning order with read-back after each.

    On a refused write, a read-back mismatch or a transport error the items written so far are
    restored to their ``from`` values. On success ``read_back`` holds the value read per target.
    """
    progress = _Progress()
    for item in detune_order(items):
        code = _write_one(plant, policies[item.target], item, progress)
        if code is not None:
            return _revert(plant, policies, progress.done, (code, item.target))
    written = tuple(item.target for item in progress.done)
    return WriteOutcome(True, "applied", "", written, (), progress.reads)
