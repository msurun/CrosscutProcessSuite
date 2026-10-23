"""Smoke test of the exp29 harness: one short seed end to end plus the generator's fault encoding.

Uses scratch seeds outside every reserved range (990029 round 1; 990011 and 990012 round 2) and
short records; checks structure, determinism and the invalid-row encoding only, never the criteria.
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
    jobs = [(SMOKE_SEED, True, dropout_index)]
    monkeypatch.setattr(exp29, "plan", lambda seeds, round_no=1: jobs)
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


def _short_run_one(original, durations: gen29.Durations = SHORT):
    """run_one bound to short durations."""
    return lambda seed, quiet, index, round_no=1: original(seed, quiet, index, durations, round_no)


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


SMOKE2_SEEDS = (990011, 990012)  # round 2 scratch seeds, not protocol seeds
# Round 2 fits 24 lagged columns and needs >= 240 valid training rows: 5 h gives 298.
SHORT2 = gen29.Durations(train_h=5.0, quiet_h=2.0, fault_h=3.0, onset_low_h=1.0, onset_high_h=1.5)


def _round2_payload(tmp_path: Path, monkeypatch, kinds: tuple[str, ...]) -> dict:
    """Round 2 run over the scratch seeds with one fault kind each, short records."""
    jobs = [(s, True, gen29.FAULT_KINDS.index(k)) for s, k in zip(SMOKE2_SEEDS, kinds, strict=True)]
    monkeypatch.setattr(exp29, "plan", lambda seeds, round_no=1: jobs)
    monkeypatch.setattr(exp29, "run_one", _short_run_one(exp29.run_one, SHORT2))
    return exp29.run("smoke", tmp_path, round_no=2)


def test_round2_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """Round 2: B1..B6, file names, lagged model, lag rows counted, SPE limit method reported."""
    payload = _round2_payload(tmp_path, monkeypatch, ("freeze", "dropout"))
    saved = json.loads((tmp_path / "smoke2_runs.json").read_text(encoding="utf-8"))
    assert set(saved["criteria"]) == {f"B{i}" for i in range(1, 7)}
    assert saved["config"]["dynamic_lags"] == 2 and saved["config"]["min_consecutive"] == 10
    assert (tmp_path / "smoke2.md").read_text(encoding="utf-8").startswith("# exp29 results")
    for row in payload["runs"]:
        assert row["model"]["n_columns"] == 3 * len(gen29.TAGS)
        assert row["model"]["spe_limit_method"] in ("jackson_mudholkar", "empirical")
        assert row["quiet"]["skipped_reasons"]["lag"] == 2
    assert sum(payload["reported"]["spe_limit_method_counts"].values()) == 2
    assert payload["criteria"]["B5"]["n"] == 1


def test_round2_freeze_is_found_by_stuck_rule(tmp_path: Path, monkeypatch) -> None:
    """A 2 h freeze is exactly constant at 60 s: the stuck rule names the frozen tag."""
    payload = _round2_payload(tmp_path, monkeypatch, ("freeze", "dropout"))
    fault = payload["runs"][0]["fault"]
    assert fault["spec"]["kind"] == "freeze"
    assert fault["detection"]["stuck_detected"] and fault["detection"]["stuck_names_tag"]
    assert fault["n_stuck_events"] >= 1
