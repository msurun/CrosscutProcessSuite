"""Unit tests of the exp43 protocol code on synthetic data; no RougherSim run, no held-out seeds."""
import dataclasses

import numpy as np
import pytest
from crosscut_fuzzy.model import system_from_dict
from crosscut_mpc.identification import IdentificationRejected, IdentifiedModel, PairQuality
from crosscut_runtime.variable_status import VariableStatus

from experiments.exp43_mpc_vs_pid.exp43 import (
    CONFIG,
    CV_IDS,
    DV_ID,
    MV_IDS,
    PidController,
    candidate_sets,
    catalogue,
    compute_kpis,
    conditioning,
    evaluate,
    fuzzy_controller,
    fuzzy_document,
    identify_from_trace,
    mpc_controller,
    pid_tunings,
    significant_pairs,
)

TARGETS = {c: s["target"] for c, s in CONFIG["cvs"].items()}
GOOD_GAINS = [[-0.036, 0.0, 0.4], [0.0, 5.0, 1.0]]


def status(name: str, value: float, sp: float | None = None) -> VariableStatus:
    """A good live status."""
    return VariableStatus(name, name, "good", (), value, "", sp)


def model(gains: list[list[float]], passed: bool = True) -> IdentifiedModel:
    """Synthetic 2 CV x 3 input identified model (FIC102, SIC201, HIT101)."""
    ok = PairQuality(0.9, 4, passed, ())
    shape = (2, 3)
    return IdentifiedModel(
        (*MV_IDS, DV_ID), tuple(CV_IDS), np.array(gains), np.full(shape, 100.0),
        np.full(shape, 30.0), 30.0, tuple(tuple(ok for _ in range(3)) for _ in range(2)), {})


def test_conditioning_flags_proportional_pair_as_ill_conditioned():
    """Proportional gains (the rejected L5 pairs) give a huge cond; a triangular set gives ~1."""
    sets = candidate_sets()
    rejected = next(v for k, v in sets.items() if k.startswith("rejected"))
    chosen = next(v for k, v in sets.items() if k.startswith("chosen"))
    assert rejected["cond"] > 500 and chosen["cond"] < 2
    assert conditioning([[1, 2], [2, 4]], [1, 1])["rga"] is None  # singular: no RGA


def test_frozen_config_is_consistent():
    """Seed sets are disjoint, events are inside the run, identification windows are ordered."""
    seeds = CONFIG["seeds"]
    assert not set(seeds["development"]) & set(seeds["held_out"])
    assert all(e["t_s"] < CONFIG["scenario"]["duration_s"] for e in CONFIG["scenario"]["events"])
    windows = CONFIG["identification"]["windows_s"].values()
    assert all(lo < hi <= CONFIG["identification"]["dv_block_end_s"] for lo, hi in windows)
    assert CONFIG["plant"]["cycle_s"] % CONFIG["plant"]["dt_s"] == 0


def trace_with(jt: np.ndarray, pdt: np.ndarray) -> dict[str, np.ndarray]:
    """A trace of 5 s steps with constant targets and constant setpoints."""
    n = len(jt)
    return {"t": 5.0 * np.arange(1, n + 1), "JT101": jt, "PDT204": pdt,
            "target_JT101": np.full(n, 8.5), "target_PDT204": np.full(n, 75.0),
            "sp_FIC102": np.full(n, 40.0), "sp_SIC201": np.full(n, 26.8)}


def test_kpis_zero_on_target_and_count_violation():
    """A trace on target has zero IAE and violation; an excursion above 8.8 MW is counted."""
    n = 2000
    on_target = compute_kpis(trace_with(np.full(n, 8.5), np.full(n, 75.0)))
    assert on_target["iae"] == 0 and on_target["violation"] == 0 and on_target["travel"] == 0
    jt = np.full(n, 8.5)
    jt[100:120] = 9.3  # 20 samples x 5 s, 0.5 MW above the 8.8 MW limit
    kpis = compute_kpis(trace_with(jt, np.full(n, 75.0)))
    assert kpis["violation_time_s"] == 100.0
    assert kpis["violation"] == pytest.approx(0.5 * 100.0 / 1.8)
    assert kpis["iae"] == pytest.approx(0.8 * 100.0 / 1.8)


def test_kpis_travel_sums_absolute_moves_over_range():
    """Travel is the sum of |dSP| over the MV range."""
    trace = trace_with(np.full(100, 8.5), np.full(100, 75.0))
    trace["sp_FIC102"] = np.r_[np.full(50, 40.0), np.full(50, 44.0)]
    assert compute_kpis(trace)["travel"] == pytest.approx(4.0 / 28.0)


def lists(iae: float, violation: float, travel: float, n: int = 8) -> dict[str, list[float]]:
    """KPI lists of one controller over n seeds."""
    return {"iae": [iae] * n, "violation": [violation] * n, "travel": [travel] * n}


def test_evaluate_declares_advantage_only_when_all_criteria_hold():
    """MPC clearly better on IAE, violations and travel passes; a worse IAE or travel does not."""
    good = {"mpc": lists(0.5, 0.0, 1.0), "pid": lists(1.0, 1.0, 1.0),
            "fuzzy": lists(1.0, 1.0, 1.0)}
    assert evaluate(good)["verdict"] == "advantage"
    result = evaluate(dict(good, mpc=lists(1.5, 0.0, 1.0)))
    assert result["verdict"] == "no demonstrated advantage" and not result["pid"]["P1_iae"]
    assert not evaluate(dict(good, mpc=lists(0.5, 0.0, 2.0)))["pid"]["P3_travel"]


