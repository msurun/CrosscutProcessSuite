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
        if dt_s <= 0:
            raise ValueError("dt_s must be positive")
        if ti_s <= 0 and not math.isinf(ti_s):
            raise ValueError("ti_s must be positive or infinity")
        if out_min >= out_max:
            raise ValueError("out_min must be less than out_max")
        if td_s < 0:
            raise ValueError("td_s must be non-negative")
        if td_filter_n <= 0:
            raise ValueError("td_filter_n must be positive")

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

        e = pv - sp if self.direct else sp - pv
        p = self.kc * e

        if self.td_s == 0:
            d = 0.0
        else:
            tf = self.td_s / self.td_filter_n
            dpv = pv - self._prev_pv if self._prev_pv is not None else 0.0
            s = 1 if self.direct else -1
            d = tf / (tf + self.dt_s) * self._d + s * self.kc * self.td_s / (tf + self.dt_s) * dpv
            self._d = d

        inc = self.kc * e * self.dt_s / self.ti_s if not math.isinf(self.ti_s) else 0.0

        if mode == "MAN":
            out = max(self.out_min, min(self.out_max, man_out))
            self._i = out - p - d - inc
            return out

        candidate = self._i + inc
        unclipped = p + candidate + d
        out = max(self.out_min, min(self.out_max, unclipped))

        if (unclipped > self.out_max and inc > 0) or (unclipped < self.out_min and inc < 0):
            out = max(self.out_min, min(self.out_max, p + self._i + d))
        else:
            self._i = candidate

        self._prev_pv = pv
        return out
