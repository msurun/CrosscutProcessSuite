"""Benefit report: the economic MPC against setpoint-tracking MPC on one identified plant.

Both controllers run the same closed loop on the same exact-ZOH FOPDT plant (the #183 simulator
plant); only the economics differ. Rates are [currency/h] of the deviation signals, so the
meaningful number is the settled difference. No I/O; JSON-ready output.
"""

from dataclasses import dataclass, replace

import numpy as np

from .config import Controller
from .economics import Binding
from .engine import Result, cycle, initialise
from .model import Array, advance, initial_model_state
from .planning import CycleInputs
from .simulator import MAX_SAMPLES, clamp_moves, trajectory_violations

SETTLED_SHARE = 0.2  # The last 20 percent of samples define the settled rate.
SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class BenefitScenario:
    """Length in samples and constant CV targets (deviations) for both branches."""

    steps: int = 150
    targets: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        """Bound the work of one report."""
        if not isinstance(self.steps, int) or not 10 <= self.steps <= MAX_SAMPLES:
            raise ValueError(f"Benefit steps must be an integer from 10 to {MAX_SAMPLES}")


DEFAULT_SCENARIO = BenefitScenario()


def run_branch(controller: Controller, targets: Array,
               steps: int) -> tuple[Array, Array, list[Result]]:
    """Close the loop for steps samples; return CV and MV trajectories and engine results."""
    count = len(controller.limits.mv_lower)
    disturbances = np.zeros(controller.model.gains.shape[1] - count)
    actual = np.zeros(count)
    plant = initial_model_state(controller.model, np.r_[actual, disturbances])
    measured = plant.paths.sum(axis=1)
    inputs = CycleInputs(measured, actual, targets, tuple(disturbances))
    state = initialise(controller, inputs)
    cvs, mvs, results = [measured.copy()], [actual.copy()], []
    for _ in range(steps):
        result, state = cycle(controller, state, inputs)
        actual = clamp_moves(controller, actual, np.array(result.moves))
        plant = advance(controller.model, plant, np.r_[actual, disturbances])
        measured = plant.paths.sum(axis=1)
        inputs = CycleInputs(measured, actual, targets, tuple(disturbances))
        cvs.append(measured.copy())
        mvs.append(actual.copy())
        results.append(result)
    return np.asarray(cvs), np.asarray(mvs), results


def settled(rates: Array) -> float:
    """Mean of the last SETTLED_SHARE of the rate series [currency/h]."""
    tail = max(1, int(len(rates) * SETTLED_SHARE))
    return float(np.mean(rates[-tail:]))


def binding_summary(results: list[Result]) -> list[dict[str, object]]:
    """Share of cycles each limit bound, with its mean shadow price while it bound."""
    counts: dict[tuple[str, int, str, str], list[float]] = {}
    for result in results:
        for item in result.economics.binding if result.economics else ():
            counts.setdefault((item.kind, item.index, item.side, item.limit), []).append(
                item.shadow_price)
    total = max(len(results), 1)
    return [{"kind": key[0], "index": key[1], "side": key[2], "limit": key[3],
             "share": len(prices) / total, "mean_shadow_price": float(np.mean(prices))}
            for key, prices in sorted(counts.items())]


def binding_over_time(results: list[Result]) -> list[list[str]]:
    """Per cycle, the binding limits as labels such as ``cv[0].upper``."""
    def label(item: Binding) -> str:
        return f"{item.kind}[{item.index}].{item.side}"
    return [[label(item) for item in (result.economics.binding if result.economics else ())]
            for result in results]


def branch_report(controller: Controller,
                  trajectory: tuple[Array, Array, list[Result]]) -> tuple[dict[str, object], Array]:
    """Series, economic rate per sample [currency/h] and violation counts of one branch."""
    cvs, mvs, results = trajectory
    economics = controller.economics
    assert economics is not None
    rates = np.array([economics.rate(cv, mv) for cv, mv in zip(cvs, mvs, strict=True)])
    return {"cvs": cvs.tolist(), "mvs": mvs.tolist(), "rate": rates.tolist(),
            "settled_rate": settled(rates),
            "violations": trajectory_violations(controller, (cvs, mvs)),
            "binding": binding_summary(results),
            "binding_over_time": binding_over_time(results)}, rates


def simulate_benefit(controller: Controller,
                     scenario: BenefitScenario = DEFAULT_SCENARIO) -> dict[str, object]:
    """Compare setpoint tracking with the economic target; both are scored with the economics."""
    economics = controller.economics
    if economics is None or not economics.is_active:
        raise ValueError("Benefit report needs active economics (a nonzero value or cost)")
    outputs = controller.model.gains.shape[0]
    targets = np.array(scenario.targets, dtype=float) if scenario.targets else np.zeros(outputs)
    if targets.shape != (outputs,):
        raise ValueError("Benefit targets must give one value per CV")
    tracking = run_branch(replace(controller, economics=None), targets, scenario.steps)
    economic = run_branch(controller, targets, scenario.steps)
    (base, base_rates), (best, best_rates) = (branch_report(controller, tracking),
                                              branch_report(controller, economic))
    period = controller.model.cycle_s
    # Integral of the rate difference over the run: sum(delta rate [currency/h]) * Ts [h].
    gained = float(np.sum(best_rates - base_rates)) * period / SECONDS_PER_HOUR
    return {"time_s": (np.arange(scenario.steps + 1) * period).tolist(),
            "targets": targets.tolist(), "unit": "currency/h",
            "tracking": base, "economic": best,
            "benefit_rate": float(settled(best_rates) - settled(base_rates)),
            "value_gained": gained}
