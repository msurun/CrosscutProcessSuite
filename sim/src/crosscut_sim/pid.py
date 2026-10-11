"""PID controller with anti-windup and bumpless transfer."""

from __future__ import annotations

import math


class PID:
    """PID controller with anti-windup and bumpless transfer."""

    def __init__(
        self,
        kc: float,
        ti_s: float,
        dt_s: float,
        out_min: float = 0.0,
        out_max: float = 100.0,
        td_s: float = 0.0,
        td_filter_n: float = 10.0,
        direct: bool = False,
    ) -> None:
        """Initialize the PID controller.

        Args:
            kc: Proportional gain.
            ti_s: Integral time constant in seconds.
            dt_s: Sample time in seconds.
            out_min: Minimum output value.
            out_max: Maximum output value.
            td_s: Derivative time constant in seconds.
            td_filter_n: Derivative filter coefficient.
            direct: If True, the controller is direct acting.
        """
        self.kc = kc
        self.ti_s = ti_s
        self.dt_s = dt_s
        self.out_min = out_min
        self.out_max = out_max
        self.td_s = td_s
        self.td_filter_n = td_filter_n
        self.direct = direct
        self._i = 0.0
        self._d = 0.0
        self._prev_pv: float | None = None
        self._validate()

    def _validate(self) -> None:
        """Raise ``ValueError`` if any constructor setting is out of range."""
        if self.dt_s <= 0:
            raise ValueError("dt_s must be positive")
        if self.ti_s <= 0 and not math.isinf(self.ti_s):
            raise ValueError("ti_s must be positive or infinity")
        if self.out_min >= self.out_max:
            raise ValueError("out_min must be less than out_max")
        if self.td_s < 0:
            raise ValueError("td_s must be non-negative")
        if self.td_filter_n <= 0:
            raise ValueError("td_filter_n must be positive")

    def reset(self) -> None:
        """Reset the PID controller state."""
        self._i = 0.0
        self._d = 0.0
        self._prev_pv = None

    def update(self, pv: float, sp: float, mode: str, man_out: float = 0.0) -> float:
        """Update the PID controller.

        Args:
            pv: Process variable.
            sp: Setpoint.
            mode: Controller mode ("MAN" or "AUTO").
            man_out: Manual output value.

        Returns:
            The controller output.

        Raises:
            ValueError: If the mode is invalid.
        """
        if mode not in ("MAN", "AUTO"):
            raise ValueError("mode must be 'MAN' or 'AUTO'")

        error = pv - sp if self.direct else sp - pv
        proportional = self.kc * error

        if self.td_s == 0:
            derivative = 0.0
        else:
            filter_time_s = self.td_s / self.td_filter_n
            pv_change = pv - self._prev_pv if self._prev_pv is not None else 0.0
            error_sign = 1 if self.direct else -1
            derivative = (
                filter_time_s / (filter_time_s + self.dt_s) * self._d
                + error_sign
                * self.kc
                * self.td_s
                / (filter_time_s + self.dt_s)
                * pv_change
            )
            self._d = derivative

        if math.isinf(self.ti_s):
            integral_increment = 0.0
        else:
            integral_increment = self.kc * error * self.dt_s / self.ti_s

        if mode == "MAN":
            output = self._clip(man_out)
            self._i = output - proportional - derivative - integral_increment
            return output

        candidate_integral = self._i + integral_increment
        unclipped_output = proportional + candidate_integral + derivative
        output = self._clip(unclipped_output)

        if self._is_winding_up(unclipped_output, integral_increment):
            output = self._clip(proportional + self._i + derivative)
        else:
            self._i = candidate_integral

        self._prev_pv = pv
        return output

    def _clip(self, value: float) -> float:
        """Clamp a value to the configured output limits."""
        return max(self.out_min, min(self.out_max, value))

    def _is_winding_up(self, unclipped_output: float, integral_increment: float) -> bool:
        """Return True when the integral term pushes an already saturated output further out."""
        return (unclipped_output > self.out_max and integral_increment > 0) or (
            unclipped_output < self.out_min and integral_increment < 0
        )
