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
        gain: Process gain K in PV units per unit of controller output (steady-state change
            of the PV divided by the change of the output).
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
        kc: Controller gain in output units per PV unit (error) unit.
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


# The SIMC rule caps the integral time at four times (tau_c + dead time), so a lag-dominant
# process (large time constant) does not get an integral action that is far too slow.
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

    SIMC = "Simple (Skogestad) Internal Model Control". The rule gives a controller gain `kc`
    and integral time `ti_s` that make the closed loop follow the setpoint like a first-order
    lag with the chosen time constant `tau_c_s`, after the process dead time that no controller
    can remove. A smaller `tau_c_s` means a faster, more aggressive controller.

    Args:
        model: FOPDT process model. FOPDT = "First-Order Plus Dead Time": the process
            reacts like a first-order lag of `time_constant_s` followed by a pure
            transport delay of `delay_s`.
        tau_c_s: Desired closed-loop time constant in seconds. This is the tuning knob: after
            the dead time, the closed loop covers about 63 % of a setpoint step in `tau_c_s`.

    Returns:
        PiSettings with controller gain `kc` (output units per error unit)
        and integral time `ti_s` in seconds.

    Raises:
        ValueError: if `tau_c_s` is not a valid closed-loop time constant.
    """
    return simc_pi_with_lag(model, model.time_constant_s, tau_c_s)


def simc_pi_with_lag(model: FopdtModel, lag_s: float, tau_c_s: float) -> PiSettings:
    """SIMC PI settings for an explicit effective lag.

    The original rule uses the process time constant T as the lag; the improved rule of Skogestad
    and Grimholt (2012) uses T + L/3 (see ``tuning_pid.simc_pi_improved``). Both share the same
    formulas, so they share this function:

        Kc = lag / (K * (tau_c + L)),    Ti = min(lag, 4 * (tau_c + L))

    Args:
        model: FOPDT process model (gain K, delay L are used; the lag comes from ``lag_s``).
        lag_s: Effective lag in seconds, positive.
        tau_c_s: Desired closed-loop time constant in seconds, positive.

    Raises:
        ValueError: if ``tau_c_s`` is not positive.
    """
    _validate_tau_c(tau_c_s)

    # Denominator of the IMC formula: the total effective lag the controller must cover.
    # It is the closed-loop time constant we ask for, plus the dead time the process already
    # adds, in seconds. Dead time cannot be cancelled, so it is added rather than tuned away.
    total_lag_s = tau_c_s + model.delay_s

    # SIMC gain rule for a FOPDT model: kc = lag / (K * (tau_c + theta)), where K = process
    # gain and theta = dead time (s). It follows from an IMC design in which the dead time is
    # approximated by a first-order term (Skogestad 2003); `lag_s` is the process time constant.
    kc = lag_s / (model.gain * total_lag_s)

    # SIMC integral-time rule: ti = min(lag, 4 * (tau_c + theta)). The cap at
    # `_SIMC_INTEGRAL_CAP_FACTOR` times the total lag only acts on lag-dominant processes
    # (lag much larger than tau_c + theta): there it speeds the integral action up so that
    # load disturbances are removed in reasonable time.
    ti_s = min(lag_s, _SIMC_INTEGRAL_CAP_FACTOR * total_lag_s)

    return PiSettings(kc=kc, ti_s=ti_s)


def lambda_from_robustness(model: FopdtModel, robustness: float) -> float:
    """Map a robustness level [0, 1] to a SIMC tuning constant tau_c.

    SIMC (Simple/Skogestad Internal Model Control) tunes a controller by picking a closed-loop
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
    # Dead time of the process, in seconds. tau_c is scaled from it: the SIMC default
    # tau_c = delay is the fast end (robustness 0) of this slider.
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
    # `gain` is the steady-state gain (PV units per unit of controller output),
    # `time_constant_s` is how slowly the output reacts (seconds), and `delay_s` is the
    # dead time before the output starts moving (seconds). AMIGO uses them to pick a PI
    # controller that stays stable without being sluggish.
    gain = model.gain
    time_constant_s = model.time_constant_s
    delay_s = model.delay_s

    # AMIGO PI rule, Astrom and Hagglund (2006), chapter 7 (coefficients still to verify against
    # the book, see docs/PROVENANCE.md). With K = gain, T = time constant, L = dead time:
    #     Kc = (0.15 + 0.35 * T / L - T**2 / (L + T)**2) / K
    # written below as 0.15 / K + (0.35 - L * T / (L + T)**2) * T / (K * L), which is the same
    # expression. `kc` is in controller-output units per PV unit (1 / K scaled by a number).
    kc = 0.15 / gain + (0.35 - delay_s * time_constant_s / (delay_s + time_constant_s) ** 2) * (
        time_constant_s / (gain * delay_s)
    )
    # `ti_s` is the integral (reset) time in seconds: the time in which the integral action
    # repeats the proportional action for a constant error. Its formula is in a helper.
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

    The same PI controller is written differently by different vendors: the gain `kc` or
    the proportional band 100 / kc (in %, which assumes `kc` is on a percent-of-span basis), and
    the integral time in seconds or minutes, or as repeats per minute (60 / ti_s). This
    function picks the converter that turns the settings into the chosen form.

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
