"""Acceptance matrix for RougherSim virtual DCS integration (Phase 1/2, issue #53).

Mirrors the "L5 acceptance matrix" table in docs/TESTING_STRATEGY.md: one row per doc
line. The P2 line expands into the P2 end-to-end row plus one gateway row (G01..G12) per
test function in gateway/tests/test_gateway_scenarios.py. EXECUTORS maps a row_id to the
callable that runs a row once its status is ready.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

VALID_PHASES: frozenset[str] = frozenset({"P1", "P1-dq", "P2", "P2.5", "P3", "P4", "P6", "P7"})
VALID_STATUSES: frozenset[str] = frozenset({"pending", "ready"})

EXECUTORS: dict[str, Callable[[], None]] = {}


@dataclass(frozen=True)
class MatrixRow:
    """One acceptance criterion of the L5 Virtual DCS matrix."""

    row_id: str
    phase: str
    milestone: str
    scenarios: tuple[str, ...]
    criterion: str
    status: str = "pending"
    scenario_ref: str | None = None


GATEWAY_CASES: tuple[tuple[str, str], ...] = (
    (
        "test_cas_handover_take_and_give_back",
        "A write takes the setpoint remote; a kill gives it back to local.",
    ),
    (
        "test_watchdog_loss_returns_plant_to_local",
        "When the gateway stops ticking, the plant is local within watchdog_s.",
    ),
    (
        "test_rejected_write_stops_and_reports",
        "If the control system refuses, the gateway reports it and stops writing that target.",
    ),
    (
        "test_limit_and_rate_clamp",
        "A written value never exceeds limits, max_step or max_rate_per_s.",
    ),
    (
        "test_operator_override_and_hold_off",
        "After an operator setpoint change, no write for hold_off_s, then only after re-enable.",
    ),
    (
        "test_readback_mismatch_stops_writing",
        "A read-back differing by more than the tolerance disables the target.",
    ),
    (
        "test_communication_loss_mid_write_fails_closed",
        "A link failure during a write ends in a disabled target and local setpoint, "
        "no exception.",
    ),
    (
        "test_duplicate_proposal_is_idempotent",
        "The same proposal sent twice produces exactly one write.",
    ),
    (
        "test_mode_change_race_never_writes_in_wrong_mode",
        "If the operator leaves CAS between proposals, the next one is refused, "
        "nothing written.",
    ),
    (
        "test_tampered_policy_file_refuses_to_start",
        "A policy file whose hash differs from the pinned one prevents startup.",
    ),
    (
        "test_kill_switch_stops_writes_within_one_tick",
        "After kill() and one tick, no write is accepted and the setpoint is local.",
    ),
    (
        "test_dry_run_sends_nothing",
        "A dry run writes an audit record of the would-be write and sends zero writes.",
    ),
)


def _gateway_rows() -> tuple[MatrixRow, ...]:
    """Build rows L5-G01..L5-G12, one per gateway scenario test function."""
    return tuple(
        MatrixRow(
            row_id=f"L5-G{number:02d}",
            phase="P2",
            milestone="M7",
            scenarios=("gateway",),
            criterion=criterion,
            status="ready",
            scenario_ref=scenario_ref,
        )
        for number, (scenario_ref, criterion) in enumerate(GATEWAY_CASES, start=1)
    )


MATRIX: tuple[MatrixRow, ...] = (
    MatrixRow(
        row_id="L5-P1",
        phase="P1",
        milestone="M5 then M6",
        scenarios=("nominal",),
        criterion=(
            "before M6: Crosscut loader reads the recording unchanged and loop triage works; "
            "after M6: catalogue built in the GUI, live loop KPI within tolerance of the "
            "ground-truth KPI, no file edited by hand (e2e)"
        ),
        status="ready",
    ),
    MatrixRow(
        row_id="L5-P1-dq",
        phase="P1-dq",
        milestone="M5",
        scenarios=("sensor_faults",),
        criterion=(
            "onboarding data-quality report flags injected faults with agreed precision and recall"
        ),
    ),
    MatrixRow(
        row_id="L5-P2-e2e",
        phase="P2",
        milestone="M7",
        scenarios=("all 12 gateway scenarios",),
        criterion=(
            "12 strict-xfail scenarios in gateway/tests pass without manual intervention; "
            "e2e proposal -> confirm -> write -> read-back -> audit entry; "
            "kill switch stops writes within one cycle"
        ),
        status="ready",
    ),
    *_gateway_rows(),
    MatrixRow(
        row_id="L5-P25",
        phase="P2.5",
        milestone="M7",
        scenarios=("operator_actions",),
        criterion=(
            "a switched-on fuzzy controller's proposals reach the gateway and are written "
            "within move_max; "
            "a failed transmitter drops its CV (shed with no_good_cv when none is left, "
            "pv_fault hooks of RougherSim 0.13.1; with only that CV a fault from t=0 refuses "
            "switch_on); "
            "base loop to manual sheds it within one cycle; "
            "restart restores standby, never on; "
            "operator switch_off stops proposals at the next cycle"
        ),
        status="ready",
    ),
    MatrixRow(
        row_id="L5-P3",
        phase="P3",
        milestone="M4+M6",
        scenarios=("step_test", "stiction", "nominal"),
        criterion=(
            "weak loop detected -> step test -> tuning -> write after confirmation -> "
            "KPI improves vs ground truth -> rollback restores the old parameters"
        ),
        status="ready",
    ),
    MatrixRow(
        row_id="L5-P4",
        phase="P4",
        milestone="post-MVP (lab samples)",
        scenarios=("hardness_shift",),
        criterion=(
            "generic engine reproduces ground-truth quality within stated error; "
            "validity flag trips on injected analyser fault"
        ),
    ),
    MatrixRow(
        row_id="L5-P6",
        phase="P6",
        milestone="M7",
        scenarios=("operator_actions", "hardness_shift"),
        criterion=(
            "proposals flow through the gateway in confirm then supervised; "
            "operator action always wins"
        ),
    ),
    MatrixRow(
        row_id="L5-P7",
        phase="P7",
        milestone="after MVP",
        scenarios=("step_test", "hardness_shift"),
        criterion=(
            "MPC writes setpoints through the gateway in supervised mode and respects constraints"
        ),
    ),
)


def _gateway_executor(scenario_ref: str) -> Callable[[], None]:
    """Executor of a gateway row: run its scenario on RougherSim in a scratch directory."""

    def execute() -> None:
        import tempfile
        from pathlib import Path

        from gateway_rows import run_scenario

        with tempfile.TemporaryDirectory() as tmp:
            run_scenario(scenario_ref, Path(tmp))

    return execute


def _controller_executor() -> None:
    """Executor of L5-P25: rows C01, C03, C04 and C05 (C02 runs in pytest, pv_fault hooks)."""
    import tempfile
    from pathlib import Path

    from test_l5_controller_rows import ROWS

    for row in ROWS.values():
        with tempfile.TemporaryDirectory() as tmp:
            row(Path(tmp))


def _p1_executor() -> None:
    """Executor of L5-P1: catalogue from a nominal recording, live KPI row for every loop."""
    from p1_live import execute

    execute()


def _p1_dq_executor() -> None:
    """Executor of L5-P1-dq: onboarding sensor-fault findings scored against injected faults."""
    from p1_dq import execute

    execute()


def _p3_executor() -> None:
    """Executor of L5-P3: run the P3 tuning-chain tests of test_l5_p3.py in a pytest subprocess."""
    import subprocess
    import sys
    from pathlib import Path

    here = Path(__file__).parent
    command = [sys.executable, "-m", "pytest", str(here / "test_l5_p3.py"), "-q", "-o", "addopts="]
    done = subprocess.run(command, cwd=here, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-500:]


def _p2_executor() -> None:
    """Executor of L5-P2-e2e: gateway scenario tests, then every gateway row on RougherSim."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, "-m", "pytest", str(root / "gateway" / "tests" /
                                                   "test_gateway_scenarios.py"),
               "-q", "-o", "addopts="]
    done = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-500:]
    for ref, _ in GATEWAY_CASES:
        _gateway_executor(ref)()


EXECUTORS["L5-P25"] = _controller_executor
EXECUTORS["L5-P2-e2e"] = _p2_executor
EXECUTORS["L5-P1"] = _p1_executor
EXECUTORS["L5-P1-dq"] = _p1_dq_executor
EXECUTORS["L5-P3"] = _p3_executor
EXECUTORS.update(
    {f"L5-G{n:02d}": _gateway_executor(ref) for n, (ref, _) in enumerate(GATEWAY_CASES, 1)}
)
