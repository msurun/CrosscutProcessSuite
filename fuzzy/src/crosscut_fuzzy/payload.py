"""JSON-ready results of the fuzzy system for the web screens: one what-if sample and a replay.

NaN has no JSON form, so a missing crisp output (no rule fired) is returned as ``None``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from crosscut_fuzzy.backtest import BacktestMetrics, BacktestSettings, backtest, split_halves
from crosscut_fuzzy.inference import Inference, evaluate
from crosscut_fuzzy.model import FuzzyModelError, FuzzySystem

DOMINANT_MIN_STRENGTH = 0.05  # a rule counts as "explaining" the output above this firing strength
MAX_REPLAY_POINTS = 5000


def infer_payload(system: FuzzySystem, values: Mapping[str, float]) -> dict[str, Any]:
    """Evaluate one sample: term degrees, rule firing, the aggregated shape and the crisp output."""
    missing = [variable.id for variable in system.inputs if variable.id not in values]
    if missing:
        raise FuzzyModelError(f"missing input values: {', '.join(missing)}")
    arrays = {key: np.array([value], dtype=float) for key, value in values.items()}
    result = evaluate(system, arrays)
    firing = {rule_id: float(strength[0]) for rule_id, strength in result.firing.items()}
    return {
        "inputs": {variable.id: float(values[variable.id]) for variable in system.inputs},
        "degrees": _degrees(result),
        "firing": firing,
        "dominant": _dominant(firing),
        "outputs": _outputs(result),
    }


def _degrees(result: Inference) -> dict[str, dict[str, float]]:
    """Membership degree of the sample in every term of every input."""
    return {
        variable_id: {term: float(degree[0]) for term, degree in terms.items()}
        for variable_id, terms in result.degrees.items()
    }


def _dominant(firing: Mapping[str, float]) -> list[str]:
    """Rules that fire noticeably, strongest first: the one-line "why" of a decision."""
    strong = [(strength, rule_id) for rule_id, strength in firing.items()]
    strong = [item for item in strong if item[0] > DOMINANT_MIN_STRENGTH]
    return [rule_id for _, rule_id in sorted(strong, reverse=True)]


def _outputs(result: Inference) -> dict[str, dict[str, Any]]:
    """Crisp value, universe and aggregated membership shape of every output.

    `Inference` is the result of a Mamdani fuzzy inference system: several output
    variables, each one an `OutputResult` holding three arrays produced by defuzzification.

    Each output is serialised as a JSON-friendly dict with these keys:
      "crisp": the single defuzzified number, e.g. the centre of gravity of the
        aggregated shape, in the output variable's own unit (no unit is attached).
      "universe": the sampled x-axis of the output variable, as a list of floats.
        Same length as "aggregated"; both are `numpy` arrays turned into lists so
        `json.dumps` can serialise them.
      "aggregated": the membership degree (0.0 to 1.0) of the aggregated fuzzy set
        at each point of "universe".

    `[0]` is taken because the arrays have one row per sample and this payload evaluates
    exactly one sample.
    """
    return {
        output_id: {
            "crisp": _json_number(float(output.crisp[0])),
            "universe": output.universe.tolist(),
            "aggregated": output.aggregated[0].tolist(),
        }
        for output_id, output in result.outputs.items()
    }


def _json_number(value: float) -> float | None:
    """The number, or None for NaN."""
    return None if np.isnan(value) else value


def replay_payload(
    system: FuzzySystem,
    t_ns: np.ndarray,
    columns: Mapping[str, np.ndarray],
    max_points: int,
) -> dict[str, Any]:
    """Run the system over recorded data; the result is thinned to at most ``max_points`` samples.

    A "replay" re-evaluates a fuzzy model against a recording (a recorded dataset) so it can be
    compared with what really happened. Every series is sampled down to at most
    ``max_points`` points before being serialised, because sending a full recording to the
    front end would be far more data than a chart can show.

    Args:
        system: The fuzzy model whose inputs and outputs define which series to read.
        t_ns: Timestamps of the recording, in nanoseconds since the epoch, one per sample.
        columns: The recording itself, mapping a column name to that column's values. A model
            input finds its data here under the column named by its tag.
        max_points: Upper bound on the number of samples returned for each series.

    Returns:
        A JSON-friendly mapping with the time axis ``t``, the model inputs, the model outputs and
        the recorded (actual) output values, all sharing the thinned time axis.

    Raises:
        FuzzyModelError: when an input has no tag or a tag is not in the data.
    """
    # Thinning uses the smaller of the caller's request and the hard server-side
    # limit, so the chart receives at most the number of points it needs.
    keep = _thinned_indices(len(t_ns), min(max_points, MAX_REPLAY_POINTS))
    # Read one recording column per model input. Each input is looked up by its tag, then indexed
    # with `keep` so every series in the result is aligned on the same (thinned) time axis.
    inputs = {
        variable.id: _column(variable.id, variable.tag, columns)[keep] for variable in system.inputs
    }
    # Evaluate the model on the thinned inputs, producing a crisp value per output.
    result = evaluate(system, inputs)
    return {
        # `t` is the time axis in nanoseconds; all three payload series below share it.
        "t": t_ns[keep].tolist(),
        # Model inputs, keyed by variable id, are already thinned by `keep`.
        "inputs": {key: _json_list(values) for key, values in inputs.items()},
        # Each output object carries its crisp (defuzzified) value; that is the series plotted.
        "outputs": {key: _json_list(out.crisp) for key, out in result.outputs.items()},
        # The recorded output for the same timestamps, for comparison with the model's output.
        "actual": _actual_series(system, columns, keep),
    }


def _thinned_indices(n_samples: int, max_points: int) -> np.ndarray:
    """Evenly spread sample indices, at most ``max_points`` of them."""
    return np.linspace(0, n_samples - 1, min(n_samples, max_points)).astype(int)


def _column(variable_id: str, tag: str | None, columns: Mapping[str, np.ndarray]) -> np.ndarray:
    """Return the data column feeding a variable.

    In a fuzzy model, each variable carries a ``tag`` naming the measured signal
    (for example a sensor channel) it reads from. ``columns`` is the recorded
    dataset, mapping every tag to one array of samples; all arrays share the same
    length, one entry per sample of the recording, so they can be replayed
    sample by sample.

    Returns:
        The samples for ``tag``, in dataset order. The array is not copied.

    Raises:
        FuzzyModelError: if the variable has no tag, or the tag is missing from
            the dataset.
    """
    if tag is None:
        raise FuzzyModelError(f"variable {variable_id} has no tag, so it cannot be replayed")
    if tag not in columns:
        raise FuzzyModelError(f"tag not in the dataset: {tag}")
    return columns[tag]


def _actual_series(
    system: FuzzySystem, columns: Mapping[str, np.ndarray], keep: np.ndarray
) -> dict[str, list[float | None]]:
    """What the outputs' tags really did, for outputs that name a tag present in the data.

    Ground truth for the fuzzy system's outputs: the observed value of the sensor tag the
    output stands for, restricted to the kept rows, in the shape the report writer wants.

    Returns a dict mapping each output's ``id`` to its observed series as a list of floats,
    with ``None`` for missing samples. Outputs without a usable tag are left out entirely.
    """
    return {
        variable.id: _json_list(columns[variable.tag][keep])
        for variable in system.outputs
        if variable.tag is not None and variable.tag in columns
    }


def _json_list(values: np.ndarray) -> list[float | None]:
    """Values as a JSON-safe list (NaN becomes None)."""
    return [None if np.isnan(value) else float(value) for value in values]


NS_PER_S = 1e9
MIN_BACKTEST_SAMPLES = 3


# codecheck: allow too-many-parameters (public signature used by crosscut_api.fuzzy_routes)
def backtest_payload(
    system: FuzzySystem,
    t_ns: np.ndarray,
    columns: Mapping[str, np.ndarray],
    output_id: str,
    settings: BacktestSettings,
) -> dict[str, Any]:
    """Score one output's advice against the operator's moves of the SP tag it stands for.

    The output's ``tag`` must be the SP tag the operator writes (like ``mill_feed_sp``): its
    jumps are the operator moves. The whole recording is scored at once, and again for each
    half, so the engineer sees whether the first half (where rules were tuned) differs from
    the second. Advisory only: nothing is written anywhere.

    Raises:
        FuzzyModelError: when the output is unknown, has no tag in the data, or the recording
            is too short to have a sampling period.
    """
    sp_tag = _sp_tag(system, columns, output_id)
    dt_s = _sampling_period_s(t_ns)
    inputs = {item.id: _column(item.id, item.tag, columns) for item in system.inputs}
    advice = evaluate(system, inputs).outputs[output_id].crisp
    sp = columns[sp_tag]
    first, second = split_halves(len(sp))
    return {
        "output": output_id,
        "all": _metrics_json(backtest(advice, sp, dt_s, settings)),
        "first_half": _metrics_json(backtest(advice, sp, dt_s, settings, first)),
        "second_half": _metrics_json(backtest(advice, sp, dt_s, settings, second)),
    }


def _sampling_period_s(t_ns: np.ndarray) -> float:
    """Median spacing of the timestamps (ns) in seconds; FuzzyModelError for a too short record."""
    if len(t_ns) < MIN_BACKTEST_SAMPLES:
        raise FuzzyModelError("the recording is too short for a backtest")
    return float(np.median(np.diff(t_ns))) / NS_PER_S


def _sp_tag(system: FuzzySystem, columns: Mapping[str, np.ndarray], output_id: str) -> str:
    """The data tag of output ``output_id``; FuzzyModelError when it is unknown or not recorded."""
    variable = next((item for item in system.outputs if item.id == output_id), None)
    if variable is None or variable.tag is None or variable.tag not in columns:
        tag = variable.tag if variable else None
        message = f"output {output_id} (tag {tag}) has no SP column in the data to compare with"
        raise FuzzyModelError(message)
    return variable.tag


def _metrics_json(metrics: BacktestMetrics) -> dict[str, float | int | None]:
    """The metrics with NaN turned into None, as JSON needs."""
    return {
        "n_moves": metrics.n_moves,
        "sign_agreement": _json_number(metrics.sign_agreement),
        "correlation": _json_number(metrics.correlation),
        "majority_share": _json_number(metrics.majority_share),
        "silent_share": _json_number(metrics.silent_share),
    }
