"""JSON-safe, thinned series for the tuning payload (measured/model comparison curves)."""

from __future__ import annotations

import numpy as np

MAX_CHECK_POINTS = 600  # points of a curve sent to the browser

JsonSeries = list[float] | list[float | None]


def thin_index(length: int) -> np.ndarray:
    """Indices of at most MAX_CHECK_POINTS samples spread evenly over ``length`` samples."""
    return np.linspace(0, length - 1, min(MAX_CHECK_POINTS, length)).astype(int)


def json_list(values: np.ndarray) -> list[float | None]:
    """Values as a JSON-safe list: NaN has no JSON form, so it becomes None."""
    return [None if np.isnan(value) else float(value) for value in values]


def comparison(
    t_s: np.ndarray, measured: np.ndarray, simulated: np.ndarray
) -> dict[str, JsonSeries]:
    """Measured and model PV on a common, thinned time axis (same indices for all three)."""
    keep = thin_index(len(t_s))
    return {
        "t_s": t_s[keep].tolist(),
        "measured": json_list(measured[keep]),
        "simulated": json_list(simulated[keep]),
    }
