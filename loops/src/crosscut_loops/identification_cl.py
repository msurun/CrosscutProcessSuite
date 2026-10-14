"""Closed-loop identification of first-order-plus-dead-time (FOPDT) models.

Problem
-------
When the controller is in AUTO, the manipulated variable u is computed from the
error y_sp - y, so u is correlated with the unmeasured disturbance that also
drives y. Ordinary least squares on the pair (u, y) then attributes part of the
disturbance to the input and the estimated gain comes out biased (see
experiments/exp00 and exp07: the same plant yields a different gain in AUTO).

Method
------
Two-stage least squares, also called instrumental variables. The setpoint y_sp
is exogenous: the operator sets it by hand, so it is independent of the
disturbance. We therefore use past setpoint samples y_sp[k-j] as instruments Z
for the regressors X = [y[k], u[k-d]]. The first stage projects X on Z
(X_hat = Z @ lstsq(Z, X)); the second stage regresses y[k+1] on [X_hat, 1].
The projection keeps only the part of u that the setpoint explains, which
removes the disturbance correlation and the bias.

Model
-----
Same discrete model as identification.py, fitted per candidate delay d:

    y[k+1] = a * y[k] + b * u[k-d] + c

The continuous FOPDT parameters follow from the discrete coefficients:

    gain            = b / (1 - a)
    time_constant_s = -dt_s / ln(a)
    delay_s         = max(d, 1) * dt_s

Limits
------
* The setpoint must move; a constant setpoint carries no information to use as
  an instrument.
* The delay is quantised to whole samples, so delay_s is a multiple of dt_s.
* The first stage needs enough explanatory power: if the setpoint explains
  almost none of the input, the projected regressors are nearly noise and the
  second stage is unreliable. INSTRUMENT_LAGS trades this against sample count.
"""

from __future__ import annotations

import numpy as np

from crosscut_loops.identification import _to_fopdt, _validate_inputs
from crosscut_loops.tuning_rules import FopdtModel

# Number of past setpoint samples used as instruments: y_sp[k], y_sp[k-1], ...,
# y_sp[k-INSTRUMENT_LAGS+1]. The controller needs a few samples to act on a
# setpoint change, so the recent history carries the useful information.
INSTRUMENT_LAGS = 40

# Columns of the second-stage regression matrix y[k+1] ~ a*y[k] + b*u[k-d] + c.
_REGRESSION_COLUMNS = 3

# A setpoint is considered excited when its spread is at least this fraction of
# the output spread. Below it the instrument set carries no usable signal.
MIN_SETPOINT_STD_FRACTION = 1e-3

# Each first-stage row needs one observation per instrument. Requiring three
# times as many rows as instruments keeps the projection well conditioned.
MIN_ROWS_PER_INSTRUMENT = 3

_NO_MODEL_MESSAGE = "no physically meaningful closed-loop model found"
_FLAT_SETPOINT_MESSAGE = (
    "the setpoint did not move: closed-loop identification needs setpoint excitation"
)


def identify_fopdt_closed_loop(
    u: np.ndarray,
    y: np.ndarray,
    sp: np.ndarray,
    dt_s: float,
    max_delay_s: float,
) -> FopdtModel:
    """Identify a FOPDT model from data recorded while the controller was in AUTO.

    The model is "First Order Plus Dead Time": the output reacts to the input
    with a first-order lag, after waiting a pure transport delay. In continuous
    time its Laplace form is ``G(s) = K * exp(-theta * s) / (tau * s + 1)``,
    where ``K`` is the gain (output units per input unit), ``tau`` the time
    constant in seconds and ``theta`` the dead time in seconds.

    The dead time is scanned over whole sampling periods. For each candidate the
    coefficients are found by two-stage least squares, using past setpoint
    samples as instruments, because in AUTO the input is correlated with the
    disturbance. The candidate with the smallest residual variance wins.

    Args:
        u: Controller output samples (the input to the plant), one per instant.
        y: Measured process value samples, the same length as ``u``.
        sp: Setpoint samples, the same length as ``u``; must have moved.
        dt_s: Sampling period in seconds, positive.
        max_delay_s: Largest dead time to scan, in seconds, positive.

    Returns:
        The ``FopdtModel`` whose discrete equivalent best fits the data.

    Raises:
        ValueError: If the signals are malformed, the setpoint is flat, or no
            candidate delay yields a physically meaningful model.
    """
    # codecheck: allow too-many-parameters (public signature used by callers and tests)
    _validate_inputs(u, y, dt_s, max_delay_s)
    _validate_setpoint(sp, u, y)
    # Delays are only tested at whole sampling instants, so convert the bound
    # from seconds to a sample count: 1.0 s at dt_s = 0.1 s gives 10 samples.
    max_delay_samples = int(round(max_delay_s / dt_s))
    return _fit_best_delay_closed_loop(u, y, sp, dt_s, max_delay_samples)


