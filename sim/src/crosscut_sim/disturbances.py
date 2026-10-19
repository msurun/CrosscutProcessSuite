"""Stochastic disturbance generators.

Currently the Ornstein-Uhlenbeck process: mean-reverting, Gaussian, with a given stationary
standard deviation and memory time. Used to make slow, realistic feed disturbances.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _check_parameters(sigma: float, tau_s: float, dt_s: float) -> None:
    """Raise ``ValueError`` unless the noise level is non-negative and the time constants are
    positive.

    Parameters
    ----------
    sigma : float
        Standard deviation of the added noise, in the same unit as the signal it perturbs.
    tau_s : float
        Correlation time of the noise process, in seconds.
    dt_s : float
        Simulation time step, in seconds.

    Raises
    ------
    ValueError
        If any argument is outside its physically meaningful range.
    """
    # A standard deviation is a square root: negative values have no real number counterpart.
    if sigma < 0:
        raise ValueError("sigma must be non-negative")
    # Both time constants are durations on a clock: zero would mean an instantaneous process,
    # and a negative duration would run it backwards in time.
    if tau_s <= 0:
        raise ValueError("tau_s must be positive")
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")


@dataclass(frozen=True)
class OuShape:
    """Statistical shape of an Ornstein-Uhlenbeck process: where it sits, how wide, how slow.

    ``mean`` is the long-run level, ``sigma`` the stationary standard deviation (both in the
    process unit) and ``tau_s`` the memory time in seconds.
    """

    mean: float
    sigma: float
    tau_s: float


class OrnsteinUhlenbeck:
    """Ornstein-Uhlenbeck process."""

    def __init__(self, shape: OuShape, dt_s: float, rng: np.random.Generator) -> None:
        """Initialize the Ornstein-Uhlenbeck process.

        The Ornstein-Uhlenbeck (OU) process is the continuous-time analogue of an AR(1)
        process: a quantity that is pulled back toward ``mean`` and simultaneously kicked
        by Gaussian noise. It is the standard model for a noisy signal that does not drift
        away forever, e.g. a temperature sensor reading or a mean-reverting price.

        The process is defined by the stochastic differential equation
        ``dX = (mean - X) / tau_s * dt + sigma * sqrt(2 / tau_s) * dW``.
        Here ``sigma`` is the stationary standard deviation (the noise gain
        ``sigma * sqrt(2 / tau_s)`` is chosen to give exactly that spread) and ``tau_s`` (the
        "relaxation" or "memory" time in seconds) sets how long the process remembers a
        deviation from the mean: it shrinks by a factor 1/e every ``tau_s``.

        Args:
            shape: Long-run mean, stationary standard deviation (the spread the process
                settles into once it has run for much longer than ``tau_s``) and time
                constant in seconds (must be positive).
            dt_s: The simulation time step, in seconds; must be positive.
            rng: The random number generator to use.

        Raises:
            ValueError: If sigma is negative, or if tau_s or dt_s are not positive.
        """
        self._validate_and_store_parameters(shape.mean, shape.sigma, shape.tau_s, dt_s)
        self._store_rng_and_initial_value(rng, shape.mean)

    def _validate_and_store_parameters(
        self, mean: float, sigma: float, tau_s: float, dt_s: float
    ) -> None:
        """Validate the process parameters and store them on the instance.

        The modelled process is an Ornstein-Uhlenbeck process, the continuous-time
        analogue of an AR(1): it is mean-reverting, pulled back towards ``mean`` with
        strength set by ``tau_s``, while driven by Gaussian noise of size ``sigma``.

        Args:
            mean: The mean of the process, i.e. the level it reverts to.
            sigma: The standard deviation of the process noise.
            tau_s: The time constant of the process, in seconds (s).
            dt_s: The time step of the process, in seconds (s).

        Raises:
            ValueError: If sigma is negative, or if tau_s or dt_s are not positive.
        """
        # Fail before storing anything, so a rejected call leaves the instance untouched.
        _check_parameters(sigma, tau_s, dt_s)
        self.mean = mean
        self.sigma = sigma
        self.tau_s = tau_s
        self.dt_s = dt_s

    def _store_rng_and_initial_value(self, rng: np.random.Generator, mean: float) -> None:
        """Store the random number generator and set the initial process value.

        Args:
            rng: The random number generator to use.
            mean: The mean of the process, used as the starting value.

        This runs once, at construction time. The generator is kept on the instance so that
        repeated calls to the same process produce a reproducible random sequence, rather
        than a fresh, unrelated one each time. ``self.value`` is the state of the process
        (same unit as ``mean``); starting it at ``mean`` means the process begins at its
        long-run average, so no warm-up transient has to decay before the output is typical.
        """
        # Plain attribute assignment, no computation: the state lives on the instance
        # and is updated in place on every subsequent step of the process.
        self.rng = rng
        self.value = mean

    def update(self) -> float:
        """Advance the process by one time step and return its new value.

        This is an Ornstein-Uhlenbeck process: a random walk that is pulled back
        towards ``self.mean`` ("mean reversion") instead of drifting away forever.
        ``self.mean`` is the long-run average level of the process and ``self.tau_s``
        is the reversion time constant in seconds, i.e. the time it takes for a
        deviation from the mean to shrink by a factor of 1/e.

        Returns:
            The new value of the process.
        """
        # Autocorrelation over one step: how much of the previous deviation from the mean survives
        # the step.
        # dt_s is the time step in seconds; phi close to 1 when dt_s is small relative to tau_s.
        phi = np.exp(-self.dt_s / self.tau_s)
        if self.sigma == 0:
            # No randomness: the process sits on the mean (it does not start elsewhere).
            self.value = self.mean
        else:
            # Exact discretisation of the OU equation over one step: keep the fraction phi of the
            # deviation from the mean, then add a fresh independent Gaussian shock.
            # The shock std is sigma * sqrt(1 - phi**2) so the process keeps its stationary
            # standard deviation sigma regardless of dt_s.
            self.value = (
                self.mean
                + phi * (self.value - self.mean)
                + self.sigma * np.sqrt(1 - phi**2) * self.rng.standard_normal()
            )
        return self.value
