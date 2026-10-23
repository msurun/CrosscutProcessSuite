"""Smoke test of the exp28 harness: two cells end to end plus the bad-kind generators.

Uses seeds outside every reserved range (round 1 28001..28788, round 2 30001..30788) and checks
structure and determinism only, never the frozen criteria.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import exp28  # noqa: E402
import gen28  # noqa: E402

SMOKE_SEED = 990001  # not a protocol seed
SMOKE_SEEDS_ROUND2 = (990003, 990004)  # scratch seeds of the round 2 smoke test


def test_two_cells_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """A good and a valve cell run through identification, PI check, payload and both files."""
    cells = [("good", gen28.good_cells()[-6], SMOKE_SEED),
             ("valve", gen28.valve_cells()[-6], SMOKE_SEED + 1)]
    monkeypatch.setattr(exp28, "plan", lambda seeds, round_no=1: cells)
    payload = exp28.run("smoke", tmp_path)
    saved = json.loads((tmp_path / "smoke_runs.json").read_text(encoding="utf-8"))
    assert set(saved["criteria"]) == {"I1", "I2", "I3", "I4"}
    assert (tmp_path / "smoke.md").read_text(encoding="utf-8").startswith("# exp28 results")
    good, valve = payload["runs"]
    assert good["looks_integrating"] is not None and valve["looks_integrating"] is None
    assert good["verdict"] in ("ok", "low_confidence", "blocked")
    again = exp28.run_one(*cells[0])
    assert again["k_hat"] == good["k_hat"] and again["verdict"] == good["verdict"]


def test_record_geometry_and_bad_kinds() -> None:
    """Tail, lead and determinism of the generator; B3 tail short, B4 without a move."""
    cell = gen28.good_cells()[0]
    first = gen28.cell_record(cell, SMOKE_SEED)
    assert np.array_equal(first.pv, gen28.cell_record(cell, SMOKE_SEED).pv)
    assert first.t_s[-1] - first.meta["last_move_s"] == gen28.required_tail_s(cell.delay_s)
    lead = first.t_s[np.flatnonzero(first.out != gen28.OUT_BIAS)[0]]
    assert lead >= max(gen28.LEAD_S, 0.25 * first.t_s[-1])
    b3 = gen28.bad_record("B3", SMOKE_SEED)
    assert b3.t_s[-1] - b3.meta["last_move_s"] < gen28.required_tail_s(b3.plant["delay_s"])
    assert np.ptp(gen28.bad_record("B4", SMOKE_SEED).out) == 0.0
    for kind in ("B1", "B2"):
        record = gen28.bad_record(kind, SMOKE_SEED)
        assert record.t_s[-1] == gen28.BAD_WINDOW_S and record.plant["type"] == "fopdt"


def test_round2_seed_layout() -> None:
    """Round 2 plans the frozen seed ranges; round 1 keeps its own."""
    dev, test = exp28.plan("dev", 2), exp28.plan("test", 2)
    assert [s for _, _, s in dev] == list(range(30001, 30073))
    seeds = {kind: [s for k, _, s in test if k == kind or (kind == "bad" and k.startswith("B"))]
             for kind in ("good", "valve", "bad")}
    assert seeds["good"] == list(range(30101, 30389))
    assert seeds["valve"] == list(range(30501, 30789))
    assert seeds["bad"] == list(range(30401, 30501))
    assert exp28.plan("dev")[0][2] == 28001


def test_round2_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """A good cell and a B1 record through the product PI path; J1..J4 and the round 2 files."""
    cells = [("good", gen28.good_cells()[-6], SMOKE_SEEDS_ROUND2[0]),
             ("B1", "B1", SMOKE_SEEDS_ROUND2[1])]
    monkeypatch.setattr(exp28, "plan", lambda seeds, round_no=1: cells)
    payload = exp28.run("smoke", tmp_path, 2)
    saved = json.loads((tmp_path / "smoke2_runs.json").read_text(encoding="utf-8"))
    assert set(saved["criteria"]) == {"J1", "J2", "J3", "J4"} and saved["round"] == 2
    assert "(round 2)" in (tmp_path / "smoke2.md").read_text(encoding="utf-8")
    good = payload["runs"][0]
    assert good["theta_lower"] <= good["theta_hat"] <= good["theta_upper"]
    assert set(good["payload_model"]) == set(exp28.PAYLOAD_MODEL_KEYS)
    if good["accepted"] and "error" not in good["pi"]:
        assert good["pi"]["delay_used_s"] == good["payload_model"]["delay_used_s"]
        assert good["loop"] is not None


def test_round2_missing_payload_keys_is_a_clear_error() -> None:
    """A payload model without the interval keys raises and names them."""
    try:
        exp28.payload_model_keys({"delay_s": 5.0})
    except RuntimeError as error:
        assert "delay_upper_s" in str(error)
    else:
        raise AssertionError("missing keys were not reported")
