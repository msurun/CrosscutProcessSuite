"""Bias correction as configuration (#159): schema, defaults, old-constant parity, effect."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import jsonschema
import numpy as np
import pytest
from crosscut_softsensor.bias import BiasTracker
from crosscut_softsensor.config import BiasCorrection, SoftSensorConfigError, load_config
from crosscut_softsensor.runner import run_softsensor
from test_bias_runner import CFG, _fit_and_labs  # reuse the synthetic drifting record

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "softsensor.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text("utf-8"))
BASE = {
    "schema_version": "1.0.0", "id": "t", "target_tag": "y", "input_tags": ["a"],
    "mode": "advisory",
}


def test_defaults_equal_the_former_constants() -> None:
    assert load_config(BASE).bias_correction == BiasCorrection(0.3, 3.0, 3)
    jsonschema.validate({**BASE, "bias_correction": {}}, SCHEMA)


def test_partial_block_keeps_other_defaults() -> None:
    cfg = load_config({**BASE, "bias_correction": {"weight": 0.5}})
    assert cfg.bias_correction == BiasCorrection(0.5, 3.0, 3)


@pytest.mark.parametrize(
    "block",
    [{"weight": 0}, {"weight": 1.2}, {"k_sigma": 0}, {"consecutive": 0}, {"consecutive": 2.5},
     {"consecutive": True}, {"weight": "a"}, {"extra": 1}],
)
def test_invalid_block_rejected_by_schema_and_loader(block: dict) -> None:
    doc = {**BASE, "bias_correction": block}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)
    with pytest.raises(SoftSensorConfigError, match="bias_correction"):
        load_config(doc)


def test_default_config_reproduces_the_default_tracker_exactly() -> None:
    model, t, cols, _, labs = _fit_and_labs(True)
    via_config = run_softsensor(model, CFG, t, cols, labs)
    explicit = run_softsensor(model, CFG, t, cols, labs, BiasTracker(model.cv_sigma, 0.3, 3.0, 3))
    assert np.array_equal(via_config.bias, explicit.bias, equal_nan=True)
    assert np.array_equal(via_config.drift, explicit.drift)


def test_non_default_weight_changes_the_correction() -> None:
    model, t, cols, _, labs = _fit_and_labs(True)
    base = run_softsensor(model, CFG, t, cols, labs)
    cfg = replace(CFG, bias_correction=BiasCorrection(weight=1.0))
    fast = run_softsensor(model, cfg, t, cols, labs)
    assert not np.allclose(base.bias, fast.bias, equal_nan=True)
