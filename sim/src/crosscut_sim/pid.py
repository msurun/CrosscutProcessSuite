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
        """Raise ``ValueError`` if any constructor setting is out of range.

        This is a physical-plausibility check on a PID controller's tuning parameters, called once
        at construction time so that a bad configuration fails immediately instead of silently
        producing wrong control output later.

        Raises:
            ValueError: if any of the five settings violates its allowed range.
        """
        # The sample time (in seconds) is how often the controller is called. It must be positive
        # because the derivative and integral terms divide by it.
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

        # td_filter_n is how many samples the first-order low-pass filter on the derivative term
        # averages over. It must be at least one sample for the filter to be defined.
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

        where ``e`` is the deviation between setpoint and process variable.  The equation is
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
        # Cheap guard so the caller gets a clear message instead of a silently wrong behaviour.
        if mode not in ("MAN", "AUTO"):
            raise ValueError("mode must be 'MAN' or 'AUTO'")

        # Deviation between measurement and setpoint, in engineering units.
        # In direct action (self.direct is True: output up -> pv up) the controller must react
        # to the setpoint being *above* the measurement, hence sp - pv.  In reverse action the
        # sign flips.  Everything downstream only uses this signed deviation.
        error = pv - sp if self.direct else sp - pv
        # Proportional contribution, in output units: Kc [dimensionless] * error [e.u.].
        proportional = self.kc * error

        # Derivative term, in output units.  Skipped when Td == 0 because then the filter time
        # below would be 0 and the formulas would divide by zero / keep a stale value.
        if self.td_s == 0:
            derivative = 0.0
        else:
            # Time constant of the 1st-order filter applied to the derivative, in seconds.
            # The filter is the usual "Td/N" one: N (td_filter_n) trades noise rejection
            # (small N) against derivative speed (large N).  N = 8..10 is typical.
            filter_time_s = self.td_s / self.td_filter_n
            # Change of the measurement since the previous step, in engineering units.
            # The first call has no previous value, so the change is taken as zero.
            pv_change = pv - self._prev_pv if self._prev_pv is not None else 0.0
            # Because the derivative acts on pv and not on the error, the sign of the
            # contribution must be corrected: d(error)/dt = -d(pv)/dt in direct action and
            # +d(pv)/dt in reverse action, hence 1 / -1.
            error_sign = 1 if self.direct else -1
            # Discretisation of a filtered derivative by backward Euler.
            # The continuous filter is  D + (Td/N) * dD/dt = Kc * Td * d(error)/dt.
            # Backward Euler with step dt gives the recursion below:
            #   D_k = a * D_{k-1} + error_sign * Kc * Td / (Td/N + dt) * (pv_k - pv_{k-1})
            # with a = (Td/N) / (Td/N + dt) the filter's weight on the previous value.
            # D is stored in output units so it can be added directly to Kc*e.
            derivative = (
                filter_time_s / (filter_time_s + self.dt_s) * self._d
                + error_sign
                * self.kc
                * self.td_s
                / (filter_time_s + self.dt_s)
                * pv_change
            )
            # Remember D_k for the next call (the filter's state).
            self._d = derivative

        # Integral increment, in output units, added during this step of dt_s seconds.
        # The continuous integral contribution is (Kc / Ti) * integral(error) dt; sampled with
        # backward Euler this adds Kc * error * dt / Ti per step.
        # Ti = inf means "no integral action requested", so the increment stays 0.
        if math.isinf(self.ti_s):
            integral_increment = 0.0
        else:
            integral_increment = self.kc * error * self.dt_s / self.ti_s

        # --- Manual mode: the operator dictates the output. ---
        if mode == "MAN":
            output = self._clip(man_out)
            # Back-calculate the integral state so that, at the switch back to AUTO, the
            # controller resumes exactly from the manual output instead of jumping
            # (this is the standard "bumpless transfer" trick):
            #   out = P + I + D + dI  =>  I = out - P - D - dI
            self._i = output - proportional - derivative - integral_increment
            return output

        # --- Automatic mode: the controller computes the output. ---
        # Try the integrator first, then check whether the resulting output saturates.
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

        # Store the measurement so the next call can differentiate it.  Note this happens
        # after manual mode returned early: in "MAN" the derivative state is left untouched on
        # purpose, so switching back to "AUTO" does not create a derivative bump.
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
