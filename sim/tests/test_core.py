"""Tests for the simulator core primitives."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from crosscut_sim.core import Fopdt, Scenario, TagCatalog, TagSpec
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(("delay_s", "delay_steps"), [(0.0, 0), (5.0, 5), (7.0, 7)])
def test_fopdt_matches_analytic_step_response(delay_s: float, delay_steps: int) -> None:
    """The discrete FOPDT update must match the exact series and the step response."""
    gain, tau, dt = 2.5, 30.0, 1.0
    model = Fopdt(gain, tau, delay_s, dt)
    pole = math.exp(-dt / tau)
    for step_index in range(1, 400):
        process_value = model.update(1.0)
        expected = (
            0.0 if step_index <= delay_steps else gain * (1.0 - pole ** (step_index - delay_steps))
        )
        assert process_value == pytest.approx(expected, abs=1e-12)
        # continuous-time reference at elapsed_time = step_index * dt
        elapsed_time = step_index * dt
        continuous = (
            0.0
            if elapsed_time <= delay_s
            else gain * (1.0 - math.exp(-(elapsed_time - delay_s) / tau))
        )
        assert process_value == pytest.approx(continuous, abs=1e-9)


def test_fopdt_steady_state_gain_and_zero_input() -> None:
    """The output settles at gain*input, then decays back to zero on a zero input."""
    fopdt_model = Fopdt(-3.0, 10.0, 4.0, 1.0)
    for _ in range(500):
        fopdt_model.update(2.0)
    assert fopdt_model.value == pytest.approx(-6.0, abs=1e-9)
    for _ in range(500):
        fopdt_model.update(0.0)
    assert fopdt_model.value == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize(
    ("tau", "delay", "dt"), [(0.0, 1.0, 1.0), (-1.0, 1.0, 1.0), (1.0, -1.0, 1.0), (1.0, 1.0, 0.0)]
)
def test_fopdt_rejects_bad_parameters(tau: float, delay: float, dt: float) -> None:
    """A non-positive time constant or sampling time, or a negative delay, is refused up front."""
    with pytest.raises(ValueError):
        Fopdt(1.0, tau, delay, dt)


def test_catalog_rejects_duplicates_and_exports_valid_document() -> None:
    """The catalog keeps its order, exports a schema-valid document, refuses duplicates."""
    specs = [
        TagSpec("a.pv", "wt%", "PV", eng_min=0.0, eng_max=100.0),
        TagSpec("a.sp", "wt%", "SP", writable=True),
        TagSpec("a.mode", "", "MODE", type="enum", writable=True),
    ]
    catalog = TagCatalog(specs)
    assert catalog.ids() == ["a.pv", "a.sp", "a.mode"]
    assert "a.pv" in catalog
    assert len(catalog) == 3
    schema = json.loads((REPO_ROOT / "schemas" / "tags.schema.json").read_text(encoding="utf-8"))
    validation_errors = list(Draft202012Validator(schema).iter_errors(catalog.to_document()))
    assert validation_errors == [], [error.message for error in validation_errors]
    with pytest.raises(ValueError):
        TagCatalog([*specs, TagSpec("a.pv", "wt%", "PV")])


def test_scenario_params_lookup() -> None:
    """Scenario parameters are found by name, the first match wins, a default covers gaps."""
    scenario = Scenario(params=(("operator", 0.0), ("operator", 1.0), ("gain", 2.5)))
    assert scenario.param("operator", 1.0) == 0.0  # first match wins
    assert scenario.param("gain", 1.0) == 2.5
    assert scenario.param("missing", 7.0) == 7.0
    assert Scenario().param("anything", 3.0) == 3.0
    assert hash(scenario) == hash(Scenario(params=scenario.params))


def test_scenario_validation() -> None:
    """A scenario with a non-positive step, a negative duration or negative noise is refused."""
    assert Scenario().dt_s == 1.0
    with pytest.raises(ValueError):
        Scenario(dt_s=0.0)
    with pytest.raises(ValueError):
        Scenario(duration_s=-1.0)
    with pytest.raises(ValueError):
        Scenario(measurement_noise=-0.1)
