"""Regression tests for the stiction validation experiment (one seed, so they stay fast)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import exp01  # noqa: E402

SEED = 1


def test_a_sticking_valve_is_detected_when_measurement_noise_is_low() -> None:
    assert exp01._verdict_for(SEED, 8.0, "low") == "stiction"


def test_a_healthy_valve_is_never_reported_as_sticking() -> None:
    assert exp01._verdict_for(SEED, 0.0, "low") != "stiction"


def test_the_summary_counts_every_verdict_per_band_and_noise_level() -> None:
    rows = [(4.0, "low", "stiction"), (4.0, "low", "stiction"), (4.0, "low", "inconclusive")]
    assert exp01.summarise(rows) == {
        (4.0, "low"): {"stiction": 2, "no_stiction": 0, "inconclusive": 1}
    }
