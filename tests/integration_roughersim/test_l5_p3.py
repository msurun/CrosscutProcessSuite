"""Exercise acceptance row L5-P3 against the pinned RougherSim offline recorder.
Detection remains independent of the known 60 s identification resolution limitation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from golden import checkout_problem, load_pin, roughersim_dir
from p3_chain import (
    AUTO_MODE,
    DEFAULT_TUNING,
    RELATIVE_MODEL_TOLERANCE,
    SEVERITY,
    IdentificationResolutionError,
    calculate_iae,
    choose_weak_baseline,
    closed_window,
    detect_weakness,
    identify_model,
    propose_tuning,
    read_proposed_targets,
    read_proposed_values,
    restore_original_values,
    step_has_headroom,
    validate_identification,
    verify_improvement,
)
from p3_data import load_truth, record_tuning
from p3_lic301 import (
    LOOP as LIC301,
)
from p3_lic301 import (
    MIN_DELAY_S,
    ROBUSTNESS,
    WEAK_TUNING,
    apply_values,
    assert_improvement,
    assert_rollback_replay,
    lic301_rig,
)

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


@pytest.fixture(scope="module")
def lic301(tmp_path_factory: pytest.TempPathFactory, checkout: None) -> dict[str, Any]:
    """Record the weak LIC301 baseline once and derive its model and SIMC proposal."""
    directory = tmp_path_factory.mktemp("l5-p3-lic301")
    baseline = record_tuning(directory / "baseline", WEAK_TUNING, loop_tag=LIC301)
    truth = load_truth(directory / "baseline", loop_tag=LIC301)
    fitted = identify_model(baseline, loop_tag=LIC301)
    model = validate_identification(fitted, truth, minimum_delay_s=MIN_DELAY_S)
    proposal = propose_tuning(model, WEAK_TUNING, loop_tag=LIC301, robustness=ROBUSTNESS)
    return {"baseline": baseline, "truth": truth, "fitted": fitted, "model": model,
            "proposal": proposal}


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


@pytest.mark.slow
def test_lic301_weak_tuning_is_detected_with_step_headroom(
    lic301: dict[str, Any], recordings: dict[str, Any], record_property: Any,
) -> None:
    """The weak LIC301 baseline is flagged and still has 5 pp of valve headroom."""
    report = detect_weakness(lic301["baseline"], lic301["truth"], LIC301, AUTO_MODE)
    nominal = detect_weakness(recordings["default"], lic301["truth"], LIC301, AUTO_MODE)
    record_property("lic301_report", repr((report.classification, report.findings)))
    assert report.classification in {"poor_performance", "oscillating", "saturated"}
    assert report.findings
    assert step_has_headroom(lic301["baseline"], LIC301)
    assert SEVERITY[nominal.classification] < SEVERITY[report.classification]


@pytest.mark.slow
def test_lic301_identification_matches_ground_truth(
    lic301: dict[str, Any], record_property: Any,
) -> None:
    """Gain and tau stay inside 25% of truth; the delay floor is exactly one sample."""
    model = lic301["model"]
    record_property("lic301_model", repr(model))
    assert model.delay_s == MIN_DELAY_S
    assert abs(model.gain / abs(lic301["truth"]["gain"]) - 1.0) <= RELATIVE_MODEL_TOLERANCE
    assert abs(model.time_constant_s / lic301["truth"]["tau_s"] - 1.0) <= RELATIVE_MODEL_TOLERANCE


@pytest.mark.slow
@pytest.mark.xfail(
    strict=True,
    raises=ValueError,
    reason="FINDING: fit_step returns theta=0 for LIC301 at 60 s sampling; FopdtModel refuses "
           "zero dead time, so the raw identification cannot be tuned without a delay floor.",
)
def test_lic301_raw_zero_delay_identification_is_refused(lic301: dict[str, Any]) -> None:
    """The unfloored fit exposes the zero-dead-time defect instead of being silently clamped."""
    assert lic301["fitted"].theta_s.value == 0.0
    validate_identification(lic301["fitted"], lic301["truth"])


@pytest.mark.slow
def test_lic301_chain_applies_improves_and_rolls_back(
    lic301: dict[str, Any], recordings: dict[str, Any], tmp_path: Path,
    record_property: Any,
) -> None:
    """Apply the proposal through the gateway, verify the KPI, then roll back and replay."""
    proposal = lic301["proposal"]
    targets = read_proposed_targets(proposal)
    with lic301_rig(tmp_path / "gateway") as (harness, gateway):
        applied_values = apply_values(harness, gateway, targets, "lic301-apply")
        restored = apply_values(harness, gateway, WEAK_TUNING, "lic301-rollback",
                                rollback_of="lic301-apply")
    assert applied_values == targets
    assert restored == WEAK_TUNING
    applied = record_tuning(tmp_path / "applied", applied_values, loop_tag=LIC301)
    assert_improvement(lic301, recordings["default"], applied)
    replay = record_tuning(tmp_path / "rollback", restored, loop_tag=LIC301)
    assert_rollback_replay(replay, lic301["baseline"], ROLLBACK_RELATIVE_TOLERANCE)
    record_property("lic301_applied", repr(applied_values))
