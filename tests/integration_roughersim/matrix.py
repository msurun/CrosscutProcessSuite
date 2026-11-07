"""Acceptance matrix for RougherSim virtual DCS integration (Phase 1/2, issue #53).

Mirrors the "L5 acceptance matrix" table in docs/TESTING_STRATEGY.md: one row per doc
line. The P2 line expands into the P2 end-to-end row plus one gateway row (G01..G12) per
test function in gateway/tests/test_gateway_scenarios.py. EXECUTORS maps a row_id to the
callable that runs a row once its status is ready.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

VALID_PHASES: frozenset[str] = frozenset({"P1", "P1-dq", "P2", "P3", "P4", "P6", "P7"})
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
    ),
    *_gateway_rows(),
    MatrixRow(
        row_id="L5-P3",
        phase="P3",
        milestone="M4+M6",
        scenarios=("step_test", "stiction", "nominal"),
        criterion=(
            "weak loop detected -> step test -> tuning -> write after confirmation -> "
            "KPI improves vs ground truth -> rollback restores the old parameters"
        ),
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


EXECUTORS.update(
    {f"L5-G{n:02d}": _gateway_executor(ref) for n, (ref, _) in enumerate(GATEWAY_CASES, 1)}
)
