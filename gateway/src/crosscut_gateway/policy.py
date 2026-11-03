"""Stateless write policy validation and clamping for Write Gateway (Phase 2, #46).

Enforces engineering limits, step clamps, rate-of-change clamps, allowed loop modes,
and minimum write intervals on proposals before any control system setpoint is modified.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from crosscut_gateway.interfaces import WriteDecision, WritePolicy, WriteProposal


class PolicyError(ValueError):
    """Raised when a write policy document or target definition is invalid."""


def _parse_float(tag: str, field_name: str, val: Any) -> float:
    """Validate and convert val to a finite float; booleans are rejected."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        msg = f"Target '{tag}': {field_name} must be a number, got {type(val).__name__}"
        raise PolicyError(msg)
    f = float(val)
    if math.isnan(f) or math.isinf(f):
        raise PolicyError(f"Target '{tag}': {field_name} must be finite, got {f}")
    return f


def _parse_positive_float(tag: str, field_name: str, val: Any) -> float:
    """Validate that val is a strictly positive finite float (> 0)."""
    f = _parse_float(tag, field_name, val)
    if f <= 0:
        raise PolicyError(f"Target '{tag}': {field_name} must be > 0, got {f}")
    return f


def _parse_non_negative_float(tag: str, field_name: str, val: Any) -> float:
    """Validate that val is a non-negative finite float (>= 0)."""
    f = _parse_float(tag, field_name, val)
    if f < 0:
        raise PolicyError(f"Target '{tag}': {field_name} must be >= 0, got {f}")
    return f


def _parse_limits(tag: str, raw_limits: Any) -> tuple[float, float]:
    """Validate limits array [lo, hi] ensuring lo <= hi and both are numbers."""
    if isinstance(raw_limits, (str, bytes, dict)) or not isinstance(raw_limits, (list, tuple)):
        raise PolicyError(f"Target '{tag}': limits must be a list or tuple of 2 numbers")
    if len(raw_limits) != 2:
        msg = f"Target '{tag}': limits must have exactly 2 numbers, got {len(raw_limits)}"
        raise PolicyError(msg)
    lo = _parse_float(tag, "limits[0]", raw_limits[0])
    hi = _parse_float(tag, "limits[1]", raw_limits[1])
    if lo > hi:
        raise PolicyError(f"Target '{tag}': limits[0] ({lo}) > limits[1] ({hi})")
    return lo, hi


def _parse_allowed_modes(tag: str, raw_modes: Any) -> tuple[str, ...]:
    """Validate allowed_loop_modes is a non-empty sequence of non-empty strings."""
    if isinstance(raw_modes, (str, bytes, dict)) or not isinstance(raw_modes, (list, tuple)):
        raise PolicyError(f"Target '{tag}': allowed_loop_modes must be a sequence of strings")
    if len(raw_modes) == 0:
        raise PolicyError(f"Target '{tag}': allowed_loop_modes must not be empty")
    modes: list[str] = []
    for i, item in enumerate(raw_modes):
        if not isinstance(item, str) or len(item.strip()) == 0:
            raise PolicyError(f"Target '{tag}': allowed_loop_modes[{i}] must be a non-empty string")
        modes.append(item.strip())
    return tuple(modes)


def _parse_target(tag: str, raw: Any) -> WritePolicy:
    """Parse one target dictionary into a WritePolicy dataclass."""
    if not isinstance(raw, dict):
        raise PolicyError(f"Target '{tag}': must be a dictionary")
    for req in (
        "limits", "max_step", "max_rate_per_s", "min_interval_s",
        "allowed_loop_modes", "hold_off_s", "watchdog_s", "readback_tolerance",
    ):
        if req not in raw:
            raise PolicyError(f"Target '{tag}': missing required field '{req}'")
    return WritePolicy(
        limits=_parse_limits(tag, raw["limits"]),
        max_step=_parse_positive_float(tag, "max_step", raw["max_step"]),
        max_rate_per_s=_parse_positive_float(tag, "max_rate_per_s", raw["max_rate_per_s"]),
        min_interval_s=_parse_non_negative_float(tag, "min_interval_s", raw["min_interval_s"]),
        allowed_loop_modes=_parse_allowed_modes(tag, raw["allowed_loop_modes"]),
        hold_off_s=_parse_non_negative_float(tag, "hold_off_s", raw["hold_off_s"]),
        watchdog_s=_parse_positive_float(tag, "watchdog_s", raw["watchdog_s"]),
        readback_tolerance=_parse_non_negative_float(
            tag, "readback_tolerance", raw["readback_tolerance"]
        ),
    )


def policy_from_dict(data: dict[str, Any]) -> dict[str, WritePolicy]:
    """Convert a targets mapping or policy document into a mapping of WritePolicy objects.

    Units:
    - limits: engineering units
    - max_step: engineering units
    - max_rate_per_s: engineering units / second
    - min_interval_s: seconds
    - hold_off_s: seconds
    - watchdog_s: seconds
    - readback_tolerance: engineering units
    """
    if not isinstance(data, dict):
        raise PolicyError("Policy data must be a dictionary")
    has_targets = "targets" in data and isinstance(data["targets"], dict)
    raw_targets = data["targets"] if has_targets else data
    if not isinstance(raw_targets, dict):
        raise PolicyError("Targets must be a dictionary mapping tag names to policy dicts")
    parsed: dict[str, WritePolicy] = {}
    for tag, target_data in raw_targets.items():
        parsed[str(tag)] = _parse_target(str(tag), target_data)
    return parsed


