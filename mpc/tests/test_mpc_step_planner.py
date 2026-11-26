"""Tests of the multi-MV step-test planner: bounds, GBN determinism and refusal reasons."""

from dataclasses import replace

import pytest
from crosscut_mpc.step_planner import MAX_STEPS, MvSpec, PlanSettings, build_plan

SEQ = PlanSettings("sequential", duration_s=600.0, gap_s=60.0)
GBN = PlanSettings("gbn", duration_s=1200.0, sample_s=60.0, switch_probability=0.4, seed=7)


def mv(name: str = "feed", **changes: object) -> MvSpec:
    """An MV at 50 with limits 10-90, max_step 5 and a 30 s write interval."""
    base = MvSpec(name, f"{name}.SP", 50.0, 2.0, (10.0, 90.0), 5.0, 30.0)
    return replace(base, **changes)


def codes(plan) -> set[str]:
    """Refusal codes of a plan."""
    return {r.code for r in plan.refusals}


def test_sequential_goes_out_and_back_per_mv_in_order() -> None:
    plan = build_plan([mv("a"), mv("b", amplitude=-3.0)], SEQ)
    assert plan.ok
    got = [(s.mv, s.at_s, s.value) for s in plan.steps]
    assert got == [("a", 0.0, 52.0), ("a", 600.0, 50.0), ("b", 660.0, 47.0), ("b", 1260.0, 50.0)]
    assert [s.index for s in plan.steps] == [0, 1, 2, 3]


def test_every_step_respects_limits_step_and_interval() -> None:
    specs = [mv("a"), mv("b", amplitude=2.5, limits=(45.0, 60.0))]
    for plan_settings in (SEQ, GBN):
        plan = build_plan(specs, plan_settings)
        assert plan.ok
        last: dict[str, tuple[float, float]] = {s.tag: (s.baseline, -1e9) for s in specs}
        for step in plan.steps:
            spec = next(s for s in specs if s.name == step.mv)
            assert spec.limits[0] <= step.value <= spec.limits[1]
            assert abs(step.value - last[step.tag][0]) <= spec.max_step
            assert step.at_s - last[step.tag][1] >= spec.min_interval_s
            last[step.tag] = (step.value, step.at_s)
        assert plan.steps[-1].value in (50.0,)  # ends on the baseline


def test_gbn_is_deterministic_for_a_seed_and_differs_between_seeds() -> None:
    specs = [mv("a"), mv("b")]
    first, again = build_plan(specs, GBN), build_plan(specs, GBN)
    other = build_plan(specs, replace(GBN, seed=8))
    assert first == again
    assert [s.value for s in first.steps] != [s.value for s in other.steps]


def test_gbn_uses_both_levels_and_flips_with_delta_twice_amplitude() -> None:
    plan = build_plan([mv("a", amplitude=2.0)], replace(GBN, switch_probability=1.0))
    values = {s.value for s in plan.steps}
    assert {48.0, 52.0} <= values
    assert any(abs(s.delta) == 4.0 for s in plan.steps)


@pytest.mark.parametrize(("spec", "code"), [
    (mv(amplitude=0.0), "amplitude_zero"),
    (mv(amplitude=6.0), "amplitude_exceeds_max_step"),
    (mv(baseline=95.0), "baseline_outside_limits"),
    (mv(limits=(10.0, 51.0)), "value_above_limit"),
    (mv(amplitude=-2.0, limits=(49.0, 90.0)), "value_below_limit"),
    (mv(amplitude=float("nan")), "bad_value"),
])
def test_mv_refusals_have_specific_codes(spec: MvSpec, code: str) -> None:
    plan = build_plan([spec], SEQ)
    assert not plan.ok and plan.steps == () and code in codes(plan)


def test_interval_shorter_than_policy_minimum_is_refused() -> None:
    plan = build_plan([mv(min_interval_s=900.0)], SEQ)
    assert codes(plan) == {"interval_below_min"} and plan.steps == ()


def test_gbn_flip_larger_than_max_step_is_refused_not_clamped() -> None:
    plan = build_plan([mv(amplitude=4.0)], replace(GBN, switch_probability=1.0))
    assert "step_exceeds_max_step" in codes(plan) and plan.steps == ()


@pytest.mark.parametrize(("settings", "code"), [
    (replace(SEQ, duration_s=0.0), "bad_duration"),
    (replace(SEQ, gap_s=-1.0), "bad_gap"),
    (replace(GBN, switch_probability=0.0), "bad_switch_probability"),
    (replace(GBN, sample_s=0.0), "bad_sample_s"),
    (replace(GBN, sample_s=5000.0), "bad_sample_s"),
    (replace(SEQ, plan_type="ramp"), "unknown_plan_type"),  # type: ignore[arg-type]
])
def test_settings_refusals(settings: PlanSettings, code: str) -> None:
    assert code in codes(build_plan([mv()], settings))


def test_no_mv_and_too_many_steps_are_refused() -> None:
    assert codes(build_plan([], SEQ)) == {"no_mv"}
    many = replace(GBN, duration_s=60.0 * (MAX_STEPS + 50), switch_probability=1.0)
    assert codes(build_plan([mv(amplitude=2.0, max_step=5.0)], many)) == {"too_many_steps"}


def test_gbn_return_to_baseline_is_not_after_the_duration() -> None:
    for duration in (1200.0, 1230.0, 1259.0):
        plan = build_plan([mv("a")], replace(GBN, duration_s=duration))
        assert plan.ok and plan.steps[-1].at_s <= duration and plan.steps[-1].value == 50.0