def test_evaluate_treats_zero_zero_violation_as_tie():
    """Two controllers that never violate the limits do not fail P2."""
    kpis = {n: lists(1.0, 0.0, 1.0) for n in ("mpc", "pid", "fuzzy")}
    assert evaluate(kpis)["pid"]["P2_violation"]


def test_significant_pairs_needs_gate_and_snr():
    """A zero-gain pair is below the SNR rule; a failed gate disables every pair."""
    mask = significant_pairs(model(GOOD_GAINS))
    assert mask[0][0] and mask[1][1] and not mask[0][1]
    failed = significant_pairs(model(GOOD_GAINS, passed=False))
    assert not any(any(row) for row in failed)


def test_pid_tunings_keep_the_sign_of_each_loop():
    """FIC102 -> JT101 has a negative gain, SIC201 -> PDT204 a positive one."""
    tunings = pid_tunings(model(GOOD_GAINS))
    assert tunings["FIC102"][1] < 0 < tunings["SIC201"][1]
    assert all(ti > 0 for _, _, ti in tunings.values())


def run_pid(jt: float, pdt: float) -> list[float]:
    """Two PID cycles with a constant measurement; the FIC102 setpoint after each."""
    pid = PidController({"FIC102": ("JT101", -150.0, 480.0), "SIC201": ("PDT204", 0.07, 46.0)})
    pid.apply_limits(catalogue(TARGETS))
    pid.initialise([])
    sp, written = {"FIC102": 40.0, "SIC201": 26.8}, []
    for _ in range(2):
        result = pid.step([status("FIC102", 40.0, sp["FIC102"]),
                           status("SIC201", 26.8, sp["SIC201"]),
                           status("JT101", jt), status("PDT204", pdt)])
        sp.update({m.variable_id: m.value for m in result.moves})
        written.append(sp["FIC102"])
    return written


def test_pid_first_cycle_does_not_move_then_acts_in_the_right_direction():
    """No kick on the first cycle; power above target raises mill water within the move limit."""
    first, second = run_pid(8.7, 75.0)
    assert first == 40.0 and 40.0 < second <= 40.0 + CONFIG["mvs"]["FIC102"]["move_max"]
    assert run_pid(8.3, 75.0)[1] < 40.0


def test_fuzzy_document_is_valid_and_acts_in_the_right_direction():
    """The rule base parses; high power and high pressure move the right MVs the right way."""
    assert system_from_dict(fuzzy_document()).rules
    fuzzy = fuzzy_controller()
    statuses = [status("FIC102", 40.0, 40.0), status("SIC201", 26.8, 26.8),
                status("JT101", 9.0), status("PDT204", 75.0), status(DV_ID, 1.0),
                status("jt_err", 0.5), status("pdt_err", 3.0)]
    fuzzy.initialise(statuses)
    fuzzy.step(statuses)  # bumpless cycle
    moves = {m.variable_id: m.value for m in fuzzy.step(statuses).moves}
    assert moves["FIC102"] > 40.0 and moves["SIC201"] < 26.8


def lag(u: np.ndarray, gain: float, tau_s: float, delay: int) -> np.ndarray:
    """Discrete first-order response (30 s samples) with a delay in samples."""
    y, a = np.zeros(u.size), np.exp(-30.0 / tau_s)
    for i in range(1, u.size):
        y[i] = a * y[i - 1] + gain * (1 - a) * u[max(i - 1 - delay, 0)]
    return y


def synthetic_trace() -> dict[str, np.ndarray]:
    """A noise-free identification record: FIC102 -> JT101 and SIC201 -> PDT204 first order."""
    ident = CONFIG["identification"]
    t = np.arange(0.0, ident["dv_block_end_s"], 30.0)
    sps = {m: np.full(t.size, CONFIG["mvs"][m]["nominal"]) for m in MV_IDS}
    for m in MV_IDS:
        lo, hi = ident["windows_s"][m]
        quarter = (hi - lo - 300) / 4.0
        for j, level in enumerate((1.0, 0.0, -1.0, 0.0)):
            window = (t >= lo + 300 + j * quarter) & (t < hi)
            sps[m][window] = CONFIG["mvs"][m]["nominal"] + level * CONFIG["mvs"][m]["amplitude"]
    return {"t": t, **sps, DV_ID: np.ones(t.size),
            "JT101": 8.0 + lag(sps["FIC102"] - 40.0, -0.036, 680.0, 1),
            "PDT204": 75.0 + lag(sps["SIC201"] - 26.8, 5.0, 46.0, 1)}


def test_identify_from_trace_recovers_required_pairs_or_rejects():
    """Noise-free first-order pairs are identified; a flat record is rejected."""
    trace = synthetic_trace()
    identified = identify_from_trace(trace)
    assert identified.gains[0, 0] == pytest.approx(-0.036, rel=0.1)
    assert identified.gains[1, 1] == pytest.approx(5.0, rel=0.1)
    flat = {k: (np.full_like(v, 8.0) if k in CV_IDS else v) for k, v in trace.items()}
    with pytest.raises(IdentificationRejected):
        identify_from_trace(flat)


def test_mpc_controller_builds_and_starts_bumpless():
    """The runtime MPC binds the model and its first step holds the current setpoints."""
    ident = dataclasses.replace(model([[-0.036, 0.0, 0.4], [0.0, 5.0, 0.0]]),
                                enabled=((True, False, True), (False, True, False)))
    controller = mpc_controller(ident)
    controller.initialise([])
    live = [status("FIC102", 40.0, 40.0), status("SIC201", 26.8, 26.8), status("JT101", 8.4),
            status("PDT204", 75.0), status(DV_ID, 1.0)]
    first = controller.step(live)
    assert {m.variable_id: m.value for m in first.moves} == {"FIC102": 40.0, "SIC201": 26.8}
