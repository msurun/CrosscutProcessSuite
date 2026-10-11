"""Tests for the simulator core primitives."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from crosscut_sim.core import Fopdt, Scenario, TagCatalog, TagSpec
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(("delay_s", "n"), [(0.0, 0), (5.0, 5), (7.0, 7)])
def test_fopdt_matches_analytic_step_response(delay_s: float, n: int) -> None:
    gain, tau, dt = 2.5, 30.0, 1.0
    f = Fopdt(gain, tau, delay_s, dt)
    a = math.exp(-dt / tau)
    for j in range(1, 400):
        y = f.update(1.0)
        expected = 0.0 if j <= n else gain * (1.0 - a ** (j - n))
        assert y == pytest.approx(expected, abs=1e-12)
        # continuous-time reference at t = j * dt
        t = j * dt
        continuous = 0.0 if t <= delay_s else gain * (1.0 - math.exp(-(t - delay_s) / tau))
        assert y == pytest.approx(continuous, abs=1e-9)


def test_fopdt_steady_state_gain_and_zero_input() -> None:
    f = Fopdt(-3.0, 10.0, 4.0, 1.0)
    for _ in range(500):
        f.update(2.0)
    assert f.value == pytest.approx(-6.0, abs=1e-9)
    for _ in range(500):
        f.update(0.0)
    assert f.value == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize(
    ("tau", "delay", "dt"), [(0.0, 1.0, 1.0), (-1.0, 1.0, 1.0), (1.0, -1.0, 1.0), (1.0, 1.0, 0.0)]
)
def test_fopdt_rejects_bad_parameters(tau: float, delay: float, dt: float) -> None:
    with pytest.raises(ValueError):
        Fopdt(1.0, tau, delay, dt)


def test_catalog_rejects_duplicates_and_exports_valid_document() -> None:
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
    errors = list(Draft202012Validator(schema).iter_errors(catalog.to_document()))
    assert errors == [], [e.message for e in errors]
    with pytest.raises(ValueError):
        TagCatalog([*specs, TagSpec("a.pv", "wt%", "PV")])


def test_scenario_params_lookup() -> None:
    scenario = Scenario(params=(("operator", 0.0), ("operator", 1.0), ("gain", 2.5)))
    assert scenario.param("operator", 1.0) == 0.0  # first match wins
    assert scenario.param("gain", 1.0) == 2.5
    assert scenario.param("missing", 7.0) == 7.0
    assert Scenario().param("anything", 3.0) == 3.0
    assert hash(scenario) == hash(Scenario(params=scenario.params))


def test_scenario_validation() -> None:
    assert Scenario().dt_s == 1.0
    with pytest.raises(ValueError):
        Scenario(dt_s=0.0)
    with pytest.raises(ValueError):
        Scenario(duration_s=-1.0)
    with pytest.raises(ValueError):
        Scenario(measurement_noise=-0.1)
