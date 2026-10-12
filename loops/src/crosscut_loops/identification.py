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

    The model is "First Order Plus Dead Time": the output reacts to the input
    as a first-order lag, after waiting a pure transport delay. In continuous
    time its Laplace form is ``G(s) = K * exp(-theta * s) / (tau * s + 1)``,
    where ``K`` is the gain (output units per input unit), ``tau`` the time
    constant in seconds (time to reach 63.2 % of a step change) and ``theta``
    the dead time in seconds.

    The dead time is not a continuous parameter here: it is scanned over whole
    sampling periods, and for each candidate the gain and time constant are
    found by ordinary least squares on the discretised model equations. The
    candidate with the best fit wins.

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
    # Delays are only tested at whole sampling instants, so convert the bound
    # from seconds to a sample count. Example: 1.0 s bound at dt_s = 0.1 s
    # gives 10 samples, i.e. candidates 0..10.
    max_delay_samples = int(round(max_delay_s / dt_s))
    best = _fit_best_delay(u, y, dt_s, max_delay_samples)
    return best[0]


def _validate_inputs(
    controller_output: np.ndarray,
    process_value: np.ndarray,
    dt_s: float,
    max_delay_s: float,
) -> None:
    """Raise ValueError if the signals or sampling arguments are unusable.

    This is the entry guard for the identification pipeline: it fans out to two
    focused checks and never returns a value.

    Parameters
    ----------
    controller_output:
        Signal driving the plant (system input), shape (n_samples,).
    process_value:
        Measured plant output, shape (n_samples,), aligned sample-by-sample with
        ``controller_output``.
    dt_s:
        Sampling period in seconds (SIMULATION/REAL time, not index units).
    max_delay_s:
        Largest transport delay to search for, in seconds; may be 0.

    Raises
    ------
    ValueError
        If the signals are mismatched or non-finite, or if the sampling
        arguments are non-positive.
    """
    _check_signals(controller_output, process_value)
    _check_sampling(dt_s, max_delay_s)


