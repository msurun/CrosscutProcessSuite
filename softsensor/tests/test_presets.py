"""Tests for soft-sensor presets: schema, loader, role binding and the deployment gate."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from crosscut_softsensor.deployment_gate import (
    REFUSAL_TEXT,
    DeploymentRefused,
    ValidationResults,
    evaluate_gate,
    require_deployable,
)
from crosscut_softsensor.presets import (
    SCHEMA_NAME,
    PresetBindingError,
    PresetError,
    bind_roles,
    load_presets,
    validate_preset,
)

ROOT = Path(__file__).resolve().parents[2]
PACKAGED = ROOT / "softsensor/src/crosscut_softsensor/presets"
V1 = {
    "belt_scale_backup", "pump_flowmeter_backup", "valve_flowmeter", "slurry_solids_flow_density",
    "cyclone_overflow_size", "lab_quality_inference", "inventory_mass_balance",
}


def test_all_v1_presets_load_and_are_experimental() -> None:
    presets = load_presets()
    assert set(presets) == V1
    assert all(p["status"] == "experimental" for p in presets.values())


def test_packaged_schema_matches_repository_schema() -> None:
    packaged = json.loads((PACKAGED / SCHEMA_NAME).read_text(encoding="utf-8"))
    canonical = json.loads((ROOT / "schemas" / SCHEMA_NAME).read_text(encoding="utf-8"))
    assert packaged == canonical


def test_every_preset_has_a_provenance_row() -> None:
    log = (ROOT / "docs/PROVENANCE.md").read_text(encoding="utf-8")
    for preset in load_presets().values():
        assert f"`{preset['provenance']['id']}`" in log


def test_invalid_file_names_file_and_field(tmp_path: Path) -> None:
    record = copy.deepcopy(load_presets()["valve_flowmeter"])
    record["deployment_gate"]["min_skill"] = 0
    (tmp_path / "bad.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(PresetError, match=r"bad\.json: field deployment_gate\.min_skill"):
        load_presets(tmp_path)


def test_unreadable_json_names_file(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    with pytest.raises(PresetError, match=r"broken\.json"):
        load_presets(tmp_path)


def test_inverted_range_is_refused() -> None:
    record = copy.deepcopy(load_presets()["valve_flowmeter"])
    record["target"]["range_min"], record["target"]["range_max"] = 5.0, 1.0
    with pytest.raises(PresetError, match=r"field target\.range_min"):
        validate_preset(record, "x.json")


def test_tag_names_are_not_allowed_in_roles() -> None:
    record = copy.deepcopy(load_presets()["valve_flowmeter"])
    record["inputs"][0]["role"] = "FIC-101.PV"
    with pytest.raises(PresetError, match=r"field inputs\.0\.role"):
        validate_preset(record, "x.json")


CATALOGUE = {"T1": "%", "T2": "kPa", "T3": "kPa", "T4": "kg/m3", "T5": "m3/h", "T6": "m3/h"}
VALVE = {
    "valve_flow": "T6", "valve_position": "T1", "upstream_pressure": "T2",
    "downstream_pressure": "T3", "fluid_density": "T4", "cv_curve": "T5",
}


def test_binding_resolves_against_catalogue() -> None:
    preset = load_presets()["valve_flowmeter"]
    assert bind_roles(preset, VALVE, CATALOGUE) == VALVE


def test_binding_refuses_missing_required_role() -> None:
    preset = load_presets()["valve_flowmeter"]
    partial = {k: v for k, v in VALVE.items() if k != "fluid_density"}
    with pytest.raises(PresetBindingError, match="fluid_density"):
        bind_roles(preset, partial, CATALOGUE)


def test_binding_refuses_unknown_tag_unit_mismatch_and_unknown_role() -> None:
    preset = load_presets()["valve_flowmeter"]
    with pytest.raises(PresetBindingError, match="not in the catalogue"):
        bind_roles(preset, {**VALVE, "valve_position": "NOPE"}, CATALOGUE)
    with pytest.raises(PresetBindingError, match="expected '%'"):
        bind_roles(preset, {**VALVE, "valve_position": "T2"}, CATALOGUE)
    with pytest.raises(PresetBindingError, match="unknown role"):
        bind_roles(preset, {**VALVE, "mystery": "T1"}, CATALOGUE)


GATE = {
    "preregistered": True, "baseline": "age_aware_lab_persistence", "same_information_cutoff": True,
    "min_skill": 0.1, "min_scored_coverage": 0.8, "min_samples": 100,
}


def _results(**changes: object) -> ValidationResults:
    base: dict[str, object] = {
        "rmse_model": 0.8, "rmse_baseline": 1.0, "scored_coverage": 0.9, "n_samples": 200,
        "baseline": "age_aware_lab_persistence",
    }
    return ValidationResults(**{**base, **changes})  # type: ignore[arg-type]


def test_gate_passes_above_margin() -> None:
    decision = evaluate_gate(GATE, _results())
    assert decision.deploy and decision.reasons == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"rmse_model": 0.9},  # skill exactly at the margin
        {"rmse_model": 1.2},  # worse than the baseline
        {"scored_coverage": 0.5},
        {"n_samples": 50},
        {"baseline": "constant"},
        {"same_information_cutoff": False},
    ],
)
def test_gate_refuses_with_exact_text(changes: dict[str, object]) -> None:
    decision = evaluate_gate(GATE, _results(**changes))
    assert not decision.deploy and decision.reasons
    assert decision.message == (
        "Deployment refused: no validated advantage over the available lab baseline."
    )
    assert decision.message == REFUSAL_TEXT


def test_exp39_like_numbers_are_refused() -> None:
    """Sealed exp39: frozen PLS 1.1322 against the shorter-delay baseline 0.7362."""
    preset = load_presets()["lab_quality_inference"]
    results = _results(rmse_model=1.1322, rmse_baseline=0.7362, n_samples=1000)
    with pytest.raises(DeploymentRefused, match="no validated advantage"):
        require_deployable(preset, results)


def test_require_deployable_passes_for_clear_advantage() -> None:
    preset = load_presets()["lab_quality_inference"]
    assert require_deployable(preset, _results(rmse_model=0.6)).deploy
