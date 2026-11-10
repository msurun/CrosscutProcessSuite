"""Small offline acceptance steps for L5-P3, with explicit units and evidence.
Simulation I/O lives in p3_data; these helpers preserve the production API semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from crosscut_loops.monitor import DELAY, OUT_RANGE, LoopReport, LoopSettings, analyze_loop
from crosscut_loops.step_fit import StepFit, fit_step
from crosscut_loops.tuning_proposal import (
    ProposalRequest,
    Stamp,
    WindowSpec,
    build_proposal,
    build_rollback,
)
from crosscut_loops.tuning_report import report_from_model
from crosscut_loops.tuning_review import WindowData, compare_windows, window_bounds
from crosscut_loops.tuning_rules import FopdtModel
from p3_data import SAMPLE_INTERVAL_S, record_tuning

MAN_START_S = 12600.0  # scenario seconds after warm-up, before the OUT step
OUT_STEP_S = 14400.0
CAS_RETURN_S = 21600.0
REVIEW_START_S = 25200.0  # one hour after CAS returns; omit the MAN experiment and settling
MAN_MODE = 0
AUTO_MODE = 1
CAS_MODE = 2
RELATIVE_MODEL_TOLERANCE = 0.25  # maximum allowed gain and tau relative error
MIN_STEP_PP = 4.0  # of the 5 pp step; less means a saturated valve (FINDING: needs headroom)
KPI_IMPROVEMENT = 0.20  # required reduction in closed-loop IAE
DEFAULT_ROBUSTNESS = 0.5  # SIMC slider used by the original FIC203 proposal
DEFAULT_TUNING = {"gain": 0.3, "ti": 10.0}  # OUT pp/PV engineering unit, seconds
CANDIDATES = ({"gain": 10.0, "ti": 1.0}, {"gain": 0.001, "ti": 10000.0},
              {"gain": 0.01, "ti": 1000.0})
SEVERITY = {"ok": 0, "poor_performance": 1, "oscillating": 2, "saturated": 3, "manual": 4}


class IdentificationResolutionError(AssertionError):
    """The measured tau violates the required truth tolerance at recorder resolution."""


def closed_window(
    recording: dict[str, np.ndarray], loop_tag: str = "FIC203", mode: int = CAS_MODE
) -> WindowData:
    """Select identical contiguous closed-loop windows, using SP or RSP by mode."""
    mask = recording["time"] >= REVIEW_START_S
    assert np.all(recording[f"{loop_tag}_mode"][mask] == mode), "Expected closed review window"
    assert np.all(recording["quality"][mask] == 0), "Review contains bad quality"
    # A cascade secondary follows RSP; an AUTO loop follows its local SP.
    sp_tag = f"{loop_tag}_rsp" if mode == CAS_MODE else f"{loop_tag}_sp"
    # The review API represents all closed-loop modes by 1.
    return WindowData(recording["time"][mask], recording[loop_tag][mask],
                      recording[sp_tag][mask], recording[f"{loop_tag}_out"][mask],
                      np.ones(np.count_nonzero(mask), dtype=int))


def detect_weakness(
    recording: dict[str, np.ndarray], truth: dict[str, float],
    loop_tag: str = "FIC203", mode: int = CAS_MODE,
) -> LoopReport:
    """Analyze actual closed-loop data without invented oscillation amplitude thresholds."""
    window = closed_window(recording, loop_tag, mode)
    settings = LoopSettings(truth["theta_s"], SAMPLE_INTERVAL_S, 0.0,
                            scan_period_s=SAMPLE_INTERVAL_S, known=frozenset({DELAY, OUT_RANGE}))
    return analyze_loop(window.t_s, window.pv, window.sp, window.out, window.mode,
                        settings=settings)


def step_has_headroom(recording: dict[str, np.ndarray], loop_tag: str = "FIC203") -> bool:
    """True when the MAN OUT step is visible; a saturated valve (OUT at 100) cannot be stepped."""
    mask = (recording["time"] >= MAN_START_S) & (recording["time"] < CAS_RETURN_S)
    return bool(np.ptp(recording[f"{loop_tag}_out"][mask]) >= MIN_STEP_PP)


def choose_weak_baseline(directory: Path, truth: dict[str, float]) -> dict[str, Any]:
    """Try candidate tunings; retain a genuinely flagged recording and its detection reason."""
    observations = []
    for index, tuning in enumerate(CANDIDATES):
        destination = directory / f"candidate-{index}"
        recording = record_tuning(destination, tuning)
        report = detect_weakness(recording, truth)
        observations.append((tuning, report.classification, report.findings))
        weak = report.classification in {"poor_performance", "oscillating", "saturated"}
        if weak and step_has_headroom(recording):
            return {"tuning": tuning, "recording": recording, "report": report,
                    "reason": observations, "directory": destination}
    raise AssertionError(f"No candidate was genuinely weak: {observations}")


def identify_model(
    recording: dict[str, np.ndarray], loop_tag: str = "FIC203"
) -> StepFit:
    """Fit the manual OUT step; gain is PV units/OUT pp and both dynamics are seconds."""
    mask = (recording["time"] >= MAN_START_S) & (recording["time"] < CAS_RETURN_S)
    assert np.all(recording[f"{loop_tag}_mode"][mask] == MAN_MODE)
    assert np.all(recording["quality"][mask] == 0)
    times = recording["time"][mask]
    pre_samples = int(np.searchsorted(times, OUT_STEP_S))
    fitted = fit_step(times, recording[loop_tag][mask], recording[f"{loop_tag}_out"][mask],
                      pre_samples, "fopdt")
    assert fitted.gain is not None and fitted.tau_s is not None
    # Keep the raw fit intact; the caller decides whether a delay floor is justified.
    return fitted


def validate_identification(
    fitted: StepFit, truth: dict[str, float], minimum_delay_s: float = 0.0
) -> FopdtModel:
    """Require 25% gain/tau accuracy and at most one sample of absolute delay error.

    A positive ``minimum_delay_s`` is a documented test-side floor: the pinned fitter returns
    theta=0 for LIC301 at 60 s sampling, and FopdtModel/SIMC refuse zero dead time.
    """
    assert fitted.gain is not None and fitted.tau_s is not None
    tau_error = abs(fitted.tau_s.value / truth["tau_s"] - 1.0)
    # FINDING: step_fit's coarse AND refined tau grids start at dt=60 s, excluding truth
    # near 5 s. Only this measured tau failure is expected; unrelated failures stay loud.
    if (tau_error > RELATIVE_MODEL_TOLERANCE and fitted.tau_s.value >= SAMPLE_INTERVAL_S
            and truth["tau_s"] * (1.0 + RELATIVE_MODEL_TOLERANCE) < SAMPLE_INTERVAL_S):
        raise IdentificationResolutionError(
            f"tau={fitted.tau_s.value}s vs truth={truth['tau_s']}s exceeds 25%; "
            "fit_step cannot search below its 60 s sample interval")
    assert tau_error <= RELATIVE_MODEL_TOLERANCE
    assert abs(fitted.gain.value / truth["gain"] - 1.0) <= RELATIVE_MODEL_TOLERANCE
    assert abs(fitted.theta_s.value - truth["theta_s"]) <= SAMPLE_INTERVAL_S
    delay_s = max(fitted.theta_s.value, minimum_delay_s)
    # A reverse-acting loop keeps a positive vendor Gain; the DCS inverts the action.
    return FopdtModel(abs(fitted.gain.value), fitted.tau_s.value, delay_s)


def make_stamp() -> Stamp:
    """Create audit metadata for an offline proposal, without contacting a gateway."""
    return Stamp(str(uuid4()), "L5-P3-offline", datetime.now(UTC))


def propose_tuning(
    model: FopdtModel, original: dict[str, float], loop_tag: str = "FIC203",
    robustness: float = DEFAULT_ROBUSTNESS,
) -> dict[str, Any]:
    """Build SIMC PI items with raw engineering gain and integral time in seconds."""
    stamp = make_stamp()
    window = WindowSpec(stamp.now - timedelta(hours=1), stamp.now, "L5-P3")
    # Siemens gain_seconds is a unit adapter here: gain=OUT pp/PV unit, ti=seconds.
    # RougherSim kc uses these same units; no ABB normalized-gain conversion is needed.
    targets = {"gain": f"{loop_tag}.GAIN", "ti": f"{loop_tag}.TI"}
    request = ProposalRequest(loop_tag, "siemens_pid_compact", "simc", targets, window)
    return build_proposal(report_from_model(loop_tag, model, robustness), request,
                          original, stamp)


def read_proposed_values(proposal: dict[str, Any]) -> dict[str, float]:
    """Map raw proposal items to recorder tuning keys without unit conversion."""
    return {item["param"]: item["to"] for item in proposal["items"]}


def read_proposed_targets(proposal: dict[str, Any]) -> dict[str, float]:
    """Map proposal items to policy target tags, retaining the proposal's to values."""
    return {item["target"]: float(item["to"]) for item in proposal["items"]}


