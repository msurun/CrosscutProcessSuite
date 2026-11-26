"""Discretise a matrix of FOPDT paths for the Python MPC reference.

Each path has its own lag and delay; all signals are deviations in engineering units.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]


@dataclass(frozen=True)
class FopdtModel:
    """Store CV-by-input gains, time constants/delays in seconds and cycle seconds.

    Inputs can include measured disturbances after the manipulated-variable columns.
    """

    gains: Array
    time_constants_s: Array
    dead_times_s: Array
    cycle_s: float

    def __post_init__(self) -> None:
        """Copy coefficients and reject incomplete or nonphysical path matrices."""
        for name in ("gains", "time_constants_s", "dead_times_s"):
            values = np.array(getattr(self, name), dtype=float, copy=True)
            if values.ndim != 2 or not values.size or not np.all(np.isfinite(values)):
                raise ValueError(f"{name} must be a nonempty finite CV-by-input matrix")
            values.setflags(write=False)
            object.__setattr__(self, name, values)
        if self.gains.shape != self.time_constants_s.shape or (
            self.gains.shape != self.dead_times_s.shape
        ):
            raise ValueError("Every input/CV pair needs gain, time constant and dead time")
        if not np.isfinite(self.cycle_s) or self.cycle_s <= 0:
            raise ValueError("cycle_s must be finite and positive")
        if np.any(self.time_constants_s <= 0) or np.any(self.dead_times_s < 0):
            raise ValueError("Time constants must be positive and dead times nonnegative")

    def delay_samples(self) -> NDArray[np.int64]:
        """Return nearest whole-sample delays, matching the simulator's convention."""
        # theta [s] / Ts [s/sample] gives samples; ties round to even like Python round.
        return np.rint(self.dead_times_s / self.cycle_s).astype(np.int64)

    def step_response(self, horizon: int) -> Array:
        """Return response after 1..horizon calls, shape (horizon, CV, input)."""
        if horizon < 1:
            raise ValueError("Prediction horizon must be positive")
        # ZOH: S[j,c,m] = K[c,m]*(1-exp(-max(j-delay,0)*Ts/tau)).
        # K and S have CV-unit/input-unit; j starts at one (next sample).
        elapsed = np.maximum(np.arange(1, horizon + 1)[:, None, None] - self.delay_samples(), 0)
        return np.asarray(self.gains * (1 - np.exp(
            -elapsed * self.cycle_s / self.time_constants_s)), dtype=float)


@dataclass(frozen=True)
class ModelState:
    """Store path outputs (CV,input) and newest-first input history (delay,input)."""

    paths: Array
    history: Array


def initial_model_state(model: FopdtModel, inputs: Array) -> ModelState:
    """Build a steady-state lag and delay history for the supplied input deviations."""
    # x[c,m] = K[c,m]*u[m] [CV units]; all delayed samples start at current input.
    depth = int(np.max(model.delay_samples())) + 1
    return ModelState(model.gains * inputs, np.tile(inputs, (depth, 1)))


def advance(model: FopdtModel, state: ModelState, inputs: Array) -> ModelState:
    """Advance exact ZOH path states by one sample without mutating arguments."""
    # x_next = a*x + K*(1-a)*u_delayed, a=exp(-Ts/tau); x has CV units.
    # Row zero is the input applied now, so a zero delay reacts in this call.
    history = np.vstack((inputs, state.history))
    delayed = history[model.delay_samples(), np.arange(model.gains.shape[1])]
    decay = np.exp(-model.cycle_s / model.time_constants_s)
    paths = decay * state.paths + model.gains * (1 - decay) * delayed
    return ModelState(paths, history[:-1].copy())


def free_response(model: FopdtModel, state: ModelState, request: tuple[Array, int]) -> Array:
    """Predict with held inputs; return (horizon,CV) deviations in CV units."""
    inputs, horizon = request
    predictions = []
    for _ in range(horizon):
        state = advance(model, state, inputs)
        predictions.append(state.paths.sum(axis=1))
    return np.array(predictions)


def move_matrix(model: FopdtModel, horizons: tuple[int, int], count: int) -> Array:
    """Return the convolution matrix mapping time-major MV increments to CVs."""
    prediction, moves = horizons
    response = model.step_response(prediction)[:, :, :count]
    matrix = np.zeros((prediction, model.gains.shape[0], moves, count))
    # Each move contributes its shifted step response: y[j] = free[j]+sum S[j-i]*du[i].
    # Flattening time first keeps constraints, weights and predictions in the same order.
    for i in range(moves):
        matrix[i:, :, i, :] = response[:prediction - i]
    return matrix.reshape(prediction * model.gains.shape[0], moves * count)
