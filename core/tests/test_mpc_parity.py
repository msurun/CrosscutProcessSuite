"""Compare the C++ MPC cycle with the independent Python/OSQP reference.

Synthetic engineering-unit inputs exercise both QPs and explicit host state.
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter

import numpy as np
import pytest
from crosscut_mpc import Controller, CycleInputs, FopdtModel, Limits, Settings, cycle, initialise

module_dir = os.environ.get("CROSSCUT_CORE_MODULE_DIR")
if module_dir:
    sys.path.insert(0, str(Path(module_dir)))

crosscut_core = pytest.importorskip("crosscut_core")

# Independent iterative solvers may stop at different residuals. These tolerances
# bound moves/predictions in engineering units, not the hard-bound certificate (2e-5).
PARITY_ABSOLUTE = 2e-3
PARITY_RELATIVE = 2e-3
MAXIMUM_SOLVE_S = 3.0  # Half of the allowed 6 s, which is 10% of a 60 s cycle.


def make_controller(gains: np.ndarray, count: int | None = None) -> Controller:
    """Build a feasible synthetic model with nonrestrictive CV bands."""
    outputs, inputs = gains.shape
    count = inputs if count is None else count
    limits = Limits(
        mv_lower=np.full(count, -5.0), mv_upper=np.full(count, 5.0),
        cv_lower=np.full(outputs, -100.0), cv_upper=np.full(outputs, 100.0),
        priorities=np.arange(outputs), move_max=np.full(count, 0.5),
        rate_max=np.full(count, 0.01), target_rate=np.full(outputs, 0.1),
        funnel_start=np.full(outputs, 200.0), funnel_end=np.full(outputs, 100.0),
    )
    model = FopdtModel(gains, np.full(gains.shape, 240.0), np.full(gains.shape, 60.0), 60.0)
    return Controller(model, limits, Settings(25, 5, 0.2))


def wood_berry() -> Controller:
    """Return the public Wood-Berry 2x2 lag/delay model with seconds-based times."""
    controller = make_controller(np.array([[12.8, -18.9], [6.6, -19.4]]))
    # Each CV/input pair has its own FOPDT path: K in CV/MV units, tau/theta in s.
    model = FopdtModel(controller.model.gains, 60 * np.array([[16.7, 21.0], [10.9, 14.4]]),
                       60 * np.array([[1.0, 3.0], [7.0, 3.0]]), 60.0)
    return replace(controller, model=model, settings=Settings(60, 8, 1.0))


def inputs_for(controller: Controller) -> CycleInputs:
    """Create nonzero CV targets and a small unmeasured load at zero MV deviation."""
    outputs, inputs = controller.model.gains.shape
    count = len(controller.limits.mv_lower)
    return CycleInputs(np.full(outputs, 0.15), np.zeros(count), np.full(outputs, 1.0),
                       tuple(np.full(inputs - count, 0.2)))


def assert_result_parity(expected: object, actual: dict) -> None:
    """Compare status exactly and all engineering-unit decisions within the tolerance."""
    values = asdict(expected)
    assert actual["status"] == values["status"]
    assert tuple(actual["relaxed_cvs"]) == values["relaxed_cvs"]
    for name in ("moves", "move_plan", "predicted_cvs", "steady_mvs", "target_cvs", "bias"):
        np.testing.assert_allclose(actual[name], values[name], atol=PARITY_ABSOLUTE,
                                   rtol=PARITY_RELATIVE, err_msg=name)


def run_parity(controller: Controller, cycles: int = 3, refuse: bool = False) -> list[dict]:
    """Run independent states with shared MV read-back, optionally refusing every move."""
    inputs = inputs_for(controller)
    python_state = initialise(controller, inputs)
    configuration = asdict(controller)
    cpp_state = crosscut_core.mpc_initialise(configuration, asdict(inputs))
    results = []
    for _ in range(cycles):
        expected, python_state = cycle(controller, python_state, inputs)
        actual, cpp_state = crosscut_core.mpc_cycle(configuration, cpp_state, asdict(inputs))
        assert_result_parity(expected, actual)
        results.append(actual)
        if not refuse:
            inputs = replace(inputs, actual_mvs=np.asarray(expected.moves))
    return results


def changed_limits(controller: Controller, **changes: object) -> Controller:
    """Change selected limits while retaining immutable configuration validation."""
    return replace(controller, limits=replace(controller.limits, **changes))


def test_wood_berry_cycle_matches_python() -> None:
    """The 60 s, 60-prediction, eight-move Wood-Berry plan matches OSQP."""
    results = run_parity(wood_berry(), cycles=5)
    assert results[-1]["status"] == "solved"


@pytest.mark.parametrize("seed", range(12))
def test_seeded_feasible_problems_match_python(seed: int) -> None:
    """Seeded full-rank plants compare complete plans and predictions, not just first moves."""
    random = np.random.default_rng(seed)
    gains = np.eye(2) + random.uniform(-0.25, 0.25, (2, 2))
    controller = make_controller(gains)
    model = replace(controller.model, time_constants_s=random.uniform(90, 600, (2, 2)),
                    dead_times_s=random.uniform(0, 150, (2, 2)))
    results = run_parity(replace(controller, model=model))
    assert results[-1]["status"] == "solved"


def test_initialisation_holds_actual_mvs() -> None:
    """Both engines start bumplessly with a zero increment plan."""
    result = run_parity(make_controller(np.array([[2.0]])), cycles=1)[0]
    assert result["status"] == "initialised"
    np.testing.assert_array_equal(result["move_plan"], np.zeros((5, 1)))


def test_refused_moves_are_reconciled_from_readback() -> None:
    """Refused proposals must not accumulate fictitious input changes or CV bias."""
    results = run_parity(make_controller(np.array([[2.0]])), cycles=4, refuse=True)
    np.testing.assert_allclose(results[-1]["moves"], results[1]["moves"], atol=1e-7)
    np.testing.assert_allclose(results[-1]["bias"], [0.15], atol=1e-12)


def test_measured_disturbances_match_python() -> None:
    """The trailing input column contributes held disturbance dynamics and steady gain."""
    results = run_parity(make_controller(np.array([[2.0, 0.7]]), count=1))
    assert results[-1]["status"] == "solved"


def test_saturated_actuator_stays_fixed() -> None:
    """A fixed MV remains at its bound while a second MV controls the CV."""
    controller = changed_limits(make_controller(np.array([[1.0, 1.0]])),
                                mv_lower=np.array([0.0, -5.0]), mv_upper=np.array([0.0, 5.0]))
    result = run_parity(controller)[-1]
    assert result["moves"][0] == pytest.approx(0.0, abs=2e-5)
    assert "mv[0].upper@1" in result["active_constraints"]


def test_conflicting_steady_cv_limits_relax_lowest_priority_first() -> None:
    """Contradictory CV demands relax the lower-priority output before the actuator."""
    controller = changed_limits(make_controller(np.array([[1.0], [1.0]])),
                                cv_lower=np.array([0.0, -2.0]), cv_upper=np.array([2.0, -0.2]))
    result = run_parity(controller, cycles=2)[-1]
    assert result["status"] == "relaxed"
    assert result["relaxed_cvs"] == [1]


def test_unreachable_dynamic_funnel_relaxes_cv_bounds() -> None:
    """An immediate zero-width funnel requires slack while actuator limits stay hard."""
    controller = changed_limits(make_controller(np.array([[1.0]])),
                                funnel_start=np.zeros(1), funnel_end=np.zeros(1))
    result = run_parity(controller, cycles=2)[-1]
    assert result["status"] == "relaxed"
    assert result["relaxed_cvs"] == [0]


def test_unreachable_hard_mv_limits_hold_then_latch_shed() -> None:
    """Three impossible actuator plans shed, and later cycles retain the shed latch."""
    controller = changed_limits(make_controller(np.array([[1.0]])),
                                mv_lower=np.ones(1), mv_upper=np.full(1, 2.0),
                                move_max=np.full(1, 0.1))
    results = run_parity(controller, cycles=5, refuse=True)
    assert [result["status"] for result in results] == [
        "initialised", "hold", "hold", "shed", "shed"
    ]


def test_repeated_inputs_produce_identical_results() -> None:
    """Fresh identical solves return identical decisions and deterministic iteration counts."""
    controller = wood_berry()
    inputs = inputs_for(controller)
    state = asdict(replace(initialise(controller, inputs), is_initial=False))
    first, first_state = crosscut_core.mpc_cycle(asdict(controller), state, asdict(inputs))
    second, second_state = crosscut_core.mpc_cycle(asdict(controller), state, asdict(inputs))
    first.pop("solve_time_s")
    second.pop("solve_time_s")
    assert first == second
    assert first_state == second_state


@pytest.mark.parametrize("bad_values", [[float("nan")], [0.0, 1.0]])
def test_nonfinite_or_misshaped_measurements_fail_visibly(bad_values: list[float]) -> None:
    """The binding rejects invalid values before accessing numerical array storage."""
    controller = make_controller(np.array([[1.0]]))
    inputs = inputs_for(controller)
    state = asdict(initialise(controller, inputs))
    invalid = asdict(inputs)
    invalid["measured_cvs"] = bad_values
    with pytest.raises(ValueError, match="measured_cvs"):
        crosscut_core.mpc_cycle(asdict(controller), state, invalid)


def test_wood_berry_solve_has_margin_under_ten_percent_of_cycle() -> None:
    """Both measured wall time and reported solve time stay below half the 6 s budget."""
    controller = wood_berry()
    inputs = inputs_for(controller)
    state = asdict(replace(initialise(controller, inputs), is_initial=False))
    start = perf_counter()
    result, _ = crosscut_core.mpc_cycle(asdict(controller), state, asdict(inputs))
    elapsed_s = perf_counter() - start
    assert result["status"] == "solved"
    assert result["solve_time_s"] < MAXIMUM_SOLVE_S
    assert elapsed_s < MAXIMUM_SOLVE_S
