"""L5-P7a: the MPC controller advises on the live RougherSim grinding MIMO bed (#184).

Skips with a message when the RougherSim checkout is missing or lacks the grinding bed (M9 #22 and
the step-test truth #24; both are newer than the pin of ``pin.json``, so point ``ROUGHERSIM_DIR`` at
a checkout that has them). Advisory only: the test proves proposals are formed with reason codes and
that nothing reaches the plant.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from crosscut_runtime.controllers.commands import enqueue_command
from mpc_rows import MV_MOVE_MAX, grinding_available, mpc_rig

CYCLES = 8
CODES = {"move", "hold", "shed", "limit", "no_target", "at_target", "input_bad", "bumpless_start"}


@pytest.fixture(scope="module")
def bed() -> None:
    """Skip the module unless the checkout has the grinding MIMO bed."""
    problem = grinding_available()
    if problem:
        pytest.skip(problem)


@pytest.mark.slow
def test_p7a_advisory_proposals_on_the_grinding_bed(tmp_path: Path, bed: None) -> None:
    """Advisory MPC: bumpless first cycle, reason codes for every MV, no write, no proposal."""
    with mpc_rig(tmp_path) as rig:
        assert rig.cycle()["state"] == "off"
        enqueue_command(rig.root, "mpc1", "switch_on")  # as the console does
        records = [rig.cycle() for _ in range(CYCLES)]
        assert {r["state"] for r in records} == {"advisory"}, [r["reason"] for r in records]
        assert rig.sent == []
        data = [r["diagnostics"] for r in records if r["diagnostics"]]
        assert data and all(d["kind"] == "mpc" for d in data)
        assert data[0]["status"] == "bumpless_start"
        for d in data:
            assert {m["id"] for m in d["mvs"]} == set(MV_MOVE_MAX)
            assert all(m["code"] in CODES for m in d["mvs"])
        later = data[1:]
        assert later, "no cycle after the bumpless start"
        for d in later:
            for m in d["mvs"]:
                assert abs(m["proposed"] - m["sp"]) <= MV_MOVE_MAX[m["id"]] + 1e-6
                assert m["lo"] <= m["proposed"] <= m["hi"]
            assert all(len(c["predicted"]) == 20 for c in d["cvs"])
        for loop in MV_MOVE_MAX:  # nothing was written
            assert rig.read(f"{loop}.SP") == pytest.approx(rig.start[f"{loop}.SP"], abs=1e-6)
