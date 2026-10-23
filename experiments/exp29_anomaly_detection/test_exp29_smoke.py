"""Smoke test of the exp29 harness: one short seed end to end plus the generator's fault encoding.

Uses a scratch seed outside every reserved range (29001..29060, 29201..29399, 29401+) and short
records; checks structure, determinism and the invalid-row encoding only, never the criteria.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import exp29  # noqa: E402
import gen29  # noqa: E402

SMOKE_SEED = 990029  # not a protocol seed
SHORT = gen29.Durations(train_h=4.0, quiet_h=2.0, fault_h=3.0, onset_low_h=1.0, onset_high_h=1.5)


def test_one_short_seed_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """Training, quiet and a dropout record through fit, scan, criteria and both files."""
    dropout_index = gen29.FAULT_KINDS.index("dropout")
    monkeypatch.setattr(exp29, "plan", lambda seeds: [(SMOKE_SEED, True, dropout_index)])
    monkeypatch.setattr(gen29, "PROTOCOL", SHORT)
    monkeypatch.setattr(exp29, "run_one", _short_run_one(exp29.run_one))
    payload = exp29.run("smoke", tmp_path)
    saved = json.loads((tmp_path / "smoke_runs.json").read_text(encoding="utf-8"))
    assert set(saved["criteria"]) == {"A1", "A2", "A3", "A4", "A5"}
    assert (tmp_path / "smoke.md").read_text(encoding="utf-8").startswith("# exp29 results")
    row = payload["runs"][0]
    assert 1 <= row["model"]["k"] < len(gen29.TAGS)
    fault = row["fault"]
    assert fault["spec"]["kind"] == "dropout" and fault["n_skipped"] > 0
    assert fault["skipped_reasons"]["nan"] == fault["n_skipped"]
    assert payload["criteria"]["A5"]["n"] == 1 and fault["a5"]["ok"]


def _short_run_one(original):
    """run_one bound to the short durations."""
    return lambda seed, quiet, index: original(seed, quiet, index, SHORT)


def test_fault_encoding_and_determinism() -> None:
    """bad_quality rows carry quality != 0 and finite values; records are a function of the seed."""
    train = gen29.training_record(SMOKE_SEED, SHORT)
    again = gen29.training_record(SMOKE_SEED, SHORT)
    assert np.array_equal(train.x, again.x) and len(train.t_s) == 240
    spec = gen29.fault_spec(
        SMOKE_SEED, gen29.FAULT_KINDS.index("bad_quality"), gen29.training_sd(train), SHORT
    )
    record = gen29.fault_record(SMOKE_SEED, spec, SHORT)
    bad = record.quality != 0
    assert bad.sum() in (60, 61) and np.isfinite(record.x[bad]).all()
    assert SHORT.onset_low_h * 3600 <= spec["onset_s"] <= SHORT.onset_high_h * 3600
