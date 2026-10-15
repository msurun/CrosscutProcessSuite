"""PID (derivative) settings for first-order-plus-dead-time (FOPDT) process models.

This module extends the PI rules in :mod:`crosscut_loops.tuning_rules` with the
AMIGO PID rule, the improved SIMC PI rule and the derivative advice of Astrom and
Hagglund. It also converts between the ideal (ISA) and series PID forms and reports
the high-frequency gain at which measurement noise is amplified.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from crosscut_loops.tuning_rules import FopdtModel, PiSettings, simc_pi_with_lag

# Default derivative filter ratio N (Tf = Td / N) used by Skogestad and Grimholt
# in the SIMC chapter; typical range 8-20.
_DEFAULT_FILTER_RATIO_N = 10.0

# AMIGO PID constants from Astrom and Hagglund (2006), eq. 7.7.
_AMIGO_PID_KC_CONSTANT = 0.2
_AMIGO_PID_KC_RATIO = 0.45
_AMIGO_PID_TI_LINEAR = 0.4
_AMIGO_PID_TI_LAG = 0.8
_AMIGO_PID_TI_DELAY = 0.1
_AMIGO_PID_TD_NUMERATOR = 0.5
_AMIGO_PID_TD_DELAY = 0.3

# Threshold on the normalized dead time above which our heuristic says the
# benefit of derivative action is marginal. Astrom and Hagglund (2006) section
# 7.4 report about a doubling of the integral gain at a normalized dead time of
# 0.5; choosing 0.5 as the cutoff is OUR heuristic, not a rule from the paper.
_DERIVATIVE_MAX_NORMALIZED_DEAD_TIME = 0.5
# OUR heuristic: noise peaks (3 sd) moving the output by more than this share of its range
# wear the valve, so derivative action is not worth it.
_NOISE_PEAK_SD = 3.0
_MAX_NOISE_OUTPUT_FRACTION = 0.05

# The ideal-to-series conversion needs Ti >= 4 Td so the square root below stays
# real (SIMC chapter, eq. 30).
_MIN_INTEGRAL_TO_DERIVATIVE_RATIO = 4.0

# Improved SIMC adds one third of the delay to the lag (Skogestad and Grimholt 2012, eq. 38).
_IMPROVED_SIMC_DELAY_SHARE = 3.0


@dataclass(frozen=True)
class PidSettings:
    """PID controller settings in ideal (ISA) form.

    Ideal form: u = Kc (e + (1/Ti) integral e dt + Td d(pv)/dt / (Tf s + 1)).
    The derivative acts on the MEASUREMENT (pv), not the setpoint (sp), so a
    setpoint step does not produce a derivative kick on the valve.

    Attributes:
        kc: Controller gain (dimensionless, output units per error unit).
        ti_s: Integral time in seconds.
        td_s: Derivative time in seconds; 0 disables the derivative term.
        filter_ratio_n: Derivative filter ratio N (dimensionless); the filter
            time constant is Tf = td_s / filter_ratio_n.
    """

    kc: float
    ti_s: float
    td_s: float
    filter_ratio_n: float = _DEFAULT_FILTER_RATIO_N

    def __post_init__(self) -> None:
        """Validate that the settings are physically meaningful."""
        if self.kc <= 0.0:
            raise ValueError("Controller gain must be positive")
        if self.ti_s <= 0.0:
            raise ValueError("Integral time must be positive")
        if self.td_s < 0.0:
            raise ValueError("Derivative time must not be negative")
        if self.filter_ratio_n <= 0.0:
            raise ValueError("Derivative filter ratio must be positive")

    @property
    def filter_time_s(self) -> float:
        """Return the derivative filter time constant Tf = td_s / filter_ratio_n in seconds."""
        return self.td_s / self.filter_ratio_n


def amigo_pid(model: FopdtModel) -> PidSettings:
    """Compute PID settings using the AMIGO rule.

    AMIGO (Astrom and Hagglund, Advanced PID Control, 2006, eq. 7.7): a
    design rule for an FOPDT model, meaning a gain K, a time constant T and
    a pure transport delay L, all read from `model`.

    Args:
        model: FOPDT process model (K = gain, T = time_constant_s, L = delay_s).

    Returns:
        PidSettings in ideal (ISA) form; times are in seconds.
    """
    gain = model.gain
    time_constant_s = model.time_constant_s
    delay_s = model.delay_s

    # Kc = (1/K) (0.2 + 0.45 T/L): the 1/K makes the loop gain independent of the
    # process unit scale, while T/L penalizes processes that are fast to delay.
    kc = (_AMIGO_PID_KC_CONSTANT + _AMIGO_PID_KC_RATIO * time_constant_s / delay_s) / gain

    # Ti = L (0.4 L + 0.8 T) / (L + 0.1 T): a reset time that follows the delay
    # for delay-dominated processes and grows with T for lag-dominated ones.
    ti_s = (
        delay_s
        * (_AMIGO_PID_TI_LINEAR * delay_s + _AMIGO_PID_TI_LAG * time_constant_s)
        / (delay_s + _AMIGO_PID_TI_DELAY * time_constant_s)
    )

    # Td = 0.5 L T / (0.3 L + T): derivative time, capped by the delay so the
    # derivative does not outrun the information the sensor can deliver.
    td_s = (
        _AMIGO_PID_TD_NUMERATOR * delay_s * time_constant_s
        / (_AMIGO_PID_TD_DELAY * delay_s + time_constant_s)
    )

    return PidSettings(kc=kc, ti_s=ti_s, td_s=td_s)


def simc_pi_improved(model: FopdtModel, tau_c_s: float) -> PiSettings:
    """Compute PI settings using the improved SIMC rule (Skogestad and Grimholt, 2012).

    The improved rule (eqs. 38-39) replaces the time constant T of the original SIMC rule by
    T + L/3. For a pure delay process (T = 0) the original rule is a pure I controller; the
    optimal PI has an integral time of about L/3, which is what the extra L/3 produces.

    Args:
        model: FOPDT process model (K = gain, T = time_constant_s, L = delay_s).
        tau_c_s: Desired closed-loop time constant in seconds; smaller is faster.

    Returns:
        PiSettings with controller gain and integral time in seconds.

    Raises:
        ValueError: If tau_c_s is not positive.
    """
    effective_lag_s = model.time_constant_s + model.delay_s / _IMPROVED_SIMC_DELAY_SHARE
    return simc_pi_with_lag(model, effective_lag_s, tau_c_s)


def normalized_dead_time(model: FopdtModel) -> float:
    """Return the normalized dead time L / (L + T).

    The normalized dead time measures how hard a process is to control: 0 means
    lag dominated (easy), values near 1 mean pure delay (hard). It is the
    dimension the derivative-advice decision below is expressed in.

    Args:
        model: FOPDT process model (T = time_constant_s, L = delay_s).

    Returns:
        A number strictly between 0 and 1 (dimensionless).
    """
    delay_s = model.delay_s
    return delay_s / (delay_s + model.time_constant_s)


def derivative_advice(model: FopdtModel) -> tuple[bool, str]:
    """Say whether derivative action is worth enabling, with a one-sentence reason.

    Args:
        model: FOPDT process model (T = time_constant_s, L = delay_s).

    Returns:
        A ``(use_derivative, reason)`` pair. The reason names the normalized dead
        time so the operator can judge the recommendation.
    """
    tau_normalized = normalized_dead_time(model)

    # Astrom and Hagglund (2006) section 7.4: the gain from derivative action is
    # marginal for delay-dominated processes and reaches about a doubling of the
    # integral gain at a normalized dead time of 0.5. Using 0.5 as the cutoff is
    # OUR heuristic, not a rule stated in the book.
    if tau_normalized <= _DERIVATIVE_MAX_NORMALIZED_DEAD_TIME:
        reason = (
            f"Lag-dominated process (normalized dead time {tau_normalized:.2f} <= "
            f"{_DERIVATIVE_MAX_NORMALIZED_DEAD_TIME}): derivative action roughly doubles "
            "the integral gain (exp06: load-step IAE at most 0.43 of the PI), but it raises the "
            "high-frequency gain to Kc(1+N); enable it only if the PV noise is small or filtered."
        )
        return True, reason

    reason = (
        f"Delay-dominated process (normalized dead time {tau_normalized:.2f} > "
        f"{_DERIVATIVE_MAX_NORMALIZED_DEAD_TIME}): Astrom and Hagglund (2006) section 7.4 "
        "find derivative action of marginal benefit here (exp06: still 30 % better IAE at 0.7, "
        "6 % at 0.9) while it amplifies PV noise; leave it off unless a faster response is needed."
    )
    return False, reason


def series_to_ideal(kc: float, ti_s: float, td_s: float) -> PidSettings:
    """Convert series PID settings to the ideal (ISA) form (SIMC chapter, eq. 30).

    The series form is what many PLCs implement: one gain with the terms
    chained; the ideal form is u = Kc (e + (1/Ti) integral e + Td de/dt). The
    SIMC chapter relates the two by the factor f = 1 + Td/Ti.

    Args:
        kc: Series controller gain (dimensionless).
        ti_s: Series integral time in seconds.
        td_s: Series derivative time in seconds; 0 makes this the identity.

    Returns:
        PidSettings in ideal form (the filter ratio keeps its default).

    Raises:
        ValueError: If the series settings are not positive.
    """
    if kc <= 0.0:
        raise ValueError("Controller gain must be positive")
    if ti_s <= 0.0:
        raise ValueError("Integral time must be positive")

    factor = 1.0 + td_s / ti_s
    # Multiplying Kc and Ti by f (and dividing Td by f) preserves the loop shape
    # while moving the same controller into the ideal parameterization.
    return PidSettings(kc=kc * factor, ti_s=ti_s * factor, td_s=td_s / factor)


def ideal_to_series(settings: PidSettings) -> tuple[float, float, float]:
    """Convert ideal (ISA) PID settings to the series form; inverse of series_to_ideal.

    For settings with td_s = 0 the conversion is the identity, because f = 1 and
    ideal = series. A series controller can only match an ideal one when
    Ti >= 4 Td: below that ratio the two zeros become complex and no series form
    exists.

    Args:
        settings: Ideal-form PID settings.

    Returns:
        A ``(kc, ti_s, td_s)`` tuple in series form; times are in seconds.

    Raises:
        ValueError: If Ti < 4 Td, so the series form cannot represent the settings.
    """
    if settings.ti_s < _MIN_INTEGRAL_TO_DERIVATIVE_RATIO * settings.td_s:
        raise ValueError("series form needs Ti >= 4 Td")

    # f = (1 + sqrt(1 - 4 Td/Ti)) / 2 picks the root that keeps the conversion
    # close to the ideal settings; the square root is real thanks to the check above.
    factor = (
        1.0 + sqrt(1.0 - _MIN_INTEGRAL_TO_DERIVATIVE_RATIO * settings.td_s / settings.ti_s)
    ) / 2.0

    # factor = 1 / (1 + Td_series / Ti_series), so the series gain and integral time are the
    # ideal ones multiplied by it and the series derivative time is divided by it.
    return settings.kc * factor, settings.ti_s * factor, settings.td_s / factor


def high_frequency_gain(settings: PidSettings) -> float:
    """Return the controller gain seen by a fast measurement-noise signal.

    The derivative is filtered, so above the filter corner the term saturates at
    Kc * (1 + N) (Astrom and Hagglund, 2006). This is the factor by which
    high-frequency noise on the measurement is turned into movement of the valve:
    a large value means sensor noise is being amplified into the actuator.

    Args:
        settings: PID settings in ideal form.

    Returns:
        The high-frequency gain (dimensionless).
    """
    return settings.kc * (1.0 + settings.filter_ratio_n)


def noise_checked_advice(
    advice: tuple[bool, str], settings: PidSettings, pv_noise_sd: float, out_span: float
) -> tuple[bool, str]:
    """Withdraw a "use derivative" advice when PV noise would shake the output too much.

    The noise reaches the output multiplied by the high-frequency gain Kc(1+N), so its
    3-sd peak on the output is 3 * Kc(1+N) * sd. A peak above
    ``_MAX_NOISE_OUTPUT_FRACTION`` of the output range turns the advice into "do not use".
    Advice that already says "do not use" is returned unchanged.

    Args:
        advice: ``(use_derivative, reason)`` from ``derivative_advice``.
        settings: PID settings in ideal form.
        pv_noise_sd: Standard deviation of the PV noise, in PV units.
        out_span: Span of the output, in output units.

    Returns:
        The advice, possibly turned off with a reason that quotes the numbers.
    """
    if not advice[0] or out_span <= 0.0:
        return advice
    peak = _NOISE_PEAK_SD * high_frequency_gain(settings) * pv_noise_sd
    fraction = peak / out_span
    if fraction <= _MAX_NOISE_OUTPUT_FRACTION:
        return advice
    reason = (
        f"PV noise too high for derivative action: its 3-sd peak would move the output by "
        f"{fraction:.0%} of the range (limit {_MAX_NOISE_OUTPUT_FRACTION:.0%}); filter the "
        "PV or keep the controller PI."
    )
    return False, reason