def _check_signals(controller_output: np.ndarray, process_value: np.ndarray) -> None:
    """Raise ValueError if the input and output arrays cannot be fitted.

    "u" is the controller output signal, "y" is the measured process value.
    Both are samples of a single-input, single-output (SISO) system, taken at
    the same instants: sample i of u drove the process when sample i of y was
    recorded, so the two arrays must line up index by index.

    A model is fitted to this pair, so anything that would make the fit
    meaningless (different lengths, a multi-loop shape, too few samples,
    gaps in the data) is rejected here with a message naming the offender.
    Returns None; raises ValueError on any bad input.
    """
    # asarray copies nothing when the input is already a float array, so this
    # stays cheap, but it guarantees every check below works on numbers.
    controller = np.asarray(controller_output, dtype=float)
    process = np.asarray(process_value, dtype=float)

    if controller.shape != process.shape:
        raise ValueError(
            f"u and y must have the same shape, got {controller.shape} and {process.shape}"
        )

    # Shape (n,) is one signal over time; shape (n, m) would be several loops
    # mixed together, which this SISO fitter cannot tell apart.
    if controller.ndim != 1:
        raise ValueError("u and y must be one-dimensional arrays")

    # Fewer than MIN_SAMPLES points give too little excitation to identify the
    # model parameters, so the result would be numerical noise.
    if controller.size < MIN_SAMPLES:
        raise ValueError(f"Need at least {MIN_SAMPLES} samples, got {controller.size}")

    # NaN or inf cannot be compared, averaged or regressed on; a single one
    # would silently poison every later calculation, so reject them up front.
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
    """Return the best-fitting model and its normalised error over all delays.

    A FOPDT (First-Order Plus Dead Time) model describes a process that reacts with
    a first-order lag and a pure transport delay. Its parameters are fitted for
    every delay from 0 up to ``max_delay_samples`` and the delay giving the
    smallest error wins.

    Args:
        controller_output: Input signal (the controller output), one sample per time step.
        process_value: Measured process output y, one sample per time step.
        dt_s: Sampling period in seconds; converts a delay in samples into seconds.
        max_delay_samples: Largest dead time to try, in NUMBER OF SAMPLES (0 .. this value).

    Returns:
        The best model and the normalised error of that fit; lower error is better.

    Raises:
        ValueError: If y never changes (nothing to identify), or if no delay
            produced an identifiable model.
    """
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
    """Return (model, normalised_error) for one delay, or None if it is rejected.

    This is the candidate-scoring step of a system identification search: for a
    single assumed transport delay, fit a discrete model and reject it when the
    fit is too poor to be believable. The caller decides which delay wins.

    Args:
        controller_output: manipulated variable (MV) samples, in actuator units.
        process_value: controlled variable (PV) samples, one per MV sample.
        dt_s: sampling interval in seconds.
        delay_samples: transport delay of the trial model, in samples (integer).

    Returns:
        (model, per_sample_error) when the fit passes the quality gate, else None.
        per_sample_error is the residual sum-of-squares, in PV units squared.
    """
    fitted = _fit_one_delay(controller_output, process_value, delay_samples)
    if fitted is None:
        return None

    # The discrete ARX model y[k+1] = a*y[k] + b*u[k-d] + c is fitted
    # with three coefficients, but only a and b matter here; the constant
    # c absorbs any offset between u and y.
    discrete_a, discrete_b, per_sample_error = fitted

    # R^2 = 1 - MSE/VAR: how much of the PV's variance the model explains.
    # Both per_sample_error and output_variance are mean-squared (not summed),
    # so the ratio is scale-free.
    output_variance = float(np.var(process_value))

    # Reject a fit explaining less than MIN_FIT_QUALITY of the PV variance:
    # such a model would be fitting noise, not the process.
    if 1.0 - per_sample_error / output_variance < MIN_FIT_QUALITY:
        return None

    # Convert the dimensionless discrete a, b into the physical gain, time
    # constant and dead time of the FOPDT model, using the sampling interval.
    model = _to_fopdt(discrete_a, discrete_b, dt_s, delay_samples)

    # _to_fopdt returns None when the discrete coefficients are not physically
    # realisable (for example a non-positive time constant).
    if model is None:
        return None

    return model, per_sample_error


def _fit_one_delay(
    controller_output: np.ndarray,
    process_value: np.ndarray,
    delay_samples: int,
) -> tuple[float, float, float] | None:
    """Return (a, b, normalised_error) for one delay, or None if rows are too few.

    Fits a first-order model of the process at the given transport delay:
    the process value is predicted as a linear combination of two regressors.
    Least squares minimises the mean squared residual (the normalised error).
    """
    # Build the design matrix (each row a sample, columns the regressors) and the
    # target vector (the value to predict). The regressors depend on delay_samples.
    regression, target = _build_regression(controller_output, process_value, delay_samples)
    # Need at least one row per arithmetic operator and column; fewer observations
    # than parameters makes the fit under-determined, so refuse to guess a result.
    if regression.shape[0] < _REGRESSION_COLUMNS:
        return None
    # Solve the ordinary least-squares problem: find coefficients minimising
    # ||regression @ coefficients - target||. The three discarded outputs are
    # residuals, rank and singular values, unused here.
    coefficients, _, _, _ = np.linalg.lstsq(regression, target, rcond=None)
    predicted = regression @ coefficients
    # Mean squared residual: units are (process_value units)^2, an error, not
    # the process value itself. Dividing by len(target) makes it comparable
    # across delays with different numbers of samples.
    error = float(np.sum((target - predicted) ** 2) / len(target))
    # The regression columns are [y[k], u[k-delay], 1], so coefficients[0] is
    # a and coefficients[1] is b. Per-sample error is in PV units squared.
    return float(coefficients[0]), float(coefficients[1]), error