def proposal_key(proposal: WriteProposal) -> str:
    """Stable SHA-256 hex over (target_tag, value, proposer, t_ns) for proposal idempotency.

    Units: value in engineering units, t_ns in nanoseconds. The reason string is excluded
    so identical proposals carrying different commentary produce the same key.
    """
    # In plain words: We serialize the core semantic fields of the proposal in a stable format
    # and compute its SHA-256 digest.
    val_repr = f"{float(proposal.value):.17g}"
    payload = f"{proposal.target_tag}\0{val_repr}\0{proposal.proposer}\0{int(proposal.t_ns)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _check_timing(
    policy: WritePolicy,
    t_ns: int,
    last_write_t_ns: int | None,
) -> WriteDecision | None:
    """Verify clock monotonic ordering and min_interval between consecutive writes."""
    if last_write_t_ns is None:
        return None
    if t_ns < last_write_t_ns:
        return WriteDecision(accepted=False, reason_code="clock_backwards")
    if (t_ns - last_write_t_ns) < policy.min_interval_s * 1e9:
        return WriteDecision(accepted=False, reason_code="min_interval")
    return None


def _clamp_step(target: float, last_value: float | None, max_step: float) -> float:
    """Clamp the step change relative to last_value to at most max_step."""
    if last_value is None:
        return target
    diff = target - last_value
    if diff > max_step:
        return last_value + max_step
    if diff < -max_step:
        return last_value - max_step
    return target


def _clamp_rate(
    target: float,
    last_value: float | None,
    dt_s: float | None,
    max_rate_per_s: float,
) -> float:
    """Clamp the rate of change relative to last_value to at most max_rate_per_s * dt_s."""
    if last_value is None or dt_s is None:
        return target
    max_change = max_rate_per_s * dt_s
    diff = target - last_value
    if diff > max_change:
        return last_value + max_change
    if diff < -max_change:
        return last_value - max_change
    return target


def _compute_clamped_value(
    policy: WritePolicy,
    proposal_value: float,
    last_value: float | None,
    dt_s: float | None,
) -> float:
    """Compute allowed setpoint value applying limits, step and rate clamps."""
    lo, hi = policy.limits
    # In plain words: First constrain the raw proposal to hard engineering limits.
    v_limit = min(max(proposal_value, lo), hi)
    # Then restrict the jump size from the current setpoint (step clamp).
    v_step = _clamp_step(v_limit, last_value, policy.max_step)
    # Then restrict the velocity of change over the elapsed time interval (rate clamp).
    v_rate = _clamp_rate(v_step, last_value, dt_s, policy.max_rate_per_s)
    # Ensure final value strictly satisfies engineering limits.
    return min(max(v_rate, lo), hi)


def _evaluate_clamping(
    policy: WritePolicy,
    proposal: WriteProposal,
    last_value: float | None,
    last_write_t_ns: int | None,
) -> WriteDecision:
    """Compute clamping and produce final acceptance decision and reason code."""
    dt_s = (proposal.t_ns - last_write_t_ns) / 1e9 if last_write_t_ns is not None else None
    clamped = _compute_clamped_value(policy, proposal.value, last_value, dt_s)
    if last_value is not None and clamped == last_value:
        return WriteDecision(accepted=False, reason_code="no_change")
    if clamped == proposal.value:
        return WriteDecision(accepted=True, reason_code="ok", clamped_value=None)
    return WriteDecision(accepted=True, reason_code="clamped", clamped_value=clamped)


def _last_value_invalid(policy: WritePolicy, last_value: float | None) -> bool:
    """Return True when a known last value is non-finite or outside policy limits."""
    if last_value is None:
        return False
    low, high = policy.limits
    return not math.isfinite(last_value) or last_value < low or last_value > high


def validate_proposal(
    policy: WritePolicy | None,
    proposal: WriteProposal,
    last_value: float | None,
    last_write_t_ns: int | None,
    loop_mode: str,
) -> WriteDecision:
    """Stateless evaluation of a write proposal against policy constraints.

    Evaluates rules in strict priority order (no_policy, bad_value, mode_not_allowed,
    last_value_out_of_limits, clock_backwards, min_interval, clamping).

    Units:
    - proposal.value, last_value: engineering units
    - proposal.t_ns, last_write_t_ns: nanoseconds (Unix epoch)
    - policy limits, max_step, readback_tolerance: engineering units
    - policy max_rate_per_s: engineering units / second
    - policy min_interval_s, hold_off_s, watchdog_s: seconds
    """
    if policy is None:
        return WriteDecision(accepted=False, reason_code="no_policy")
    if math.isnan(proposal.value) or math.isinf(proposal.value):
        return WriteDecision(accepted=False, reason_code="bad_value")
    if loop_mode not in policy.allowed_loop_modes:
        return WriteDecision(accepted=False, reason_code="mode_not_allowed")
    if _last_value_invalid(policy, last_value):
        return WriteDecision(accepted=False, reason_code="last_value_out_of_limits")
    timing_decision = _check_timing(policy, proposal.t_ns, last_write_t_ns)
    if timing_decision is not None:
        return timing_decision
    return _evaluate_clamping(policy, proposal, last_value, last_write_t_ns)
