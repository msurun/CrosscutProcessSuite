"""Stochastic disturbance generators."""

from __future__ import annotations

import numpy as np


def _check_parameters(sigma: float, tau_s: float, dt_s: float) -> None:
    """Raise ``ValueError`` unless the noise level is non-negative and the time constants are
    positive."""
    if sigma < 0:
        raise ValueError("sigma must be non-negative")
    if tau_s <= 0:
        raise ValueError("tau_s must be positive")
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")


class OrnsteinUhlenbeck:
    """Ornstein-Uhlenbeck process."""

    def __init__(
        self, mean: float, sigma: float, tau_s: float, dt_s: float, rng: np.random.Generator
    ) -> None:
        """Initialize the Ornstein-Uhlenbeck process.

        Args:
            mean: The mean of the process.
            sigma: The standard deviation of the process.
            tau_s: The time constant of the process.
            dt_s: The time step of the process.
            rng: The random number generator to use.

        Raises:
            ValueError: If sigma is negative, or if tau_s or dt_s are not positive.
        """
        self._validate_and_store_parameters(mean, sigma, tau_s, dt_s)
        self._store_rng_and_initial_value(rng, mean)

    def _validate_and_store_parameters(
        self, mean: float, sigma: float, tau_s: float, dt_s: float
    ) -> None:
        """Validate the process parameters and store them on the instance.

        Args:
            mean: The mean of the process.
            sigma: The standard deviation of the process.
            tau_s: The time constant of the process.
            dt_s: The time step of the process.

        Raises:
            ValueError: If sigma is negative, or if tau_s or dt_s are not positive.
        """
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
        """
        self.rng = rng
        self.value = mean

    def update(self) -> float:
        """Update the value of the process.

        Returns:
            The new value of the process.
        """
        phi = np.exp(-self.dt_s / self.tau_s)
        if self.sigma == 0:
            self.value = self.mean
        else:
            self.value = (
                self.mean
                + phi * (self.value - self.mean)
                + self.sigma * np.sqrt(1 - phi**2) * self.rng.standard_normal()
            )
        return self.value
