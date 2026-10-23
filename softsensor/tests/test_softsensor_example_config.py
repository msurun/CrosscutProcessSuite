"""The bundled soft sensor example (the web UI's "Load example") must be valid and advisory."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from crosscut_softsensor.config import load_config

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PATH = ROOT / "softsensor" / "examples" / "mill_circuit_pls.json"
EXAMPLE = json.loads(EXAMPLE_PATH.read_text("utf-8"))
SCHEMA = json.loads((ROOT / "schemas" / "softsensor.schema.json").read_text("utf-8"))


def test_example_is_valid_and_advisory() -> None:
    config = load_config(EXAMPLE)
    jsonschema.validate(EXAMPLE, SCHEMA)
    assert config.mode == "advisory" and config.id == "mill_circuit_pls"
    assert config.target_tag not in config.input_tags


def test_example_uses_simulator_tags_without_the_online_p80() -> None:
    config = load_config(EXAMPLE)
    assert len(config.input_tags) == 7
    assert all(tag.startswith("sim.mc.") for tag in config.input_tags)
    assert "sim.mc.p80" not in config.input_tags


def test_example_uses_the_frozen_protocol_settings() -> None:
    config = load_config(EXAMPLE)
    assert config.lags_s == (0.0, 300.0, 900.0, 1800.0)
    assert (config.lab_delay_s, config.sample_period_s) == (3600.0, 60.0)
