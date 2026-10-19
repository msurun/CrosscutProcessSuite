"""Tests for the valve test CLI in ``crosscut_loops.valve_test_cli``.

The CLI has two subcommands: ``plan`` prints a stroke-test schedule, and
``analyze`` fits a deadband model to a logged CSV.  These tests exercise the
public contract of ``main(argv) -> int``: its exit code and its console output.
"""

import csv

from crosscut_loops.valve_test import plan_stroke_test
from crosscut_loops.valve_test_cli import main

# Sample counts and amplitudes used to build the synthetic CSV.  All values
# match the arguments we pass to ``main(["analyze", ...])`` below.
START_OP_PCT = 50.0
DWELL_S = 30
OP_STEP_BEFORE_STAIRCASE = 30
STARVED_DWELL_SAMPLES = 30
PV_GAIN = 2.0
REVERSAL_DEADBAND_OP_PCT = 0.4
CSV_HEADER = ["t_s", "op", "pv"]


def build_staircase_op(plan) -> list[float]:
    """Return the commanded op for each sample: 30 filler samples, then each step's target."""
    filler = [START_OP_PCT] * OP_STEP_BEFORE_STAIRCASE
    steps = [step.op_target for step in plan.steps for _ in range(step.dwell_s)]
    return filler + steps


def simulate_backlash(op: list[float]) -> list[float]:
    """Return valve position following each commanded op with a 0.8 % reversal deadband.

    Backlash model: when moving up, the valve lags by 0.4 % below ``op``;
    when moving down, it lags 0.4 % above ``op``.  The total deadband on a
    reversal is 0.8 %.
    """
    positions = [op[0]]
    for command in op[1:]:
        previous = positions[-1]
        if command > previous + REVERSAL_DEADBAND_OP_PCT:
            positions.append(command - REVERSAL_DEADBAND_OP_PCT)
        elif command < previous - REVERSAL_DEADBAND_OP_PCT:
            positions.append(command + REVERSAL_DEADBAND_OP_PCT)
        else:
            positions.append(previous)
    return positions


def write_synthetic_csv(csv_path, include_pv: bool = True) -> None:
    """Write a backlash-shaped stroke-test log to ``csv_path``."""
    plan = plan_stroke_test(START_OP_PCT, DWELL_S)
    op = build_staircase_op(plan)
    position = simulate_backlash(op)
    pv = [START_OP_PCT + PV_GAIN * (p - START_OP_PCT) for p in position]
    header = CSV_HEADER if include_pv else ["t_s", "op"]

    with csv_path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        for t_s, (op_value, pv_value) in enumerate(zip(op, pv, strict=True)):
            row = [t_s, op_value, pv_value] if include_pv else [t_s, op_value]
            writer.writerow(row)


def test_plan_returns_zero() -> None:
    """A valid plan request exits with status 0."""
    exit_code = main(["plan", "--op-start", "50", "--dwell-s", "30"])
    assert exit_code == 0


def test_plan_prints_manual_first(capsys) -> None:
    """The first printed plan line describes the MANUAL phase."""
    main(["plan", "--op-start", "50", "--dwell-s", "30"])
    first_line = capsys.readouterr().out.splitlines()[0]
    assert "MANUAL" in first_line


def test_plan_prints_auto_somewhere(capsys) -> None:
    """The plan includes an AUTO phase somewhere in the output."""
    main(["plan", "--op-start", "50", "--dwell-s", "30"])
    output = capsys.readouterr().out
    assert "AUTO" in output


def test_plan_last_line_is_total_test_time(capsys) -> None:
    """The last plan line reports the total test time."""
    main(["plan", "--op-start", "50", "--dwell-s", "30"])
    last_line = capsys.readouterr().out.splitlines()[-1]
    assert last_line.startswith("Total test time:")


def test_plan_out_of_range_returns_two(capsys) -> None:
    """A plan whose stroke exceeds 0..100 op is rejected with status 2."""
    exit_code = main(["plan", "--op-start", "99.5", "--dwell-s", "30"])
    assert exit_code == 2


def test_plan_out_of_range_writes_to_stderr(capsys) -> None:
    """An out-of-range plan explains the failure on stderr."""
    main(["plan", "--op-start", "99.5", "--dwell-s", "30"])
    assert capsys.readouterr().err != ""


def test_analyze_synthetic_csv_returns_zero(tmp_path) -> None:
    """Analyzing a backlash-shaped CSV exits with status 0."""
    csv_path = tmp_path / "valve_log.csv"
    write_synthetic_csv(csv_path)
    exit_code = main(["analyze", str(csv_path), "--op-start", "50", "--dwell-s", "30"])
    assert exit_code == 0


def test_analyze_output_mentions_deadband(tmp_path, capsys) -> None:
    """The analysis output contains a deadband line."""
    csv_path = tmp_path / "valve_log.csv"
    write_synthetic_csv(csv_path)
    main(["analyze", str(csv_path), "--op-start", "50", "--dwell-s", "30"])
    assert "deadband" in capsys.readouterr().out.lower()


def test_analyze_output_is_marked_synthetic(tmp_path, capsys) -> None:
    """The analysis output carries the synthetic-validation disclaimer."""
    csv_path = tmp_path / "valve_log.csv"
    write_synthetic_csv(csv_path)
    main(["analyze", str(csv_path), "--op-start", "50", "--dwell-s", "30"])
    assert "Synthetic validation only" in capsys.readouterr().out


def test_analyze_missing_pv_column_returns_two(tmp_path) -> None:
    """A CSV without the pv column is rejected with status 2."""
    csv_path = tmp_path / "valve_log.csv"
    write_synthetic_csv(csv_path, include_pv=False)
    exit_code = main(["analyze", str(csv_path), "--op-start", "50", "--dwell-s", "30"])
    assert exit_code == 2


def test_analyze_missing_file_returns_two(tmp_path) -> None:
    """A CSV path that does not exist is rejected with status 2."""
    missing_path = tmp_path / "does_not_exist.csv"
    exit_code = main(["analyze", str(missing_path), "--op-start", "50", "--dwell-s", "30"])
    assert exit_code == 2
