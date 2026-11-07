"""Exercise acceptance row L5-P3 against the pinned RougherSim offline recorder.
Detection remains independent of the known 60 s identification resolution limitation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from golden import checkout_problem, load_pin, roughersim_dir
from p3_chain import (
    DEFAULT_TUNING,
    SEVERITY,
    IdentificationResolutionError,
    calculate_iae,
    choose_weak_baseline,
    closed_window,
    detect_weakness,
    identify_model,
    propose_tuning,
    read_proposed_values,
    restore_original_values,
    validate_identification,
    verify_improvement,
)
from p3_data import load_truth, record_tuning

ROLLBACK_RELATIVE_TOLERANCE = 0.01  # maximum 1% KPI difference on replay


@pytest.fixture(scope="module")
def checkout() -> None:
    """Skip unless the RougherSim checkout matches the release and clean-source pin."""
    problem = checkout_problem(roughersim_dir(), load_pin())
    if problem:
        pytest.skip(problem)


@pytest.fixture(scope="module")
def recordings(tmp_path_factory: pytest.TempPathFactory, checkout: None) -> dict[str, Any]:
    """Generate the default and candidate runs once; preserve independent truth evidence."""
    directory = tmp_path_factory.mktemp("l5-p3")
    default_directory = directory / "default"
    default = record_tuning(default_directory, DEFAULT_TUNING)
    truth = load_truth(default_directory)
    baseline = choose_weak_baseline(directory, truth)
    assert load_truth(baseline["directory"]) == pytest.approx(truth, rel=1e-6)
    return {"default": default, "truth": truth, "baseline": baseline}


@pytest.mark.slow
def test_a_weak_tuning_is_flagged_at_least_as_severely_as_default(
    recordings: dict[str, Any], record_property: Any,
) -> None:
    """Real monitor classification selects the weak baseline and records why it was chosen."""
    baseline = recordings["baseline"]
    default_report = detect_weakness(recordings["default"], recordings["truth"])
    record_property("baseline_selection", repr(baseline["reason"]))
    record_property("baseline_tuning", repr(baseline["tuning"]))
    assert baseline["report"].classification in {"poor_performance", "oscillating", "saturated"}
    assert baseline["report"].findings
    assert SEVERITY[default_report.classification] <= SEVERITY[baseline["report"].classification]


@pytest.mark.slow
@pytest.mark.xfail(
    strict=True,
    raises=IdentificationResolutionError,
    reason="FINDING: fit_step tau grid starts at dt=60 s; FIC203 truth tau near 5 s "
           "cannot meet the required 25% tolerance. Finer recorder samples or fitter needed.",
)
def test_identification_proposal_apply_and_rollback_restore_baseline(
    recordings: dict[str, Any], tmp_path: Path,
) -> None:
    """Truth-validated identification must precede a useful proposal and reproducible rollback."""
    baseline = recordings["baseline"]
    fitted = identify_model(baseline["recording"])
    model = validate_identification(fitted, recordings["truth"])
    proposal = propose_tuning(model, baseline["tuning"])
    applied = record_tuning(tmp_path / "applied", read_proposed_values(proposal))
    verify_improvement((closed_window(baseline["recording"]), closed_window(applied),
                        closed_window(recordings["default"])), recordings["truth"])
    restored_values = restore_original_values(proposal)
    assert restored_values == baseline["tuning"]
    restored = record_tuning(tmp_path / "rollback", restored_values)
    assert calculate_iae(closed_window(restored)) == pytest.approx(
        calculate_iae(closed_window(baseline["recording"])),
        rel=ROLLBACK_RELATIVE_TOLERANCE,
    )
