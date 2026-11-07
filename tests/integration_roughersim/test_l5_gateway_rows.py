"""L5-G01..G12: the 12 gateway scenarios against a live RougherSim OPC UA server.

Skips with a message when RougherSim is absent or not at the pin. Each case starts the server
with the hook file of its scenario on a free port and stops it in a finally block.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from gateway_rows import SCENARIOS, run_scenario, tuning
from golden import checkout_problem, load_pin, roughersim_dir


@pytest.fixture(scope="module")
def checkout() -> None:
    """Skip the module unless the sibling RougherSim checkout is the pinned release."""
    problem = checkout_problem(roughersim_dir(), load_pin())
    if problem:
        pytest.skip(problem)


@pytest.mark.slow
@pytest.mark.parametrize("scenario_ref", list(SCENARIOS))
def test_gateway_scenario_on_roughersim(
    scenario_ref: str, tmp_path: Path, checkout: None
) -> None:
    """The scenario's safety property holds on the real gateway + OpcUaPlant + RougherSim."""
    run_scenario(scenario_ref, tmp_path)


@pytest.mark.slow
def test_tuning_write_and_rollback_on_roughersim(tmp_path: Path, checkout: None) -> None:
    """Gain/Ti change through OpcUaPlant.write_param (Double): exact read-back and rollback."""
    tuning(tmp_path)
