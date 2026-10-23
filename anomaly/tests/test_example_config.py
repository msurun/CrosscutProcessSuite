"""The bundled example config (web UI "Load example") must be valid with frozen defaults."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from crosscut_anomaly.config import load_config

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = json.loads((ROOT / "anomaly" / "examples" / "mill_circuit_pca.json").read_text("utf-8"))
SCHEMA = json.loads((ROOT / "schemas" / "anomaly.schema.json").read_text("utf-8"))


def test_example_is_valid_and_advisory() -> None:
    config = load_config(EXAMPLE)
    jsonschema.validate(EXAMPLE, SCHEMA)
    assert config.mode == "advisory" and config.id == "mill_circuit_pca"
    assert len(config.tags) == 8 and all(tag.startswith("sim.mc.") for tag in config.tags)


def test_example_uses_the_frozen_protocol_defaults() -> None:
    config = load_config(EXAMPLE)
    assert (config.variance_fraction, config.alpha) == (0.90, 0.99)
    assert (config.min_consecutive, config.close_after, config.sample_period_s) == (5, 10, 60.0)