def _validate_setpoint(sp: np.ndarray, u: np.ndarray, y: np.ndarray) -> None:
    """Raise ValueError if the setpoint is unusable as an instrument source.

    Two failure modes are checked: a setpoint that does not line up with the
    other signals (wrong length or non-finite values) and a setpoint that never
    moved. A flat setpoint is independent of nothing, so the instruments would
    be constant and the projected regressors would collapse.

    Raises:
        ValueError: If the setpoint length or values are bad, or it never moved.
    """
    setpoint = np.asarray(sp, dtype=float)
    if setpoint.shape != u.shape:
        raise ValueError(f"sp must have the same shape as u and y, got {setpoint.shape}")
    if not np.all(np.isfinite(setpoint)):
        raise ValueError("sp must contain only finite values (no NaN or inf)")
    _check_setpoint_moved(setpoint, y)


def _check_setpoint_moved(setpoint: np.ndarray, y: np.ndarray) -> None:
    """Raise ValueError if the setpoint carries no excitation to use as instrument.

    A setpoint that never moves gives constant instruments; a very small
    movement relative to the output spread is indistinguishable from noise in
    the data, so it is rejected too.
    """
    output_spread = float(np.std(np.asarray(y, dtype=float)))
    setpoint_spread = float(np.std(setpoint))
    if np.ptp(setpoint) == 0 or setpoint_spread < MIN_SETPOINT_STD_FRACTION * output_spread:
        raise ValueError(_FLAT_SETPOINT_MESSAGE)


def _fit_best_delay_closed_loop(
    u: np.ndarray,
    y: np.ndarray,
    sp: np.ndarray,
    dt_s: float,
    max_delay_samples: int,
) -> FopdtModel:
    """Return the model with the smallest projected residual over every candidate delay.

    Every candidate delay is scored on the SAME rows (the rows that exist for the largest
    delay), otherwise a long delay would be scored on fewer samples than a short one and the
    scores could not be compared.

    Args:
        u: Controller output samples.
        y: Process value samples, same length as ``u``.
        sp: Setpoint samples, same length as ``u``.
        dt_s: Sampling period in seconds.
        max_delay_samples: Largest dead time to try, in number of samples.

    Returns:
        The best-fitting physically valid model.

    Raises:
        ValueError: If no delay produced a physically meaningful model.
    """
    first_row = max_delay_samples + INSTRUMENT_LAGS - 1
    best_model: FopdtModel | None = None
    best_score = np.inf
    for delay_samples in range(max_delay_samples + 1):
        candidate = _fit_one_delay_iv(u, y, sp, (delay_samples, first_row))
        if candidate is None:
            continue
        coefficients, score = candidate
        model = _to_fopdt(coefficients[0], coefficients[1], dt_s, delay_samples)
        if model is not None and score < best_score:
            best_score = score
            best_model = model
    if best_model is None:
        raise ValueError(_NO_MODEL_MESSAGE)
    return best_model


