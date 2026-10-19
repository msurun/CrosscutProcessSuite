"""PID controller with anti-windup and bumpless transfer.

Discrete ISA-style PID: derivative on the process variable with a first-order filter, integral by
conditional integration, back-calculated integral state in manual mode. Times in seconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PidTuning:
    """Tuning constants of a PID controller.

    ``kc`` is the proportional gain, ``ti_s`` the integral time in seconds (``math.inf``
    disables the integral term), ``td_s`` the derivative time in seconds (0 disables it) and
    ``td_filter_n`` the derivative filter coefficient N (filter time constant is Td / N).
    """

    kc: float
    ti_s: float
    td_s: float = 0.0
    td_filter_n: float = 10.0


@dataclass(frozen=True)
class OutputLimits:
    """Actuator limits, in the same unit as the controller output (e.g. percent)."""

    low: float = 0.0
    high: float = 100.0


class PID:
    """PID controller with anti-windup and bumpless transfer."""

    def __init__(
        self,
        tuning: PidTuning,
        dt_s: float,
        limits: OutputLimits = OutputLimits(),  # noqa: B008 - frozen, safe to share
        direct: bool = False,
    ) -> None:
        """Initialize the PID controller.

        Args:
            tuning: Gains and time constants (proportional, integral, derivative, filter).
            dt_s: Sample time in seconds.
            limits: Minimum and maximum output value.
            direct: If True, the controller is direct acting.
        """
        self.kc = tuning.kc
        self.ti_s = tuning.ti_s
        self.dt_s = dt_s
        self.out_min = limits.low
        self.out_max = limits.high
        self.td_s = tuning.td_s
        self.td_filter_n = tuning.td_filter_n
        self.direct = direct
        self._i = 0.0
        self._d = 0.0
        self._prev_pv: float | None = None
        self._validate()

    def _validate(self) -> None:
        """Raise ``ValueError`` if any constructor setting is out of range.

        This is a physical-plausibility check on a PID controller's tuning parameters, called once
        at construction time so that a bad configuration fails immediately instead of silently
        producing wrong control output later.

        Raises:
            ValueError: if any of the five settings violates its allowed range.
        """
        # The sample time (in seconds) is how often the controller is called. Every discrete
        # update scales with it, so a zero or negative step has no meaning.
        if self.dt_s <= 0:
            raise ValueError("dt_s must be positive")

        # ti_s is the integral time constant (seconds). A positive value sets how fast the integral
        # term reacts. An infinite value is allowed and means "disable the integral term".
        if self.ti_s <= 0 and not math.isinf(self.ti_s):
            raise ValueError("ti_s must be positive or infinity")

        # out_min and out_max are the actuator limits (same unit as the controller output, e.g.
        # percent or volts). They must span a non-empty range, otherwise clipping is impossible.
        if self.out_min >= self.out_max:
            raise ValueError("out_min must be less than out_max")

        # td_s is the derivative time constant (seconds). Zero is legal and means "disable the
        # derivative term", so only negative values are rejected.
        if self.td_s < 0:
            raise ValueError("td_s must be non-negative")

        # td_filter_n is the derivative filter coefficient N: the filter time constant is Td / N,
        # so a larger N means a faster filter and less noise rejection. It must be positive.
        if self.td_filter_n <= 0:
            raise ValueError("td_filter_n must be positive")

    def reset(self) -> None:
        """Reset the PID controller state."""
        self._i = 0.0
        self._d = 0.0
        self._prev_pv = None

    def update(self, pv: float, sp: float, mode: str, man_out: float = 0.0) -> float:
        """Update the PID controller (one discrete time step of length ``self.dt_s`` seconds).

        The controller is the standard ISA ("ideal", non-interacting) PID form in velocity-free,
        positional shape::

            output = Kc * e + (Kc / Ti) * integral_of(e) + Kc * Td * d(e) / dt

        where ``e`` is the signed deviation (sp - pv for reverse action, pv - sp for direct
        action) and the derivative is taken on pv, see below.  The equation is
        solved recursively, not in closed form, so the previous calls' contributions are kept
        inside ``self._i`` (the integral/accumulated term, in output units) and ``self._d``
        (the filtered derivative term, also in output units).

        Derivative action is taken on the *process variable* rather than on the error, which
        avoids the "derivative kick" (a spike every time the operator moves the setpoint).
        The derivative is filtered by a first-order lag with time constant ``Td / td_filter_n``
        seconds, so that measurement noise is not amplified.

        ``self._i`` is also used as the anti-windup state: it is the value that makes the
        controller output continuous when the loop leaves manual mode or when the output
        saturation is released.

        Args:
            pv: Process variable (controlled measurement), in engineering units.
            sp: Setpoint, in engineering units.
            mode: Controller mode ("MAN" or "AUTO").  "MAN" means the output is written by the
                operator; "AUTO" means the controller computes it.
            man_out: Output requested by the operator, in output units (%).  Only used in "MAN".

        Returns:
            The controller output, in output units (%), already limited by ``self._clip``.

        Raises:
            ValueError: If the mode is invalid.
        """
        if mode not in ("MAN", "AUTO"):
            raise ValueError("mode must be 'MAN' or 'AUTO'")

        error = self._signed_error(pv, sp)
        proportional = self.kc * error
        derivative = self._update_derivative(pv)
        # The measurement is remembered in both modes: the derivative state ``_d`` is updated
        # from it in MAN too, so a stale value would feed a wrong pv_change into the filter and
        # kick the output on the first AUTO step.
        self._prev_pv = pv
        integral_increment = self._integral_increment(error)

        if mode == "MAN":
            return self._apply_manual_output(man_out, proportional, derivative, integral_increment)

        return self._compute_auto_output(proportional, derivative, integral_increment)

    def _signed_error(self, pv: float, sp: float) -> float:
        """Deviation between measurement and setpoint, in engineering units.

        Direct action (``self.direct`` True) raises the output when pv rises above sp, so the
        error is pv - sp.  Reverse action raises it when pv falls below sp, so the error is
        sp - pv.  Everything downstream only uses this signed error.
        """
        return pv - sp if self.direct else sp - pv

    def _update_derivative(self, pv: float) -> float:
        """Compute the filtered derivative term in output units, and store it as ``self._d``.

        Td == 0 disables the term: both the filter time Td / N and the gain Kc * Td are zero, so
        the derivative is 0 and the filter state stays 0.
        """
        if self.td_s == 0:
            return 0.0

        # Time constant of the 1st-order filter applied to the derivative, in seconds.
        # The filter is the usual "Td/N" one: N (td_filter_n) trades noise rejection
        # (small N) against derivative speed (large N); the default N is 10.
        filter_time_s = self.td_s / self.td_filter_n
        # Change of the measurement since the previous step, in engineering units.
        # The first call has no previous value, so the change is taken as zero.
        pv_change = pv - self._prev_pv if self._prev_pv is not None else 0.0
        # Because the derivative acts on pv and not on the error, the sign of the
        # contribution must follow d(error)/dt: with error = pv - sp (direct action) it is
        # +d(pv)/dt, with error = sp - pv (reverse action, sp held) it is -d(pv)/dt.
        error_sign = 1 if self.direct else -1
        # Discretisation of a filtered derivative by backward Euler.
        # The continuous filter is  D + (Td/N) * dD/dt = Kc * Td * d(error)/dt.
        # Backward Euler with step dt gives the recursion below:
        #   D_k = a * D_{k-1} + error_sign * Kc * Td / (Td/N + dt) * (pv_k - pv_{k-1})
        # with a = (Td/N) / (Td/N + dt) the filter's weight on the previous value.
        # D is stored in output units so it can be added directly to Kc*e.
        derivative = (
            filter_time_s / (filter_time_s + self.dt_s) * self._d
            + error_sign * self.kc * self.td_s / (filter_time_s + self.dt_s) * pv_change
        )
        # Remember D_k for the next call (the filter's state).
        self._d = derivative
        return derivative

    def _integral_increment(self, error: float) -> float:
        """Integral increment in output units, added during this step of ``dt_s`` seconds.

        The continuous integral contribution is (Kc / Ti) * integral(error) dt; sampled with
        backward Euler this adds Kc * error * dt / Ti per step.
        Ti = inf means "no integral action requested", so the increment stays 0.
        """
        if math.isinf(self.ti_s):
            return 0.0
        return self.kc * error * self.dt_s / self.ti_s

    def _apply_manual_output(
        self, man_out: float, proportional: float, derivative: float, integral_increment: float
    ) -> float:
        """In manual mode the operator dictates the output; store the matching integral state.

        Back-calculates the integral state so that, at the switch back to AUTO, the controller
        resumes exactly from the manual output instead of jumping (the standard "bumpless
        transfer" trick):  out = P + I + D + dI  =>  I = out - P - D - dI
        """
        output = self._clip(man_out)
        self._i = output - proportional - derivative - integral_increment
        return output

    def _compute_auto_output(
        self, proportional: float, derivative: float, integral_increment: float
    ) -> float:
        """In automatic mode the controller computes the output, with anti-windup.

        Tries the integrator first, then checks whether the resulting output saturates.
        """
        candidate_integral = self._i + integral_increment
        unclipped_output = proportional + candidate_integral + derivative
        output = self._clip(unclipped_output)

        # Anti-windup: if we are pushing further into the saturation limit, refuse the new
        # integral increment and recompute the output with the previous integral state, so the
        # integrator stops growing where it cannot have an effect ("conditional integration").
        if self._is_winding_up(unclipped_output, integral_increment):
            output = self._clip(proportional + self._i + derivative)
        else:
            # Output not (or no longer) saturated in that direction: keep the new integral.
            self._i = candidate_integral
        return output

    def _clip(self, value: float) -> float:
        """Clamp a value to the configured output limits."""
        return max(self.out_min, min(self.out_max, value))

    def _is_winding_up(self, unclipped_output: float, integral_increment: float) -> bool:
        """Return True when the integral term pushes an already saturated output further out."""
        return (unclipped_output > self.out_max and integral_increment > 0) or (
            unclipped_output < self.out_min and integral_increment < 0
        )
