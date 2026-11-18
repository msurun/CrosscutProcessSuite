"""Synthetic operating-point and held-sensor regression tests.
These exercise engine decisions independently of public experiment measurements.
"""

import json
from dataclasses import replace
from pathlib import Path

import jsonschema
import numpy as np
import pytest
from crosscut_anomaly.config import AnomalyConfigError, load_config
from crosscut_anomaly.detect import scan, scan_regimes
from crosscut_anomaly.pca_model import RegimeModelSet, fit_from_config, fit_regimes

DOCUMENT = {"schema_version": "1.0.0", "id": "test", "mode": "advisory",
            "tags": ["a", "b", "c", "d"]}
SCHEMA = json.loads((Path(__file__).resolve().parents[2] /
                     "schemas/anomaly.schema.json").read_text())


def test_regime_switch_is_normal_and_unknown_rows_have_no_verdict():
    """Separate mean models explain a switch that a single-point fit alarms on."""
    config = load_config({**DOCUMENT, "regimes": {"by": ["a"]}})
    random = np.random.default_rng(102)
    training = np.vstack([random.normal(size=(500, 4)), random.normal(20, 1, (500, 4))])
    models = fit_regimes(training, config, [0] * 500 + [1] * 500)
    held_out = random.normal(20, 1, (100, 4))
    single = fit_from_config(training[:500], config)
    assert scan(single, np.arange(100), held_out, config=config).n_pca_events > 0
    assert scan_regimes(models, np.arange(100), held_out, mode_ids=[1] * 100).events == ()
    unknown = scan_regimes(models, np.arange(100), held_out, mode_ids=[2] * 100)
    assert unknown.rows_unscored == 100 and unknown.events == ()
    restored = RegimeModelSet.from_dict(json.loads(json.dumps(models.to_dict())))
    assert restored.sha256() == models.sha256()


@pytest.mark.parametrize("changes", [
    {"regimes": {"by": []}}, {"regimes": {"by": ["a"], "min_rows": True}},
    {"regimes": {"by": ["a"], "quantum": {"a": 0}}}, {"setpoint_like": ["a", "a"]},
])
def test_invalid_regime_documents_are_rejected(changes):
    """Both schema and parser reject malformed optional settings."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**DOCUMENT, **changes}, SCHEMA)
    with pytest.raises(AnomalyConfigError):
        load_config({**DOCUMENT, **changes})


def test_valid_regime_document_is_accepted():
    """Rounding and explicit held tags are accepted by both contracts."""
    document = {**DOCUMENT, "regimes": {"by": ["a"], "quantum": {"a": 0.5}},
                "setpoint_like": ["b"]}
    jsonschema.validate(document, SCHEMA)
    assert load_config(document).regimes.min_rows == 200


@pytest.mark.parametrize("reason", ["training_run", "training_limit", "quantised_level",
                                   "setpoint_like", "automatic_setpoint", "real_stuck"])
def test_stuck_decisions_use_training_evidence(reason):
    """Legitimate training holds are exempt; a novel interior freeze still alarms."""
    random = np.random.default_rng(103)
    training = random.normal(size=(500, 4))
    training[:20, 0] = 0.25
    if reason == "automatic_setpoint":
        training[:490, 0] = 0.25
    config = load_config({**DOCUMENT, "stuck_samples": 10})
    if reason == "setpoint_like":
        config = replace(config, setpoint_like=("a",))
    model = fit_from_config(training, config)
    values = {"training_run": 0.8, "training_limit": training[:, 0].min(),
              "quantised_level": 0.25, "setpoint_like": 0.8,
              "automatic_setpoint": 0.8, "real_stuck": 0.8}
    count = 15 if reason == "training_run" else 80
    record = random.normal(size=(count, 4))
    record[:, 0] = values[reason]
    result = scan(model, np.arange(count), record, config=config)
    if reason == "real_stuck":
        assert result.n_stuck_events == 1
    else:
        expected = "setpoint_like" if reason == "automatic_setpoint" else reason
        assert result.stuck_exemptions[expected] == 1
        assert result.n_stuck_events == 0


def test_undertrained_regime_is_unscored():
    """A seen regime with insufficient training receives no verdict."""
    config = load_config({**DOCUMENT, "regimes": {"by": ["a"]}})
    training = np.random.default_rng(104).normal(size=(300, 4))
    models = fit_regimes(training, config, [0] * 250 + [1] * 50)
    result = scan_regimes(models, np.arange(50), training[-50:], mode_ids=[1] * 50)
    assert result.rows_unscored == 50 and result.events == ()


def test_rounded_setpoints_can_be_constant_within_each_regime():
    """Raw setpoint grouping fits even when its column has no within-mode variance."""
    config = load_config({**DOCUMENT, "regimes": {"by": ["a"], "quantum": {"a": 1}}})
    rows = np.random.default_rng(105).normal(size=(600, 4))
    rows[:300, 0] = 10
    rows[300:, 0] = 20
    models = fit_regimes(rows, config)
    result = scan_regimes(models, np.arange(600), rows)
    assert len(models.models) == 2
    assert result.rows_unscored == 0 and result.n_valid == 600
