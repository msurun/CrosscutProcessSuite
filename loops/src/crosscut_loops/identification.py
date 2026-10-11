"""Identification of first-order-plus-dead-time (FOPDT) models from data.

Method
------
The routine fits the discrete ARX model

    y[k+1] = a * y[k] + b * u[k-d] + c

by least squares for every candidate integer delay d, and keeps the delay that
minimises the residual sum of squares. The continuous FOPDT parameters follow
from the discrete coefficients:

    gain            = b / (1 - a)
    time_constant_s = -dt_s / ln(a)
    delay_s         = d * dt_s

Limits
------
* Open-loop data is required. Closed-loop data with a correlated input and
  unmeasured disturbances gives biased estimates, so prefer step tests or
  manually driven (MAN) data.
* The delay is quantised to whole samples, so ``delay_s`` is a multiple of
  ``dt_s``. A true delay of a few samples cannot be resolved precisely.
* The model assumes a single first-order pole. Higher-order dynamics are
  approximated as first order plus dead time and may fit poorly.
"""

from __future__ import annotations

import numpy as np

from crosscut_loops.tuning_rules import FopdtModel

# A fit needs enough samples to cover the dead time plus the transient of the
# first-order pole; below this the least-squares solution is not trustworthy.
MIN_SAMPLES = 50

# Columns of the regression matrix y[k+1] ~ a*y[k] + b*u[k-d] + c.
_REGRESSION_COLUMNS = 3

# A delay is only considered free of correlation between input and output when
# the input explains a decent share of the output. On pure white noise the best
# delay usually shows a higher correlation, so this floor rejects such fits.
MIN_FIT_QUALITY = 0.3


def identify_fopdt(u: np.ndarray, y: np.ndarray, dt_s: float, max_delay_s: float) -> FopdtModel:
    """Identify a FOPDT model from input/output data by least squares.

    Args:
        u: Input samples, one per sampling instant.
        y: Output samples, the same length as ``u``.
        dt_s: Sampling period in seconds, positive.
        max_delay_s: Largest dead time to scan, in seconds, positive.

    Returns:
        The ``FopdtModel`` whose discrete equivalent best fits the data.

    Raises:
        ValueError: If the signals are malformed, the sampling arguments are
            invalid, or no candidate delay yields a physically meaningful model.
    """
    _validate_inputs(u, y, dt_s, max_delay_s)
    max_delay_samples = int(round(max_delay_s / dt_s))
    best = _fit_best_delay(u, y, dt_s, max_delay_samples)
    return best[0]


def _validate_inputs(
    controller_output: np.ndarray,
    process_value: np.ndarray,
    dt_s: float,
    max_delay_s: float,
) -> None:
    """Raise ValueError if the signals or sampling arguments are unusable."""
    _check_signals(controller_output, process_value)
    _check_sampling(dt_s, max_delay_s)


def _check_signals(controller_output: np.ndarray, process_value: np.ndarray) -> None:
    """Raise ValueError if the input and output arrays cannot be fitted."""
    controller = np.asarray(controller_output, dtype=float)
    process = np.asarray(process_value, dtype=float)
    if controller.shape != process.shape:
        raise ValueError(
            f"u and y must have the same shape, got {controller.shape} and {process.shape}"
        )
    if controller.ndim != 1:
        raise ValueError("u and y must be one-dimensional arrays")
    if controller.size < MIN_SAMPLES:
        raise ValueError(f"Need at least {MIN_SAMPLES} samples, got {controller.size}")
    if not np.all(np.isfinite(controller)) or not np.all(np.isfinite(process)):
        raise ValueError("u and y must contain only finite values (no NaN or inf)")


def _check_sampling(dt_s: float, max_delay_s: float) -> None:
    """Raise ValueError if the sampling period or the scanned dead time is not positive."""
    if dt_s <= 0.0:
        raise ValueError(f"dt_s must be positive, got {dt_s}")
    if max_delay_s <= 0.0:
        raise ValueError(f"max_delay_s must be positive, got {max_delay_s}")


