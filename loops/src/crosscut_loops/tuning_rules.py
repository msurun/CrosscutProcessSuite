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

    SIMC = "Skogestad Internal Model Control". The rule gives a controller gain `kc`
    and integral time `ti_s` that make the closed loop behave like a first-order lag
    with the chosen time constant `tau_c_s`. A smaller `tau_c_s` means a faster, more
    aggressive controller.

    Args:
        model: FOPDT process model. FOPDT = "First-Order Plus Dead Time": the process
            reacts like a first-order lag of `time_constant_s` followed by a pure
            transport delay of `delay_s`.
        tau_c_s: Desired closed-loop time constant in seconds. This is the tuning knob:
            the closed loop should reach its setpoint about `tau_c_s` seconds after a step.

    Returns:
        PiSettings with controller gain `kc` (dimensionless, output units per error unit)
        and integral time `ti_s` in seconds.

    Raises:
        ValueError: if `tau_c_s` is not a valid closed-loop time constant.
    """
    _validate_tau_c(tau_c_s)

    # `time_constant_s` is the process lag in seconds, `gain` is the process steady-state
    # gain (output units per input units). The two are pulled out of `model` so the formula
    # below reads like the textbook version, not like attribute lookups.
    time_constant_s = model.time_constant_s
    gain = model.gain

    # Denominator of the IMC formula: the total effective lag the controller must cover.
    # It is the closed-loop time constant we ask for, plus the dead time the process already
    # adds, in seconds. Dead time cannot be cancelled, so it is added rather than tuned away.
    total_lag_s = tau_c_s + model.delay_s

    # SIMC gain rule for a FOPDT model: kc = tau / (K * (tau_c + theta)), where
    # tau = process time constant (s), K = process gain, theta = dead time (s).
    # This is the standard IMC design for a first-order model, with the derivative term dropped.
    kc = time_constant_s / (gain * total_lag_s)

    # SIMC integral-time rule: ti = min(tau, 4 * (tau_c + theta)). The cap at
    # `_SIMC_INTEGRAL_CAP_FACTOR` times the total lag keeps the integral action from being
    # so slow on a lag-heavy process that it never removes steady-state offset.
    ti_s = min(time_constant_s, _SIMC_INTEGRAL_CAP_FACTOR * total_lag_s)

    return PiSettings(kc=kc, ti_s=ti_s)


def lambda_from_robustness(model: FopdtModel, robustness: float) -> float:
    """Map a robustness level [0, 1] to a SIMC tuning constant tau_c.

    SIMC (Skogestad Internal Model Control) tunes a PID by picking a closed-loop
    speed parameter tau_c: a smaller tau_c gives a faster but less robust loop.
    Here tau_c is expressed as a multiple of the process delay.

    The mapping is linear: 0 -> delay, 1 -> 5 * delay.

    Args:
        model: FOPDT process model. First-Order Plus Dead Time: a gain, a time
            constant and a transport delay.
        robustness: Desired robustness, between 0 (fast) and 1 (robust).

    Returns:
        tau_c in seconds.

    Raises:
        ValueError: If robustness is outside [0, 1].
    """
    _validate_robustness(robustness)
    # Dead time of the process, in seconds. tau_c is scaled from this because
    # SIMC's own rule of thumb picks tau_c proportional to the delay.
    delay_s = model.delay_s
    # Interpolate between the two endpoints of the mapping: robustness 0 gives
    # tau_c = delay (1.0 * delay) and robustness 1 gives tau_c = 5 * delay.
    # The term inside the brackets is the multiplier, spanning
    # 1.0 to 1.0 + _ROBUSTNESS_SPAN (that is, 5.0) as robustness goes 0 -> 1.
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
    # First-order plus dead time (FOPDT) model: the process is described by three numbers.
    # `gain` is the steady-state gain (output units per input unit, dimensionless ratio),
    # `time_constant_s` is how slowly the output reacts (seconds), and `delay_s` is the
    # dead time before the output starts moving (seconds). AMIGO uses them to pick a PI
    # controller that stays stable without being sluggish.
    gain = model.gain
    time_constant_s = model.time_constant_s
    delay_s = model.delay_s

    # Constants from Astrom and Hagglund (2006), Table 7.2.
    # `kc` is the proportional gain (input units per output unit, so it is 1/gain scaled
    # by the tuning rule). The rule has two parts: `0.15 / gain` is a fixed floor that
    # keeps the loop stable when the process is hard to control, and the second term
    # adds correction based on how the dead time compares to the time constant. The
    # fraction `delay_s * time_constant_s / (delay_s + time_constant_s)**2` is a
    # dimensionless shape factor: it peaks at 0.25 when delay equals time constant and
    # shrinks toward zero when either dominates, so the correction is largest for a
    # balanced process. `time_constant_s / (gain * delay_s)` converts that shape factor
    # back into gain units. Multiplying by the shape factor makes `kc` smaller (control
    # less aggressive) for processes with an unfavorable delay-to-time-constant ratio.
    kc = 0.15 / gain + (0.35 - delay_s * time_constant_s / (delay_s + time_constant_s) ** 2) * (
        time_constant_s / (gain * delay_s)
    )
    # `ti_s` is the integral (reset) time in seconds: how long the controller takes to
    # repeat the proportional action. The AMIGO formula for it is kept in a helper so the
    # logic and the caller stay readable.
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

    A PI controller is described by a proportional gain and an integral time
    (both in the controller's own engineering units); every PLC vendor instead
    expects the integral part as a gain with a different unit (usually a reset
    time in seconds or a gain per second). This function picks the converter
    that translates the vendor-neutral PI settings into the chosen form.

    Args:
        settings: PI settings to convert.
        form: Target parameter form.

    Returns:
        Dictionary of converted parameters; the keys depend on the form
        (see the individual ``_to_*`` converters).

    Raises:
        ValueError: If the requested form is not recognised.
    """
    # _CONVERTERS maps each accepted ConversionForm member to the function that
    # implements it. The lookup returns None (not a KeyError) when the form is
    # unknown, so the missing-entry case is handled by the explicit check below.
    converter = _CONVERTERS.get(form)
    if converter is None:
        raise ValueError(f"Unknown conversion form: {form}")
    return converter(settings)
