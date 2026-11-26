"""Exercise equipment learning with a synthetic pump.

Operating interruptions must never become evidence of normal operation.
"""

import json

import numpy as np
import pytest
from crosscut_anomaly.equipment_learning import (
    EquipmentModel,
    apply_exclusions,
    equipment_variables,
    learn_equipment,
    propose_windows,
    score,
    training_mask,
)


@pytest.fixture
def pump() -> tuple:
    """Return reproducible pump channels with disjoint invalid stretches."""
    generator = np.random.default_rng(215)
    times = np.arange(600, dtype=float)
    output = 50 + 15 * np.sin(times / 25)
    data = {"PV": output + generator.normal(0, 0.1, 600), "SP": output.copy(),
            "OUT": output.copy(), "MODE": np.ones(600), "RUN": np.ones(600),
            "CURRENT": 2 * output + generator.normal(0, 0.2, 600)}
    data["RUN"][100:140] = 0
    data["MODE"][200:240] = 0
    data["OUT"][300:340] = 100
    equipment = {"id": "pump", "loops": ["flow"],
                 "signals": [{"tag": "CURRENT", "kind": "current", "confirmed": True}],
                 "running": {"tag": "RUN", "above": 0.5, "confirmed": True}}
    loops = [{"id": "flow", "pv": "PV", "sp": "SP", "out": "OUT", "mode": "MODE"}]
    return times, data, equipment, loops


def test_interruptions_are_removed_with_their_reasons(pump: tuple) -> None:
    """Each operating rule accounts for its excluded samples."""
    mask, reasons = training_mask(*pump)
    assert reasons == {"stopped": 40, "manual": 40, "saturated": 40, "quiet": 0}
    assert mask.sum() == 480


def test_variables_preserve_catalogue_order_and_remove_duplicates(pump: tuple) -> None:
    """Owned loop channels precede the condition channels."""
    _, _, equipment, loops = pump
    site = {"equipment": [equipment], "loops": loops}
    assert equipment_variables(site, "pump") == ["PV", "SP", "OUT", "CURRENT"]


def test_current_fault_exceeds_residual_and_ewma_limits(pump: tuple) -> None:
    """A load increase at unchanged speed is unexplained by the operating point."""
    model = learn_equipment(*pump)
    row = {tag: values[400] for tag, values in pump[1].items()}
    row["CURRENT"] += 10
    score(model, {tag: values[399] for tag, values in pump[1].items()})
    result = score(model, row)
    assert model.status == "learned"
    assert result["residuals"]["CURRENT"] > 3
    assert result["ewma"]["CURRENT"] > result["ewma_limit"]
    assert result["t2"] >= 0
    assert result["spe"] >= 0


def test_json_round_trip_preserves_predictions(pump: tuple) -> None:
    """Saved models retain both PCA and conditional regressions."""
    model = learn_equipment(*pump)
    restored = EquipmentModel.from_dict(json.loads(json.dumps(model.to_dict(), allow_nan=False)))
    row = {tag: values[400] for tag, values in pump[1].items()}
    assert score(model, row) == score(restored, row)


def test_short_records_return_explicit_fallback(pump: tuple) -> None:
    """Quiet stretches shorter than thirty samples cannot train a model."""
    times, data, equipment, loops = pump
    short = {tag: values[:20] for tag, values in data.items()}
    model = learn_equipment(times[:20], short, equipment, loops)
    assert model.status == "not_enough_data"
    assert model.to_dict()["fallback"] == "per_loop"


def test_exclusions_split_windows_without_retaining_endpoints() -> None:
    """Exclusion boundaries are closed and cannot leak into training."""
    assert apply_exclusions([[0, 100]], [[20, 40]]) == [
        [0, np.nextafter(20.0, -np.inf)], [np.nextafter(40.0, np.inf), 100]]


def test_proposals_only_include_long_contiguous_spans() -> None:
    """An unusable sample separates otherwise adjacent proposals."""
    assert propose_windows(np.arange(7), [True, True, False, True, True, True, True], 2) == [
        [3.0, 6.0]]


def test_fallback_fits_an_individual_loop_when_equipment_history_is_short(pump: tuple) -> None:
    """Static loop PCA can learn from sixty samples when lagged equipment PCA cannot."""
    times, data, equipment, loops = pump
    short = {tag: values[:60] for tag, values in data.items()}
    model = learn_equipment(times[:60], short, equipment, loops)
    assert model.status == "not_enough_data"
    assert model.per_loop["flow"].n_train == 60


def test_user_exclusions_also_prevent_fallback_training(pump: tuple) -> None:
    """The fallback cannot relearn explicitly rejected samples."""
    times, data, equipment, loops = pump
    short = {tag: values[:60] for tag, values in data.items()}
    model = learn_equipment(times[:60], short, equipment, loops, [[0, 59]])
    assert model.per_loop == {}


def test_short_eligible_stretches_are_removed_as_quiet(pump: tuple) -> None:
    """Twenty samples never meet the thirty-sample uninterrupted evidence rule."""
    times, data, equipment, loops = pump
    short = {tag: values[:20] for tag, values in data.items()}
    mask, reasons = training_mask(times[:20], short, equipment, loops)
    assert not mask.any()
    assert reasons["quiet"] == 20


def test_archive_gaps_do_not_supply_false_lag_history(pump: tuple) -> None:
    """Two separated sixty-sample records lose one lag row per segment."""
    times, data, equipment, loops = pump
    continuous = {tag: values[350:470] for tag, values in data.items()}
    separated = times[:120].copy()
    separated[60:] += 1000
    model = learn_equipment(separated, continuous, equipment, loops)
    assert model.pca.n_train == 118
    assert model.windows == [[0.0, 59.0], [1060.0, 1119.0]]


def test_power_expectation_includes_the_pump_affinity_cubic(pump: tuple) -> None:
    """A cubic load follows normal speed changes without a large residual."""
    times, data, equipment, loops = pump
    data = {**data, "POWER": 0.001 * data["SP"] ** 3 + np.sin(times) * 0.01}
    signal = {"tag": "POWER", "kind": "power", "confirmed": True}
    equipment = {**equipment, "signals": [*equipment["signals"], signal]}
    model = learn_equipment(times, data, equipment, loops)
    row = {tag: values[400] for tag, values in data.items()}
    result = score(model, row)
    assert len(model.regressions["POWER"]["coefficients"]) == 3
    assert abs(result["residuals"]["POWER"]) < 3


def test_missing_mode_evidence_cannot_establish_automatic_operation(pump: tuple) -> None:
    """A loop without a mode binding produces an explicit training refusal."""
    times, data, equipment, loops = pump
    loop = {key: value for key, value in loops[0].items() if key != "mode"}
    model = learn_equipment(times, data, equipment, [loop])
    assert model.status == "not_enough_data"
    assert model.reasons["manual"] == 560