def _fit_one_delay_iv(
    u: np.ndarray,
    y: np.ndarray,
    sp: np.ndarray,
    delay_and_first_row: tuple[int, int],
) -> tuple[np.ndarray, float] | None:
    """Two-stage least squares for one delay; None when the fit is impossible.

    ``delay_and_first_row`` is (delay in samples, index of the first usable row).

    Returns:
        (coefficients, score) where coefficients are (a, b, c) and score is the mean squared
        residual on the setpoint-explained part of the output (see ``_two_stage_fit``), or
        None if the delay leaves too few rows.
    """
    delay_samples, first_row = delay_and_first_row
    rows = _build_rows_iv(u, y, sp, (delay_samples, first_row))
    if rows is None:
        return None
    regressors, target, instruments = rows
    return _two_stage_fit(regressors, target, instruments)


def _build_rows_iv(
    u: np.ndarray,
    y: np.ndarray,
    sp: np.ndarray,
    delay_and_first_row: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Build (regressors, target, instruments) for the rows ``first_row`` .. n-2.

    ``first_row`` must be at least ``delay + INSTRUMENT_LAGS - 1`` so that every past setpoint
    sample sp[k-j] for j in 0..INSTRUMENT_LAGS-1 and every u[k-delay] still exists; the last row is
    n-2 because the target y[k+1] must exist.

    Returns:
        regressors: shape (n_rows, 2), each row [y[k], u[k-delay]].
        target: shape (n_rows,), the value y[k+1] of each row.
        instruments: shape (n_rows, INSTRUMENT_LAGS + 1), the setpoint lags and
            a trailing ones column.
        None when fewer than the required number of rows can be formed.
    """
    delay_samples, first_row = delay_and_first_row
    if first_row > len(y) - 2 or first_row < delay_samples + INSTRUMENT_LAGS - 1:
        return None
    indices = np.arange(first_row, len(y) - 1)
    # Each row consumes INSTRUMENT_LAGS + 1 unknowns in the first stage, so
    # demand several rows per unknown to keep the projection conditioned.
    if indices.size < MIN_ROWS_PER_INSTRUMENT * (INSTRUMENT_LAGS + 1):
        return None
    return (
        _build_regressors(u, y, indices, delay_samples),
        y[indices + 1],
        _build_instruments(sp, indices),
    )


def _build_regressors(
    u: np.ndarray,
    y: np.ndarray,
    indices: np.ndarray,
    delay_samples: int,
) -> np.ndarray:
    """Stack the two regressors [y[k], u[k-delay]] into a (n_rows, 2) matrix."""
    return np.column_stack((y[indices], u[indices - delay_samples]))


def _build_instruments(sp: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """Stack the setpoint lags sp[k-j] plus a ones column into the instrument matrix."""
    # Lag j shifts the setpoint back j samples; indices >= INSTRUMENT_LAGS - 1
    # guarantees the shift stays inside the array.
    lags = [sp[indices - lag] for lag in range(INSTRUMENT_LAGS)]
    lags.append(np.ones_like(indices, dtype=float))
    return np.column_stack(lags)


def _two_stage_fit(
    regressors: np.ndarray,
    target: np.ndarray,
    instruments: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Return the (a, b, c) coefficients of the two-stage fit and the delay score.

    First stage: project the regressors AND the target on the instruments (X_hat, t_hat). The
    projection keeps the part that the exogenous setpoint explains and drops the part
    correlated with the disturbance. Second stage: regress t_hat on [X_hat, 1] by least squares.

    The score is the mean squared residual of THAT regression (the setpoint-explained part of
    the output against the setpoint-explained part of the model). Scoring on the raw output
    instead let long delays win (delay error of about 14 samples in exp07, seeds 1-20): the
    disturbance dominates the raw residual and hides the delay, while the projected residual
    does not contain it.
    """
    columns = np.column_stack((regressors, target))
    first_stage, _, _, _ = np.linalg.lstsq(instruments, columns, rcond=None)
    projected = instruments @ first_stage
    design = np.column_stack((projected[:, :-1], np.ones(len(target))))
    coefficients, _, _, _ = np.linalg.lstsq(design, projected[:, -1], rcond=None)
    residual = projected[:, -1] - design @ coefficients
    return np.asarray(coefficients, dtype=float), float(np.mean(residual**2))
