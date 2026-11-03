"""Acceptance matrix for RougherSim virtual DCS integration (Phase 1/2, issue #53).

Maps product claims across Crosscut modules to RougherSim simulation scenarios,
milestone prerequisites, and gateway execution hooks.
"""

from __future__ import annotations

from dataclasses import dataclass

VALID_MODULES: frozenset[str] = frozenset(
    {"loops", "anomaly", "softsensor", "gateway", "runtime", "connectors"}
)
VALID_STATUSES: frozenset[str] = frozenset({"pending", "ready"})


@dataclass(frozen=True)
class MatrixRow:
    """One acceptance criterion in the L5 Virtual DCS matrix."""

    row_id: str
    module: str
    claim: str
    scenario_id: str
    needs: str
    status: str
    scenario_ref: str | None = None


MATRIX: tuple[MatrixRow, ...] = (
    MatrixRow(
        row_id="L5-01",
        module="connectors",
        claim=(
            "Crosscut loader reads the recording unchanged, loop triage works, "
            "and catalogue is built in the GUI."
        ),
        scenario_id="nominal",
        needs="RougherSim recording export (M5) and ABB OPC UA profile (M6)",
        status="pending",
    ),
    MatrixRow(
        row_id="L5-02",
        module="anomaly",
        claim=(
            "Onboarding data-quality report flags injected faults with agreed "
            "precision and recall."
        ),
        scenario_id="sensor_faults",
        needs="sensor_faults scenario with ground-truth fault log (RougherSim M5)",
        status="pending",
    ),
    MatrixRow(
        row_id="L5-03",
        module="gateway",
        claim=(
            "Write Gateway proposal, confirmation, write, readback, audit, and kill switch "
            "operate end-to-end against virtual DCS."
        ),
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
    ),
    MatrixRow(
        row_id="L5-04",
        module="loops",
        claim=(
            "Weak loop detected, step test executed, tuning applied after confirmation, "
            "KPI improves vs ground truth, and rollback restores parameters."
        ),
        scenario_id="step_test",
        needs="RougherSim step_test and stiction scenarios with tuning hooks (M4+M6)",
        status="pending",
    ),
    MatrixRow(
        row_id="L5-05",
        module="softsensor",
        claim=(
            "Generic virtual sensor engine reproduces ground-truth quality within stated error "
            "and validity flag trips on injected analyser fault."
        ),
        scenario_id="hardness_shift",
        needs=(
            "RougherSim hardness_shift scenario with ground-truth assay and analyzer "
            "fault injection"
        ),
        status="pending",
    ),
    MatrixRow(
        row_id="L5-06",
        module="loops",
        claim=(
            "Proposals flow through the gateway in confirm then supervised mode, "
            "and operator action always wins."
        ),
        scenario_id="operator_actions",
        needs="RougherSim operator_actions scenario and M7 gateway test hooks",
        status="pending",
    ),
    MatrixRow(
        row_id="L5-07",
        module="runtime",
        claim=(
            "MPC writes setpoints through the gateway in supervised mode and respects constraints."
        ),
        scenario_id="step_test",
        needs="RougherSim M7 gateway integration with multivariable model and constraint hooks",
        status="pending",
    ),
    MatrixRow(
        row_id="L5-G01",
        module="gateway",
        claim="A write takes the setpoint remote; a kill gives it back to local control.",
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
        scenario_ref="test_cas_handover_take_and_give_back",
    ),
    MatrixRow(
        row_id="L5-G02",
        module="gateway",
        claim=(
            "When the gateway stops ticking, the plant returns to local control within "
            "watchdog timeout."
        ),
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
        scenario_ref="test_watchdog_loss_returns_plant_to_local",
    ),
    MatrixRow(
        row_id="L5-G03",
        module="gateway",
        claim=(
            "If the control system refuses, the gateway reports it and stops "
            "writing that target."
        ),
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
        scenario_ref="test_rejected_write_stops_and_reports",
    ),
    MatrixRow(
        row_id="L5-G04",
        module="gateway",
        claim="A written value never exceeds limits, max_step, or max_rate_per_s.",
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
        scenario_ref="test_limit_and_rate_clamp",
    ),
    MatrixRow(
        row_id="L5-G05",
        module="gateway",
        claim=(
            "After an operator setpoint change, no write occurs for hold-off duration, "
            "then only after re-enable."
        ),
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
        scenario_ref="test_operator_override_and_hold_off",
    ),
    MatrixRow(
        row_id="L5-G06",
        module="gateway",
        claim="A read-back differing by more than the tolerance disables the target.",
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
        scenario_ref="test_readback_mismatch_stops_writing",
    ),
    MatrixRow(
        row_id="L5-G07",
        module="gateway",
        claim=(
            "A communication link failure during a write fails closed with disabled target "
            "and local setpoint."
        ),
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
        scenario_ref="test_communication_loss_mid_write_fails_closed",
    ),
    MatrixRow(
        row_id="L5-G08",
        module="gateway",
        claim="The same write proposal sent twice produces exactly one physical write.",
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
        scenario_ref="test_duplicate_proposal_is_idempotent",
    ),
    MatrixRow(
        row_id="L5-G09",
        module="gateway",
        claim=(
            "If the operator leaves cascade mode between proposals, the next proposal is refused "
            "and nothing is written."
        ),
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
        scenario_ref="test_mode_change_race_never_writes_in_wrong_mode",
    ),
    MatrixRow(
        row_id="L5-G10",
        module="gateway",
        claim="A policy file whose hash differs from the pinned digest prevents gateway startup.",
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
        scenario_ref="test_tampered_policy_file_refuses_to_start",
    ),
    MatrixRow(
        row_id="L5-G11",
        module="gateway",
        claim=(
            "After emergency kill and one tick, no further writes are accepted and setpoints "
            "return to local."
        ),
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
        scenario_ref="test_kill_switch_stops_writes_within_one_tick",
    ),
    MatrixRow(
        row_id="L5-G12",
        module="gateway",
        claim=(
            "A dry run writes an audit record of the would-be write and sends zero writes "
            "to the plant."
        ),
        scenario_id="TBD",
        needs="OPC UA write profile + gateway test hooks (RougherSim M7)",
        status="pending",
        scenario_ref="test_dry_run_sends_nothing",
    ),
)
