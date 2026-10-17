"""
Valve model for G3 stiction generator.

Provides ideal and sticking valve implementations with optional first-order
actuator lag and optional quantisation. The valve state lives inside each
Valve object; `step(u)` advances the valve one sample.

Stiction models (case "stick"):
  - Choudhury two-parameter model (deadband S, slip J); S in 0.5-6 %, J in 0-0.7*S.
  - Kano simple-sticking-band model.
  - He one-parameter model.
All parameter values are percentages of valve travel (0-100).
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np

# Constants (percent of valve travel)
MIN_DEADBAND_PCT = 0.5  # lower bound for Choudhury S
MAX_DEADBAND_PCT = 6.0  # upper bound for Choudhury S
MAX_SLIP_RATIO = 0.7  # J <= 0.7 * S for Choudhury
IDEAL_QUANT_STEP_PCT = 0.05  # minimum quantisation step for ideal valve
MAX_QUANT_STEP_PCT = 0.5  # maximum quantisation step for ideal valve
MAX_ACTUATOR_TAU_S = 5.0  # maximum actuator time constant (samples)


class StictionModel(Enum):
    """Enumeration of the three stiction model families."""

    CHOUDHURY = "choudhury"
    KANO = "kano"
    HE = "he"


@dataclass
class Valve:
    """
    Base class for all valves.

    Attributes:
        model: string identifier of the valve model ("choudhury", "kano",
            "he", or "ideal").
        quant_step: quantisation step in percent (0 means no quantisation).
        actuator_tau: first-order actuator lag time constant in samples
            (0 means no lag).
    """

    model: str
    quant_step: float = 0.0
    actuator_tau: float = 0.0

    def step(self, u: float) -> float:
        """Advance the valve by one sample and return the position."""
        raise NotImplementedError


@dataclass
class IdealValve(Valve):
    """Valve with no nonlinearity, optional quantisation and optional lag."""

    _previous_output: float = 50.0

    def step(self, u: float) -> float:
        """Return the commanded position after optional quantisation and lag."""
        # Quantise the input
        if self.quant_step > 0:
            u = np.round(u / self.quant_step) * self.quant_step

        # First-order actuator lag
        if self.actuator_tau > 0 and self.actuator_tau < np.inf:
            alpha = 1.0 / (1.0 + self.actuator_tau)
            output = self._previous_output + alpha * (u - self._previous_output)
        else:
            output = u

        self._previous_output = output
        return float(output)


@dataclass
class ChoudhuryValve(Valve):
    """
    Choudhury two-parameter stiction model.

    Valve sticks until the input moves outside the deadband [u_prev - S/2,
    u_prev + S/2]; when it slips, it jumps by J (plus the input change).
    """

    deadband: float = 1.0  # S, in percent
    slip: float = 0.0  # J, in percent
    _u_last: float = 50.0
    _y_last: float = 50.0
    _prev_output: float = 50.0  # for actuator lag

    def step(self, u: float) -> float:
        """Update the sticking/slipping valve state and return the position."""
        if abs(u - self._u_last) > self.deadband / 2.0:
            # Slipping: move by slip plus leftover input change
            output = self._y_last + (u - self._u_last) + self.slip
            self._u_last = u
            self._y_last = output
        else:
            # Sticking: hold position
            output = self._y_last

        # Optional actuator lag
        if self.actuator_tau > 0 and self.actuator_tau < np.inf:
            alpha = 1.0 / (1.0 + self.actuator_tau)
            output = self._prev_output + alpha * (output - self._prev_output)
        self._prev_output = output

        return float(output)


@dataclass
class KanoValve(Valve):
    """
    Kano simple-sticking-band model.

    The valve sticks while the input remains within a fixed band around the
    last output. When the input exits the band, the valve moves to the input.
    The band is drawn from the Choudhury deadband range (0.5-6 %).
    """

    band: float = 1.0  # sticking band half-width, in percent
    _y_last: float = 50.0
    _prev_output: float = 50.0

    def step(self, u: float) -> float:
        """Update the sticking/slipping valve state and return the position."""
        if abs(u - self._y_last) > self.band:
            output = u
            self._y_last = output
        else:
            output = self._y_last

        # Optional actuator lag
        if self.actuator_tau > 0 and self.actuator_tau < np.inf:
            alpha = 1.0 / (1.0 + self.actuator_tau)
            output = self._prev_output + alpha * (output - self._prev_output)
        self._prev_output = output

        return float(output)


@dataclass
class HeValve(Valve):
    """
    He one-parameter stiction model.

    The valve sticks while the input remains within a band of width 2*d around
    the last output, where d is drawn from 0.5-6 % (one parameter). When the
    input exits the band, the valve moves to the input.
    """

    d: float = 1.0  # half deadband, in percent
    _y_last: float = 50.0
    _prev_output: float = 50.0

    def step(self, u: float) -> float:
        """Update the sticking/slipping valve state and return the position."""
        if abs(u - self._y_last) > self.d:
            output = u
            self._y_last = output
        else:
            output = self._y_last

        # Optional actuator lag
        if self.actuator_tau > 0 and self.actuator_tau < np.inf:
            alpha = 1.0 / (1.0 + self.actuator_tau)
            output = self._prev_output + alpha * (output - self._prev_output)
        self._prev_output = output

        return float(output)


def _draw_actuator_lag(rng: np.random.Generator) -> float:
    """Draw an actuator lag time constant (samples) or 0 for no lag."""
    # 50 % chance of no lag, else uniform 0.2-5.0 samples
    if rng.random() < 0.5:
        return 0.0
    return float(rng.uniform(0.2, MAX_ACTUATOR_TAU_S))


def _draw_quant_step(rng: np.random.Generator, tiny: bool = False) -> float:
    """
    Draw a quantisation step in percent.

    Args:
        tiny: if True, use the ideal-valve range (0.05-0.5 %);
              if False, use 0 (no quantisation) or the same range.
    """
    if tiny:
        return float(rng.uniform(IDEAL_QUANT_STEP_PCT, MAX_QUANT_STEP_PCT))
    # 50 % chance of no quantisation, else the same range
    if rng.random() < 0.5:
        return 0.0
    return float(rng.uniform(IDEAL_QUANT_STEP_PCT, MAX_QUANT_STEP_PCT))


def make_valve(rng: np.random.Generator, case: str) -> Valve:
    """
    Create a valve object for the given case.

    Args:
        rng: numpy random generator for reproducible parameter draws.
        case: "stick" for a stiction valve; any other string for an ideal
            valve (with optional tiny quantisation and optional lag).

    Returns:
        A Valve instance with a `step` method.
    """
    if case != "stick":
        # Ideal valve: optional tiny quantisation, optional actuator lag
        quant_step = _draw_quant_step(rng, tiny=True)
        actuator_tau = _draw_actuator_lag(rng)
        return IdealValve(
            model="ideal",
            quant_step=quant_step,
            actuator_tau=actuator_tau,
        )

    # Stiction case: randomly choose one of the three models
    model_choice = rng.integers(0, 3)
    actuator_tau = _draw_actuator_lag(rng)

    if model_choice == 0:
        # Choudhury two-parameter model
        deadband = float(rng.uniform(MIN_DEADBAND_PCT, MAX_DEADBAND_PCT))
        max_slip = MAX_SLIP_RATIO * deadband
        slip = float(rng.uniform(0.0, max_slip))
        return ChoudhuryValve(
            model="choudhury",
            deadband=deadband,
            slip=slip,
            actuator_tau=actuator_tau,
        )
    elif model_choice == 1:
        # Kano simple-sticking-band model
        band = float(rng.uniform(MIN_DEADBAND_PCT, MAX_DEADBAND_PCT))
        return KanoValve(
            model="kano",
            band=band,
            actuator_tau=actuator_tau,
        )
    else:
        # He one-parameter model
        d = float(rng.uniform(MIN_DEADBAND_PCT, MAX_DEADBAND_PCT))
        return HeValve(
            model="he",
            d=d,
            actuator_tau=actuator_tau,
        )