def _build_regression(
    controller_output: np.ndarray,
    process_value: np.ndarray,
    delay_samples: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build (regression, target) for rows k = delay..n-2: [y[k], u[k-delay], 1] -> y[k+1].

    Fits a first-order ARX (autoregressive with exogenous input) discrete model:
    y[k+1] = a * y[k] + b * u[k-delay] + c, where the constant 1 column is the bias term
    that absorbs the operating point. The system is assumed linear and time-invariant,
    and delay_samples is the dead time (transport delay) measured in samples, i.e. how
    many sample periods pass before a change in the input u shows up in the output y.

    Args:
        controller_output: input signal u, one value per sample step.
        process_value: output signal y, same length and same sampling instants as u.
        delay_samples: dead time in samples (>= 0); aligns u[k-delay] with y[k].

    Returns:
        regression: float array of shape (n_rows, 3); each row is [y[k], u[k-delay], 1]
            for k = delay_samples .. n-2. Column order matters: it matches the parameter
            vector [a, b, c].
        target: float array of shape (n_rows,); the value y[k+1] predicted by each row.
        Both arrays are empty when there are not enough samples to form a single row,
        which keeps the caller from fitting on zero data.
    """
    # Last row index k we can form, because the target y[k+1] must exist.
    last_k = len(controller_output) - 2
    # Need at least one k with k >= delay_samples, hence delay_samples <= n-2.
    if last_k < delay_samples:
        # Keep the empty regression matrix wide enough for the solver's 3 columns.
        return np.empty((0, _REGRESSION_COLUMNS)), np.empty(0)
    # Valid row indices k, from the delay up to the last usable index.
    indices = np.arange(delay_samples, last_k + 1)
    # Present output y[k]: the autoregressive term.
    current_output = process_value[indices]
    # Shift the input back by the dead time so u[k-delay] lines up with y[k].
    delayed_input = controller_output[indices - delay_samples]
    # Ones column: the constant term c of the affine model (intercept).
    ones = np.ones_like(current_output)
    # Stack columns in [y[k], u[k-delay], 1] order as required by the solver.
    regression = np.column_stack((current_output, delayed_input, ones))
    # One-step-ahead target y[k+1], shifted forward one sample.
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

    The discrete model being converted is the first-order difference equation
    y[k] = a * y[k-1] + b * u[k-1], sampled every dt_s seconds. FOPDT stands for
    "first order plus dead time": a continuous-time model with three parameters,
    a steady-state gain, one time constant and a pure transport delay.
    """
    # Discrete-time stability for a first-order model requires 0 < a < 1:
    # a < 0 corresponds to oscillation at the Nyquist frequency and a > 1
    # to instability. Values outside this range would give a non-physical
    # continuous-time time constant.
    if not 0.0 < discrete_a < 1.0:
        return None

    # Steady-state gain: with y[k] = y[k-1] = y_ss and u = 1,
    # y_ss = a*y_ss + b, giving gain = b/(1-a). Units: output per input.
    gain = discrete_b / (1.0 - discrete_a)

    # A negative or zero gain is not a physical process for this caller, so the
    # conversion is rejected rather than silently returned.
    if gain <= 0.0:
        return None

    # The discrete pole a corresponds to a continuous-time pole through
    # z = exp(s*dt_s), so a = exp(-dt_s / tau). Solving for tau gives
    # tau = -dt_s / ln(a); with 0 < a < 1, ln(a) < 0, so tau > 0.
    time_constant_s = -dt_s / np.log(discrete_a)

    # Dead time in seconds. A zero-sample delay is bumped to one sample
    # so the FOPDT model has a strictly positive delay_s.
    delay_s = max(delay_samples, 1) * dt_s

    # Return plain Python floats because FopdtModel expects them; numpy
    # scalars would be valid but less predictable for the caller.
    return FopdtModel(gain=gain, time_constant_s=float(time_constant_s), delay_s=float(delay_s))
