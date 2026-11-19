"""L5-C01..C05: the fuzzy APC core against a live RougherSim OPC UA server.

Real chain: controller job (runtime wiring) -> OpcUaConnector snapshots -> proposals -> real
WriteGateway (supervised) -> OpcUaPlant -> RougherSim. Skips with a message when RougherSim is
absent or not at the pin. C02 uses the pv_fault hook of RougherSim 0.13.0.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from controller_rows import (
    CV_A,
    CV_B,
    LATE_FAULT_HOOK,
    MOVE_MAX,
    ctl_rig,
    transmitter_fault_hook,
)
from gateway_rows import POLICY, TAG
from golden import checkout_problem, load_pin, roughersim_dir
from p6_rows import P6_CASES

MOVE_TOL = 1e-9
CYCLES_ON = 6
MAX_CYCLES_TO_SHED = 400  # one plant step per cycle; the late fault starts at 120 s


@pytest.fixture(scope="module")
def checkout() -> None:
    """Skip the module unless the sibling RougherSim checkout is the pinned release."""
    problem = checkout_problem(roughersim_dir(), load_pin())
    if problem:
        pytest.skip(problem)


def c01(tmp: Path) -> None:
    """A switched-on fuzzy controller runs cycles and its proposals are written by the gateway."""
    with ctl_rig(tmp) as c:
        assert c.cycle()["state"] == "off"
        c.command("switch_on")
        records = [c.cycle() for _ in range(CYCLES_ON)]
        assert records[0]["state"] == "on", records[0]
        assert c.accepted() >= 2, [d.reason_code for d in c.decisions]
        assert len(c.seen) >= 2 and len(c.decisions) == len(c.seen)
        assert all(abs(new - seen) <= MOVE_MAX + MOVE_TOL for seen, new in c.seen)
        written = [v for _, tag, v in c.rig.h.writes if tag == TAG]
        assert written and all(POLICY.limits[0] <= v <= POLICY.limits[1] for v in written)
        assert c.rig.h.read(TAG) == pytest.approx(written[-1], abs=POLICY.readback_tolerance)
        assert c.rig.source() == "remote"


def c02_second_cv(tmp: Path) -> None:
    """A failed transmitter turns its CV bad; a second CV keeps the controller running."""
    with ctl_rig(tmp, cvs=(CV_A, CV_B), hook=transmitter_fault_hook(CV_A)) as c:
        c.command("switch_on")
        for _ in range(CYCLES_ON):
            record = c.cycle()
        assert record["state"] == "on"


def c02_only_cv(tmp: Path) -> None:
    """A controller that is on sheds with no_good_cv when its only CV fails (fault from 120 s)."""
    with ctl_rig(tmp, hook=LATE_FAULT_HOOK) as c:
        c.command("switch_on")
        records = [c.cycle()]
        assert records[0]["state"] == "on", records[0]
        while records[-1]["state"] == "on" and len(records) < MAX_CYCLES_TO_SHED:
            records.append(c.cycle())
        assert (records[-1]["state"], records[-1]["reason"]) == ("shed", "no_good_cv")


def c02_only_cv_refused(tmp: Path) -> None:
    """Fault from t=0: switch_on is refused (standby, no_good_cv) and nothing is proposed."""
    with ctl_rig(tmp, hook=transmitter_fault_hook(CV_A)) as c:
        c.command("switch_on")
        first = c.cycle()
        assert (first["state"], first["reason"]) == ("standby", "no_good_cv"), first
        assert c.cycle()["state"] == "standby"
        assert c.decisions == []


def c03(tmp: Path) -> None:
    """Base loop to manual in RougherSim: the controller sheds within one cycle, no proposals."""
    with ctl_rig(tmp) as c:
        c.command("switch_on")
        for _ in range(3):
            assert c.cycle()["state"] == "on"
        n_accepted, n_writes = c.accepted(), len(c.rig.h.writes)
        assert n_accepted >= 1 and c.rig.h.loop_mode(TAG) == "RSP"
        c.rig.step()  # let the last accepted write settle before the operator acts
        c.operator_manual()
        assert c.rig.h.loop_mode(TAG) == "MAN"
        record = c.cycle()  # the first cycle after the operator's action
        assert (record["state"], record["reason"]) == ("shed", "mv_unavailable"), record
        for _ in range(3):
            assert c.cycle()["state"] == "shed"
        assert c.rig.h.loop_mode(TAG) == "MAN"
        assert (c.accepted(), len(c.rig.h.writes)) == (n_accepted, n_writes)


def c04(tmp: Path) -> None:
    """A new host on the same data root restores standby, never on."""
    with ctl_rig(tmp) as c:
        c.command("switch_on")
        assert [c.cycle() for _ in range(3)][-1]["state"] == "on"
        n = len(c.decisions)
        c.start_job()  # restart of the runtime: a new ControllerHost
        record = c.cycle()
        assert record["state"] == "standby", record
        assert c.cycle()["state"] == "standby"
        assert len(c.decisions) == n


def c05(tmp: Path) -> None:
    """Operator switch_off through the command queue stops proposals at the next cycle."""
    with ctl_rig(tmp) as c:
        c.command("switch_on")
        for _ in range(3):
            c.cycle()
        assert c.accepted() >= 1
        n = len(c.decisions)
        c.command("switch_off")
        record = c.cycle()
        assert (record["state"], record["reason"]) == ("off", "switch_off"), record
        for _ in range(3):
            assert c.cycle()["state"] == "off"
        assert len(c.decisions) == n


ROWS = {"C01": c01, "C03": c03, "C04": c04, "C05": c05}


@pytest.mark.slow
@pytest.mark.parametrize("row", list(ROWS))
def test_controller_row_on_roughersim(row: str, tmp_path: Path, checkout: None) -> None:
    """The controller row holds on the real connector, gateway, adapter and RougherSim."""
    ROWS[row](tmp_path)



@pytest.mark.slow
def test_c02_failed_cv_with_second_cv_keeps_running(tmp_path: Path, checkout: None) -> None:
    """C02a: the failed CV is bad and the controller keeps running on the second CV."""
    c02_second_cv(tmp_path)


@pytest.mark.slow
def test_c02_failed_only_cv_refuses_switch_on(tmp_path: Path, checkout: None) -> None:
    """C02b (as the host behaves): a controller never on cannot shed; switch_on is refused."""
    c02_only_cv_refused(tmp_path)


@pytest.mark.slow
def test_c02_failed_only_cv_sheds(tmp_path: Path, checkout: None) -> None:
    """C02b: with only the failed CV the controller sheds (no_good_cv)."""
    c02_only_cv(tmp_path)


@pytest.mark.slow
@pytest.mark.parametrize("case", P6_CASES, ids=[case.__name__ for case in P6_CASES])
def test_p6_controller_row_on_roughersim(
    case: Callable[[Path], None], tmp_path: Path, checkout: None
) -> None:
    """P6 confirm, supervised and operator-priority outcomes hold on the pinned simulator."""
    case(tmp_path)