def restore_original_values(proposal: dict[str, Any]) -> dict[str, float]:
    """Construct an applied audit from offline simulator inputs, then build rollback."""
    audit = {"from_read": {item["target"]: item["from"] for item in proposal["items"]},
             "to_read": {item["target"]: item["to"] for item in proposal["items"]}}
    applied = {**proposal, "status": "applied", "applied": audit}
    return read_proposed_values(build_rollback(applied, make_stamp()))


def calculate_iae(window: WindowData) -> float:
    """Integrate absolute PV-RSP error using forward intervals, in PV-unit seconds."""
    assert np.all(np.diff(window.t_s) == SAMPLE_INTERVAL_S)
    return float(np.sum(np.abs(window.pv[:-1] - window.sp[:-1]) * np.diff(window.t_s)))


def verify_improvement(windows: tuple[WindowData, ...], truth: dict[str, float]) -> None:
    """Require 20% IAE reduction, production review improvement and the default KPI bound."""
    before, after, default = windows
    assert np.array_equal(before.t_s, after.t_s)
    assert np.array_equal(before.t_s, default.t_s)
    assert calculate_iae(after) <= (1.0 - KPI_IMPROVEMENT) * calculate_iae(before)
    assert calculate_iae(after) <= 2.0 * calculate_iae(default)
    assert compare_windows(before, after)["verdict"] == "improved"
    # Dynamics determine the minimum review length; both runs use the same scenario times.
    bounds, _ = window_bounds(CAS_RETURN_S, truth["theta_s"], truth["tau_s"])
    assert after.t_s[-1] - after.t_s[0] >= bounds[1] - bounds[0]


