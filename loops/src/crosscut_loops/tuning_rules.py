"""PI tuning rules for first-order-plus-dead-time (FOPDT) process models.

This module implements two classic tuning rules:

* SIMC (Skogestad, 2003) - "Simple analytic rules for model reduction and
  PID controller tuning", J. Process Control, 13(4), 291-309.
* AMIGO (Astrom and Hagglund, 2006) - "Advanced PID Control",
  ISA - The Instrumentation, Systems, and Automation Society.

It also provides conversion helpers that map the resulting PI settings
into the parameter forms used by different vendor systems.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeAlias


@dataclass(frozen=True)
class FopdtModel:
    """A first-order-plus-dead-time (FOPDT) process model.

    Attributes:
        gain: Process gain (dimensionless).
        time_constant_s: First-order time constant in seconds.
        delay_s: Dead time in seconds.
    """

    gain: float
    time_constant_s: float
    delay_s: float

    def __post_init__(self) -> None:
        """Validate that all model parameters are positive."""
        if self.gain <= 0.0:
            raise ValueError("Process gain must be positive")
        if self.time_constant_s <= 0.0:
            raise ValueError("Time constant must be positive")
        if self.delay_s <= 0.0:
            raise ValueError("Dead time must be positive")


@dataclass(frozen=True)
class PiSettings:
    """PI controller settings.

    Attributes:
        kc: Controller gain (dimensionless).
        ti_s: Integral time in seconds.
    """

    kc: float
    ti_s: float

    def __post_init__(self) -> None:
        """Validate that both settings are positive."""
        if self.kc <= 0.0:
            raise ValueError("Controller gain must be positive")
        if self.ti_s <= 0.0:
            raise ValueError("Integral time must be positive")


# The SIMC rule caps the integral time at four times the total lag
# (dead time plus tuning constant) to avoid sluggish response.
_SIMC_INTEGRAL_CAP_FACTOR = 4.0

# The robustness slider maps [0, 1] to a tau_c range of [L, 5L].
_ROBUSTNESS_SPAN = 4.0

# Used to convert integral times from seconds to minutes or repeats per minute.
_SECONDS_PER_MINUTE = 60.0


def _validate_tau_c(tau_c_s: float) -> None:
    """Raise ValueError if tau_c is not positive."""
    if tau_c_s <= 0.0:
        raise ValueError("Tuning constant tau_c must be positive")


def _validate_robustness(robustness: float) -> None:
    """Raise ValueError if robustness is outside [0, 1]."""
    if not 0.0 <= robustness <= 1.0:
        raise ValueError("Robustness must be between 0 and 1")


def simc_pi(model: FopdtModel, tau_c_s: float) -> PiSettings:
    """Compute PI settings using the SIMC rule.

    Args:
        model: FOPDT process model.
        tau_c_s: Desired closed-loop time constant in seconds.

    Returns:
        PiSettings with controller gain and integral time.
    """
    _validate_tau_c(tau_c_s)
    time_constant_s = model.time_constant_s
    gain = model.gain
    total_lag_s = tau_c_s + model.delay_s

    kc = time_constant_s / (gain * total_lag_s)
    ti_s = min(time_constant_s, _SIMC_INTEGRAL_CAP_FACTOR * total_lag_s)
    return PiSettings(kc=kc, ti_s=ti_s)


def lambda_from_robustness(model: FopdtModel, robustness: float) -> float:
    """Map a robustness level [0, 1] to a SIMC tuning constant tau_c.

    The mapping is linear: 0 -> delay, 1 -> 5 * delay.

    Args:
        model: FOPDT process model.
        robustness: Desired robustness, between 0 (fast) and 1 (robust).

    Returns:
        tau_c in seconds.
    """
    _validate_robustness(robustness)
    delay_s = model.delay_s
    return delay_s * (1.0 + _ROBUSTNESS_SPAN * robustness)


def _amigo_integral_time_s(time_constant_s: float, delay_s: float) -> float:
    """Return the AMIGO integral time in seconds (Astrom and Hagglund, 2006)."""
    return 0.35 * delay_s + 13.0 * delay_s * time_constant_s**2 / (
        time_constant_s**2 + 12.0 * delay_s * time_constant_s + 7.0 * delay_s**2
    )


def amigo_pi(model: FopdtModel) -> PiSettings:
    """Compute PI settings using the AMIGO rule.

    Args:
        model: FOPDT process model.

    Returns:
        PiSettings with controller gain and integral time.
    """
    gain = model.gain
    time_constant_s = model.time_constant_s
    delay_s = model.delay_s

    # Constants from Astrom and Hagglund (2006), Table 7.2.
    kc = 0.15 / gain + (0.35 - delay_s * time_constant_s / (delay_s + time_constant_s) ** 2) * (
        time_constant_s / (gain * delay_s)
    )
    ti_s = _amigo_integral_time_s(time_constant_s, delay_s)
    return PiSettings(kc=kc, ti_s=ti_s)


ConversionForm: TypeAlias = Literal[
    "gain_seconds",
    "gain_minutes",
    "proportional_band_minutes",
    "gain_repeats_per_minute",
]

def _to_gain_seconds(settings: PiSettings) -> dict[str, float]:
    """Express the settings as {"gain", "integral_time_s"}."""
    return {"gain": settings.kc, "integral_time_s": settings.ti_s}


def _to_gain_minutes(settings: PiSettings) -> dict[str, float]:
    """Express the settings as {"gain", "integral_time_min"}."""
    return {"gain": settings.kc, "integral_time_min": settings.ti_s / _SECONDS_PER_MINUTE}


def _to_proportional_band_minutes(settings: PiSettings) -> dict[str, float]:
    """Express the settings as {"proportional_band_pct", "integral_time_min"}."""
    return {
        "proportional_band_pct": 100.0 / settings.kc,
        "integral_time_min": settings.ti_s / _SECONDS_PER_MINUTE,
    }


def _to_gain_repeats_per_minute(settings: PiSettings) -> dict[str, float]:
    """Express the settings as {"gain", "repeats_per_min"}."""
    return {"gain": settings.kc, "repeats_per_min": _SECONDS_PER_MINUTE / settings.ti_s}


_CONVERTERS: dict[ConversionForm, Callable[[PiSettings], dict[str, float]]] = {
    "gain_seconds": _to_gain_seconds,
    "gain_minutes": _to_gain_minutes,
    "proportional_band_minutes": _to_proportional_band_minutes,
    "gain_repeats_per_minute": _to_gain_repeats_per_minute,
}


def convert_pi(settings: PiSettings, form: ConversionForm) -> dict[str, float]:
    """Convert PI settings into a vendor-specific parameter form.

    Args:
        settings: PI settings to convert.
        form: Target parameter form.

    Returns:
        Dictionary of converted parameters; the keys depend on the form
        (see the individual ``_to_*`` converters).

    Raises:
        ValueError: If the requested form is not recognised.
    """
    converter = _CONVERTERS.get(form)
    if converter is None:
        raise ValueError(f"Unknown conversion form: {form}")
    return converter(settings)
