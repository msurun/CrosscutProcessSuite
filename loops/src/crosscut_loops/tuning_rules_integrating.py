"""SIMC PI tuning for integrating (level) processes with dead time.

Model: PV rate = slope * OUT(t - theta), slope in PV units per second per % OUT.
Reuses ``PiSettings`` and the robustness map from ``tuning_rules``.
"""

from __future__ import annotations

import math

from crosscut_loops.tuning_rules import (
    FopdtModel,
    PiSettings,
    lambda_from_robustness,
)

# Skogestad (2003) integral time factor: Ti = 4 * (tau_c + theta).
_INTEGRAL_FACTOR = 4.0


def _require_finite(name: str, value: float) -> None:
    """Raise ValueError if ``value`` is NaN or infinite."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _validate_slope_delay(slope_per_s: float, delay_s: float) -> None:
    """Raise ValueError unless the slope is finite and non-zero and the delay positive."""
    _require_finite("Slope", slope_per_s)
    _require_finite("Dead time", delay_s)
    if slope_per_s == 0.0:
        raise ValueError("Slope must not be zero")
    if delay_s <= 0.0:
        raise ValueError("Dead time must be positive")


def simc_pi_integrating(slope_per_s: float, delay_s: float, tau_c_s: float) -> PiSettings:
    """SIMC PI settings for an integrating process with dead time.

    Kc = 1 / (|slope| * (tau_c + theta)),  Ti = 4 * (tau_c + theta)

    This is the limit of the SIMC FOPDT rule for a lag tending to infinity
    (Skogestad 2003, J. Process Control 13:291). It gives noticeable setpoint
    overshoot, which is normal for this rule.

    Sign convention: ``PiSettings`` (like the FOPDT rule, whose model needs a
    positive gain, and the vendor forms, which forbid a negative Gain) holds
    positive values only. Kc is therefore returned as a magnitude and the sign
    of the slope is not folded in. The caller must set the controller action
    from the sign of ``slope_per_s`` (reverse/direct action, see
    ``vendor_forms``); a negative slope means the opposite action.

    Args:
        slope_per_s: Process slope (PV units per second per % OUT), non-zero.
        delay_s: Dead time theta in seconds, positive.
        tau_c_s: Closed-loop time constant in seconds, not negative.

    Raises:
        ValueError: on non-finite input, zero slope, non-positive delay or negative tau_c.
    """
    _validate_slope_delay(slope_per_s, delay_s)
    _require_finite("tau_c", tau_c_s)
    if tau_c_s < 0.0:
        raise ValueError("Tuning constant tau_c must not be negative")
    total_s = tau_c_s + delay_s
    return PiSettings(kc=1.0 / (abs(slope_per_s) * total_s), ti_s=_INTEGRAL_FACTOR * total_s)


def tau_c_for_max_swing(
    slope_per_s: float, delay_s: float, load_step_pct: float, max_swing_pv: float
) -> float:
    """Closed-loop time constant that keeps a load step within a PV swing limit.

    Averaging-level design: after a load step of ``load_step_pct`` (% OUT) the
    controller must absorb it with a PV swing of at most ``max_swing_pv``.
    The swing is roughly load / Kc, so Kc_min = load_step_pct / max_swing_pv.
    With Kc = 1 / (|slope| * (tau_c + theta)) this gives
    tau_c = 1 / (|slope| * Kc_min) - theta, floored at theta (the fast end of
    the robustness slider; never below the dead time).

    Args:
        slope_per_s: Process slope, non-zero.
        delay_s: Dead time in seconds, positive.
        load_step_pct: Expected load step in % OUT, positive.
        max_swing_pv: Largest tolerated PV swing in PV units, positive.

    Raises:
        ValueError: on invalid inputs.
    """
    _validate_slope_delay(slope_per_s, delay_s)
    for name, value in (("Load step", load_step_pct), ("Max swing", max_swing_pv)):
        _require_finite(name, value)
        if value <= 0.0:
            raise ValueError(f"{name} must be positive")
    kc_min = load_step_pct / max_swing_pv
    return max(delay_s, 1.0 / (abs(slope_per_s) * kc_min) - delay_s)


def lambda_from_robustness_integrating(delay_s: float, robustness: float) -> float:
    """Map robustness [0, 1] to tau_c (delay to 5 * delay), as for FOPDT.

    Delegates to ``lambda_from_robustness`` so the mapping exists once.

    Raises:
        ValueError: if the delay is not positive and finite or robustness is outside [0, 1].
    """
    _require_finite("Dead time", delay_s)
    return lambda_from_robustness(FopdtModel(1.0, 1.0, delay_s), robustness)
