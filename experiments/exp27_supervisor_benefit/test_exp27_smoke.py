"""Smoke test of the exp27 harness: one short seed end to end (all arms, faults, E5, report).

Uses a 6 h plan with the fault at 3 h so it runs in well under a minute; checks structure and
determinism, not the frozen criteria. Never touches the test seeds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import exp27  # noqa: E402

PLAN = exp27.Plan(duration_s=6 * 3600.0, skip_s=3600.0, fault_start_s=3 * 3600.0)
SEED = 27001


def test_one_short_seed_end_to_end(tmp_path: Path) -> None:
    """Run one seed, write both files, and get the same numbers on a second run."""
    payload = exp27.run((SEED,), PLAN, tmp_path, "smoke")
    assert (tmp_path / "smoke.md").read_text(encoding="utf-8").startswith("# exp27 results")
    saved = json.loads((tmp_path / "smoke_runs.json").read_text(encoding="utf-8"))
    row = saved["runs"][0]
    assert set(row["arms"]) == {"a", "b", "c"}
    assert set(saved["criteria"]) == {"E1", "E2", "E3", "E4", "E5"}
    assert len(row["log_b"]) == len(row["log_c"]) == int(PLAN.duration_s // exp27.WINDOW_S) - 1
    assert row["arms"]["c"]["gate_open_share"] > 0.5  # loop knowledge given: not 'not_assessed'
    for fault in row["e1"].values():
        assert fault["inside_non_hold"] == 0 and fault["named"]
    again = exp27.run_seed(SEED, PLAN, exp27.load_supervisors())
    assert again["arms"] == payload["runs"][0]["arms"]


def test_acceptance_draws_are_shared_and_seeded() -> None:
    """Arms b and c see the same per-instant draws; another seed gives other draws."""
    first = exp27.acceptance_draws(SEED, PLAN)
    assert (first == exp27.acceptance_draws(SEED, PLAN)).all()
    full = exp27.Plan()
    assert (exp27.acceptance_draws(SEED, full) != exp27.acceptance_draws(SEED + 1, full)).any()
    assert len(first) == int(PLAN.duration_s // exp27.WINDOW_S)
