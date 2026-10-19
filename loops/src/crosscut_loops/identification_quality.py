"""Judge how far a FOPDT fit produced by identify_fopdt can be trusted.

A high one-step-ahead R2 says little on slow loops: the prediction is anchored to the
last measured y, so it can look excellent even when the gain is wrong. This module
re-simulates the model in open loop (free run) and counts the input moves that carry
enough energy to identify a gain.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp

import numpy as np
from numpy.typing import ArrayLike

from crosscut_loops.tuning_rules import FopdtModel

MIN_EXCITATION_EVENTS = 2  # fewer distinct input moves leave the gain unidentifiable
MIN_FREE_RUN_R2 = 0.6  # free-run R2 below this means the model does not reproduce the record
MOVE_NOISE_FACTOR = 5.0  # a move must exceed this many noise standard deviations of dU
MOVE_RANGE_FRACTION = 0.02  # ... and this fraction of the input range

# Consistency factor of the median absolute deviation for a normal distribution:
# sigma = 1.4826 * median(|x - median(x)|). It is robust to the few large dU that
# are exactly the moves we want to keep.
MAD_TO_SIGMA = 1.4826
SQRT_TWO = 2.0**0.5


@dataclass(frozen=True)
class FitAssessment:
    """Verdict on a FOPDT fit: free-run quality and input excitation."""

    free_run_r2: float
    excitation_events: int
    low_confidence: bool
    reasons: tuple[str, ...]


def free_run_r2(
    model: FopdtModel, controller_output: ArrayLike, process_value: ArrayLike, dt_s: float
) -> float:
    """Coefficient of determination of an open-loop simulation of `model`.

    The simulation feeds back only the simulated output, never the measured y, so a
    wrong gain shows up as a large error instead of being hidden by feedback.
    Args:
        model: fitted first-order-plus-dead-time model.
        controller_output: input samples u, in the units the model gain refers to.
        process_value: measured output samples y, one per input sample.
        dt_s: sampling period in seconds.
    Returns:
        1 - SSE/SST, or 0.0 when y is constant (SST is zero, so R2 is undefined).
    """
    u_values = np.asarray(controller_output, dtype=float)
    y_values = np.asarray(process_value, dtype=float)

    y_sim = _simulate_open_loop(model, u_values, y_values, dt_s)

    total_sum_squares = float(np.sum((y_values - np.mean(y_values)) ** 2))
    if total_sum_squares == 0.0:
        return 0.0

    residual_sum_squares = float(np.sum((y_values - y_sim) ** 2))
    return 1.0 - residual_sum_squares / total_sum_squares


def _simulate_open_loop(
    model: FopdtModel, u_values: np.ndarray, y_values: np.ndarray, dt_s: float
) -> np.ndarray:
    """Return y_sim, the model output driven only by u (no correction from y).

    Discretised at the sample rate: decay = exp(-dt_s/tau) is the fraction kept after one
    step, delay_samples = round(delay_s/dt_s) is the dead time in samples, u[0] is the
    input the response is measured from, and y[0] anchors the absolute level.
    """
    decay = exp(-dt_s / model.time_constant_s)
    delay_samples = round(model.delay_s / dt_s)

    y_sim = np.empty_like(y_values)
    y_sim[0] = 0.0  # deviation from y[0]; the offset is added at the end
    input_origin = u_values[0]
    for k in range(len(y_values) - 1):
        delayed_u = u_values[max(k - delay_samples, 0)]
        y_sim[k + 1] = decay * y_sim[k] + model.gain * (1.0 - decay) * (delayed_u - input_origin)

    return np.asarray(y_sim + y_values[0], dtype=float)


def count_excitation_events(controller_output: ArrayLike) -> int:
    """Number of distinct input moves large enough to identify a gain.

    A move sample is a |dU| above both a noise floor and a fraction of the input range.
    Adjacent move samples are one event (a ramp counts once, not once per sample).
    Returns 0 both when the signal is flat and when no sample clears the threshold.
    """
    u_values = np.asarray(controller_output, dtype=float)
    increments = np.diff(u_values)

    threshold = _move_threshold(u_values, increments)
    if threshold == 0.0:
        return 0

    is_move = np.abs(increments) > threshold
    # An event starts where a move follows a non-move (or the beginning of the record).
    event_starts = np.count_nonzero(is_move & ~np.concatenate(([False], is_move[:-1])))
    return int(event_starts)


def _move_threshold(u_values: np.ndarray, increments: np.ndarray) -> float:
    """Smallest |dU| that counts as a deliberate move, in input units.

    Two floors are combined with max: a robust noise estimate (MAD, which ignores the
    moves themselves) scaled by MOVE_NOISE_FACTOR, and a fixed fraction of the input
    span in case the signal is so clean that the noise floor is tiny.
    """
    if increments.size == 0:
        return 0.0
    median_increment = np.median(increments)
    noise_sd = MAD_TO_SIGMA * np.median(np.abs(increments - median_increment))
    range_floor = MOVE_RANGE_FRACTION * (np.max(u_values) - np.min(u_values))
    return max(MOVE_NOISE_FACTOR * float(noise_sd), float(range_floor))


def assess_fit(
    model: FopdtModel, controller_output: ArrayLike, process_value: ArrayLike, dt_s: float
) -> FitAssessment:
    """Decide whether a FOPDT fit is trustworthy and explain every failure.

    Fails on too few input moves (the gain is then unidentifiable) or on a free-run R2
    below MIN_FREE_RUN_R2 (the model does not reproduce the record in open loop).
    Returns:
        A FitAssessment; `reasons` is empty when the fit passes both criteria.
    """
    r2 = free_run_r2(model, controller_output, process_value, dt_s)
    events = count_excitation_events(controller_output)

    reasons: list[str] = []
    if events < MIN_EXCITATION_EVENTS:
        reasons.append(f"only {events} input move(s); need at least {MIN_EXCITATION_EVENTS}")
    if r2 < MIN_FREE_RUN_R2:
        reasons.append(f"free-run R2 {r2:.2f} below {MIN_FREE_RUN_R2}")

    return FitAssessment(
        free_run_r2=r2,
        excitation_events=events,
        low_confidence=bool(reasons),
        reasons=tuple(reasons),
    )


def pv_noise_sd(process_value: ArrayLike) -> float:
    """Estimate the standard deviation of white measurement noise on ``process_value``.

    Differencing removes the slow process movement, so what is left is mostly noise; for
    white noise var(dy) = 2 var(noise), hence the division by sqrt(2). The MAD ignores
    the few large differences at real process moves.
    """
    increments = np.diff(np.asarray(process_value, dtype=float))
    if increments.size == 0:
        return 0.0
    spread = MAD_TO_SIGMA * np.median(np.abs(increments - np.median(increments)))
    return float(spread) / SQRT_TWO