_NO_MODEL_MESSAGE = (
    "No physically meaningful FOPDT model fits this data well enough. "
    "Check that the input excites the process, the data is open loop, "
    "and the output is not pure noise."
)


def _fit_best_delay(
    controller_output: np.ndarray,
    process_value: np.ndarray,
    dt_s: float,
    max_delay_samples: int,
) -> tuple[FopdtModel, float]:
    """Return the best-fitting model and its normalised error over all delays."""
    controller_output = np.asarray(controller_output, dtype=float)
    process_value = np.asarray(process_value, dtype=float)
    if float(np.var(process_value)) <= 0.0:
        raise ValueError("Output y is constant, so a FOPDT model cannot be identified")
    best: tuple[FopdtModel, float] | None = None
    for delay_samples in range(max_delay_samples + 1):
        candidate = _model_for_delay(controller_output, process_value, dt_s, delay_samples)
        if candidate is not None and (best is None or candidate[1] < best[1]):
            best = candidate
    if best is None:
        raise ValueError(_NO_MODEL_MESSAGE)
    return best


def _model_for_delay(
    controller_output: np.ndarray,
    process_value: np.ndarray,
    dt_s: float,
    delay_samples: int,
) -> tuple[FopdtModel, float] | None:
    """Return (model, normalised_error) for one delay, or None if it is rejected."""
    fitted = _fit_one_delay(controller_output, process_value, delay_samples)
    if fitted is None:
        return None
    discrete_a, discrete_b, per_sample_error = fitted
    output_variance = float(np.var(process_value))
    if 1.0 - per_sample_error / output_variance < MIN_FIT_QUALITY:
        return None
    model = _to_fopdt(discrete_a, discrete_b, dt_s, delay_samples)
    if model is None:
        return None
    return model, per_sample_error


def _fit_one_delay(
    controller_output: np.ndarray,
    process_value: np.ndarray,
    delay_samples: int,
) -> tuple[float, float, float] | None:
    """Return (a, b, normalised_error) for one delay, or None if rows are too few."""
    regression, target = _build_regression(controller_output, process_value, delay_samples)
    if regression.shape[0] < _REGRESSION_COLUMNS:
        return None
    coefficients, _, _, _ = np.linalg.lstsq(regression, target, rcond=None)
    predicted = regression @ coefficients
    error = float(np.sum((target - predicted) ** 2) / len(target))
    return float(coefficients[0]), float(coefficients[1]), error


def _build_regression(
    controller_output: np.ndarray,
    process_value: np.ndarray,
    delay_samples: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build (regression, target) for rows k = delay..n-2: [y[k], u[k-delay], 1] -> y[k+1]."""
    last_k = len(controller_output) - 2
    if last_k < delay_samples:
        return np.empty((0, _REGRESSION_COLUMNS)), np.empty(0)
    indices = np.arange(delay_samples, last_k + 1)
    current_output = process_value[indices]
    delayed_input = controller_output[indices - delay_samples]
    ones = np.ones_like(current_output)
    regression = np.column_stack((current_output, delayed_input, ones))
    target = process_value[indices + 1]
    return regression, target


def _to_fopdt(
    discrete_a: float,
    discrete_b: float,
    dt_s: float,
    delay_samples: int,
) -> FopdtModel | None:
    """Convert discrete (a, b) into a FOPDT model, or None if unphysical.

    A stable first-order pole needs 0 < a < 1 and a positive gain needs
    b / (1 - a) > 0. A zero delay becomes one sample, since FopdtModel
    requires a strictly positive dead time.
    """
    if not 0.0 < discrete_a < 1.0:
        return None
    gain = discrete_b / (1.0 - discrete_a)
    if gain <= 0.0:
        return None
    time_constant_s = -dt_s / np.log(discrete_a)
    delay_s = max(delay_samples, 1) * dt_s
    return FopdtModel(gain=gain, time_constant_s=float(time_constant_s), delay_s=float(delay_s))
