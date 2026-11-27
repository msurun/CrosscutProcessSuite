"""Verify edited identification artifacts retain their provenance and path settings.

Synthetic single-path models isolate persistence and controller conversion behavior.
"""

from dataclasses import replace

import numpy as np
import pytest
from crosscut_mpc.artifact import IdentModelIntegrityError, load_ident_model, save_ident_model
from crosscut_mpc.identification import IdentificationRejected, IdentifiedModel, PairQuality


def example_model() -> IdentifiedModel:
    """Return one accepted synthetic path with seconds and CV/input-unit gain."""
    return IdentifiedModel(
        ("feed",), ("temperature",), np.array([[2.0]]), np.array([[10.0]]),
        np.array([[3.0]]), 1.0, ((PairQuality(0.99, 4, True, ()),),), {},
    )


def test_edited_artifact_round_trips_flags_and_hashed_provenance(tmp_path):
    metadata = {"parent_model_id": "parent", "parent_sha256": "a" * 64,
                "author": "Engineer", "reason": "Revised equipment response"}
    model = replace(example_model(), enabled=((False,),), edit_metadata=metadata)
    digest = save_ident_model(tmp_path / "child", model)

    loaded = load_ident_model(tmp_path / "child", digest)

    assert loaded.enabled == ((False,),)
    assert loaded.edit_metadata == metadata
    np.testing.assert_array_equal(loaded.gains, [[2.0]])


def test_disabled_pair_contributes_zero_gain_without_destroying_fit():
    model = replace(example_model(), enabled=((False,),))

    converted = model.to_mpc_model()

    np.testing.assert_array_equal(converted.gains, [[0.0]])
    np.testing.assert_array_equal(model.gains, [[2.0]])


def test_legacy_model_without_flags_keeps_its_gain():
    converted = example_model().to_mpc_model()

    np.testing.assert_array_equal(converted.gains, [[2.0]])


def test_disabled_failed_pair_retains_verdict_but_does_not_block_conversion():
    failed = PairQuality(0.1, 0, False, ("insufficient excitation",))
    model = replace(example_model(), quality=((failed,),), enabled=((False,),))

    converted = model.to_mpc_model()

    assert model.quality[0][0] == failed
    np.testing.assert_array_equal(converted.gains, [[0.0]])


def test_enabled_failed_pair_still_blocks_conversion():
    failed = PairQuality(0.1, 0, False, ("insufficient excitation",))
    model = replace(example_model(), quality=((failed,),), enabled=((True,),))

    with pytest.raises(IdentificationRejected, match="insufficient excitation"):
        model.to_mpc_model()


def test_enable_grid_requires_every_pair():
    with pytest.raises(ValueError, match="one boolean per"):
        replace(example_model(), enabled=((),))


def test_enable_grid_rejects_numeric_truth_values():
    with pytest.raises(ValueError, match="booleans"):
        replace(example_model(), enabled=((1,),))


def test_provenance_tampering_is_refused(tmp_path):
    model = replace(example_model(), edit_metadata={"reason": "calibration"})
    save_ident_model(tmp_path / "child", model)
    payload = tmp_path / "child" / "model.json"
    payload.write_text(payload.read_text().replace("calibration", "forged"))

    with pytest.raises(IdentModelIntegrityError):
        load_ident_model(tmp_path / "child")
