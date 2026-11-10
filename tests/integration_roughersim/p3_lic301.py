"""LIC301 level-loop acceptance chain for L5-P3: weak detection, model, live tuning, rollback.

The pinned fitter returns zero dead time at the 60 s recorder resolution, so this chain uses a
documented one-sample delay floor; the raw zero-delay refusal is a separate FINDING test.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from crosscut_gateway import engine
from crosscut_gateway.actor import ActorContext
from crosscut_gateway.engine_params import ParamConfig, param_set_key
from crosscut_gateway.interfaces import ParamItem, ParamPolicy, ParamSetProposal
from p3_chain import AUTO_MODE, calculate_iae, closed_window, verify_improvement
from p3_data import SAMPLE_INTERVAL_S
from rs_harness import Harness, S, plant_map_for, rs_server

LOOP = "LIC301"
GAIN, TI = f"{LOOP}.GAIN", f"{LOOP}.TI"
WEAK_TUNING = {"gain": 11.0, "ti": 10000.0}  # flagged poor_performance; still 5 pp headroom
WEAK_TARGETS = {GAIN: WEAK_TUNING["gain"], TI: WEAK_TUNING["ti"]}
ROBUSTNESS = 1.0  # SIMC slider: the robust end of the range
MIN_DELAY_S = SAMPLE_INTERVAL_S  # documented one-sample floor for the zero fitted delay
SERVER_SPEED = 20.0  # simulation seconds per wall second, as in the gateway rows
PROPOSAL_LIFETIME_S = 3600
ALICE = ActorContext(actor="alice", roles=("engineer",))
BOB = ActorContext(actor="bob", roles=("engineer",))
POLICIES = {
    GAIN: ParamPolicy(LOOP, "gain", "OUT/PV", "siemens_pid_compact",
                      (0.001, 500.0), 2.0, 0.0, 0.0, ("MAN", "AUTO", "CAS", "RSP")),
    TI: ParamPolicy(LOOP, "ti", "s", "siemens_pid_compact",
                    (1.0, 20000.0), 100.0, 0.0, 0.0, ("MAN", "AUTO", "CAS", "RSP")),
}


@contextmanager
def lic301_rig(tmp: Path) -> Iterator[tuple[Harness, engine.WriteGateway]]:
    """Start RougherSim, write the weak baseline, and yield the real parameter gateway."""
    tmp.mkdir(parents=True, exist_ok=True)
    with rs_server(tmp / "server.log", None, SERVER_SPEED) as port:
        harness = Harness(plant_map_for(port), SERVER_SPEED)
        try:
            harness.wait_ready()
            harness.write_param(GAIN, WEAK_TUNING["gain"])
            harness.write_param(TI, WEAK_TUNING["ti"])
            gateway = engine.WriteGateway(harness, {}, "confirm",
                                          params=ParamConfig(dict(POLICIES), harness))
            yield harness, gateway
        finally:
            harness.close()


def read_tuning(harness: Harness) -> dict[str, float]:
    """Read both stored LIC301 parameters through the real adapter."""
    return {tag: harness.read_param(tag) for tag in POLICIES}


def recorder_values(targets: dict[str, float]) -> dict[str, float]:
    """Map policy target values to the recorder's gain and ti keys."""
    return {"gain": targets[GAIN], "ti": targets[TI]}


def apply_values(
    harness: Harness, gateway: engine.WriteGateway, targets: dict[str, float],
    proposal_id: str, rollback_of: str | None = None,
) -> dict[str, float]:
    """Propose as Alice, approve as Bob, and return the values read back from the plant."""
    now = harness.now_ns()
    items = tuple(
        ParamItem(POLICIES[tag].param, tag, POLICIES[tag].unit, POLICIES[tag].vendor_form,
                  harness.read_param(tag), float(value))
        for tag, value in targets.items()
    )
    proposal = ParamSetProposal(proposal_id, LOOP, items, ALICE.actor, now,
                                now + PROPOSAL_LIFETIME_S * S, "L5-P3 LIC301", rollback_of)
    gateway.tick(now)
    assert gateway.propose_params(proposal, actor_ctx=ALICE).reason_code == "queued"
    decision = gateway.approve(param_set_key(proposal), actor_ctx=BOB)
    assert decision.accepted and decision.reason_code == "applied", decision.reason_code
    return read_tuning(harness)


def assert_improvement(
    lic301: dict[str, Any], default: dict[str, np.ndarray], applied: dict[str, np.ndarray]
) -> None:
    """Require the applied window to beat the weak baseline and stay near the nominal default."""
    verify_improvement((closed_window(lic301["baseline"], LOOP, AUTO_MODE),
                        closed_window(applied, LOOP, AUTO_MODE),
                        closed_window(default, LOOP, AUTO_MODE)), lic301["truth"])


def assert_rollback_replay(
    replay: dict[str, np.ndarray], baseline: dict[str, np.ndarray], tolerance: float
) -> None:
    """Require the replayed rollback KPI to match the weak baseline within tolerance."""
    assert calculate_iae(closed_window(replay, LOOP, AUTO_MODE)) == pytest.approx(
        calculate_iae(closed_window(baseline, LOOP, AUTO_MODE)), rel=tolerance)
