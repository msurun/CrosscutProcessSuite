"""Smoke test of the exp30 harness: one short regime record end to end in well under 60 s.

Uses a scratch seed outside every reserved range (29401..29440, 29501..29600, 29601+) and a
4-day record; checks structure, the leakage property and the generator's encoding only, never
the criteria.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import exp30  # noqa: E402
import gen30  # noqa: E402

SMOKE_SEED = 990030  # not a protocol seed
SHORT = gen30.Durations(
    total_d=4.0, cut_d=3.0, drift_start_d=3.1, regime_start_d=3.25, regime_h=12.0
)


def test_one_short_record_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """Generate, fit, S4 check, evaluate, criteria and both result files for one record."""
    monkeypatch.setattr(exp30, "plan", lambda seeds: [(SMOKE_SEED, "regime")])
    monkeypatch.setattr(exp30, "run_one", _short(exp30.run_one))
    payload = exp30.run("smoke", tmp_path)
    saved = json.loads((tmp_path / "smoke_runs.json").read_text(encoding="utf-8"))
    assert set(saved["criteria"]) == {"S1", "S2", "S3", "S4"}
    assert (tmp_path / "smoke.md").read_text(encoding="utf-8").startswith("# exp30 results")
    row = payload["runs"][0]
    assert row["s4"]["identical"] and row["s4"]["identical_truncated"]
    gap = row["model"]["gap"]
    assert gap["ok"] and gap["gap"] == 30  # 1800 s longest lag at 60 s samples
    assert 1 <= row["model"]["n_components"] <= 8
    assert row["validity"]["n_outside"] > 0  # the regime pushed the hardness out of range
    try:
        exp30.run("smoke", tmp_path)
    except SystemExit as exc:
        assert "refusing to overwrite" in str(exc)
    else:
        raise AssertionError("run() overwrote existing results")


def _short(original):
    """run_one bound to the short durations."""
    return lambda seed, scenario: original(seed, scenario, SHORT)


def test_training_target_uses_only_labs_available_before_the_cut() -> None:
    """Target rows: exactly the lab samples available before the cut, at their sample rows."""
    t_s = np.arange(2000) * 60.0 + 50.0
    lab_t = t_s[240::240]
    labs = exp30.LabResults.with_delay(lab_t, np.arange(len(lab_t), dtype=float), 3600.0)
    cut = float(t_s[1000])
    y = exp30.training_target(t_s, labs, cut)
    used = np.flatnonzero(np.isfinite(y))
    assert np.array_equal(t_s[used], lab_t[lab_t + 3600.0 < cut])


def test_drift_term_and_ou_scale() -> None:
    """Drift is zero before the onset and ~0.1 per day after; the OU path has sd ~OU_SD."""
    t_s = np.arange(0, 3 * gen30.DAY_S, 60.0)
    x = np.full((len(t_s), len(gen30.TAGS)), 150.0)
    term = gen30.drift_term(t_s, x, t_s < gen30.DAY_S, gen30.DAY_S)
    assert term[t_s < gen30.DAY_S].max() == 0.0
    assert abs(term[-1] - 0.1 * (t_s[-1] - gen30.DAY_S) / gen30.DAY_S) < 1e-12
    ou = gen30.ou_path(200_000, np.random.default_rng(1))
    assert abs(ou.std() - gen30.OU_SD) < 0.1
