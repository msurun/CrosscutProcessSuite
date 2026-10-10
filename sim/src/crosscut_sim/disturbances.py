"""Stochastic disturbance generators."""

from __future__ import annotations

import numpy as np


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
        if sigma < 0:
            raise ValueError("sigma must be non-negative")
        if tau_s <= 0:
            raise ValueError("tau_s must be positive")
        if dt_s <= 0:
            raise ValueError("dt_s must be positive")

        self.mean = mean
        self.sigma = sigma
        self.tau_s = tau_s
        self.dt_s = dt_s
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
