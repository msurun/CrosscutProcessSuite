# loops/tests/test_project_loops.py
"""Behaviour of loops_from_project: building LoopTags from a project and its tags."""

from crosscut_loops.overview import default_settings
from crosscut_loops.project_loops import loops_from_project


def tag(tag_id, unit="", eng_min=None, eng_max=None):
    """Build one tag dict as it appears in the project tag list."""
    return {"id": tag_id, "unit": unit, "eng_min": eng_min, "eng_max": eng_max}


def project_with(*entries):
    """Build a project mapping holding the given loop entries."""
    return {"loops": list(entries)}


def full_tags():
    """The four tags a complete loop references: pv, sp, out and mode."""
    return [
        tag("PV1", unit="degC", eng_min=0.0, eng_max=100.0),
        tag("SP1"),
        tag("OUT1"),
        tag("MODE1"),
    ]


def loop_entry(**overrides):
    """A minimal valid loop entry pointing at the four tags of full_tags()."""
    entry = {"id": "L1", "pv": "PV1", "sp": "SP1", "out": "OUT1", "mode": "MODE1"}
    entry.update(overrides)
    return entry


def test_name_falls_back_to_the_loop_id():
    loops = loops_from_project(project_with(loop_entry()), full_tags())
    assert loops[0].name == "L1"


def test_display_name_is_used_when_given():
    loops = loops_from_project(project_with(loop_entry(name="Reactor temperature")), full_tags())
    assert loops[0].name == "Reactor temperature"


def test_the_pv_tag_supplies_unit_and_range():
    loops = loops_from_project(project_with(loop_entry()), full_tags())
    assert (loops[0].unit, loops[0].eng_min, loops[0].eng_max) == ("degC", 0.0, 100.0)


def test_a_pv_tag_without_unit_or_range_gives_empty_defaults():
    tags = [tag("PV1"), tag("SP1"), tag("OUT1"), tag("MODE1")]
    loops = loops_from_project(project_with(loop_entry()), tags)
    assert (loops[0].unit, loops[0].eng_min, loops[0].eng_max) == ("", None, None)


def test_the_four_tag_ids_are_copied_to_the_loop():
    loops = loops_from_project(project_with(loop_entry()), full_tags())
    loop = loops[0]
    assert (loop.pv, loop.sp, loop.out, loop.mode) == ("PV1", "SP1", "OUT1", "MODE1")


def test_optional_settings_are_copied_from_the_entry():
    entry = loop_entry(delay_s=5.0, ultimate_period_s=60.0, amplitude_limit=0.25)
    loops = loops_from_project(project_with(entry), full_tags())
    loop = loops[0]
    assert (loop.delay_s, loop.ultimate_period_s, loop.amplitude_limit) == (5.0, 60.0, 0.25)


def test_missing_settings_stay_none():
    loops = loops_from_project(project_with(loop_entry()), full_tags())
    loop = loops[0]
    assert (loop.delay_s, loop.ultimate_period_s, loop.amplitude_limit) == (None, None, None)


def test_a_loop_referencing_an_unknown_tag_is_skipped():
    valid = loop_entry(id="VALID")
    broken = loop_entry(id="BROKEN", sp="GHOST")
    loops = loops_from_project(project_with(broken, valid), full_tags())
    assert [loop.name for loop in loops] == ["VALID"]


def test_a_loop_without_a_mode_tag_is_skipped():
    without_mode = loop_entry(id="NO_MODE")
    del without_mode["mode"]
    loops = loops_from_project(project_with(without_mode, loop_entry(id="OK")), full_tags())
    assert [loop.name for loop in loops] == ["OK"]


def test_an_empty_project_yields_no_loops():
    assert loops_from_project(project_with(), full_tags()) == []


def test_the_project_order_is_preserved():
    entries = [loop_entry(id="A"), loop_entry(id="B"), loop_entry(id="C")]
    loops = loops_from_project(project_with(*entries), full_tags())
    assert [loop.name for loop in loops] == ["A", "B", "C"]


def test_default_settings_take_the_values_set_on_the_loop():
    entry = loop_entry(delay_s=5.0, ultimate_period_s=60.0, amplitude_limit=0.25)
    tuned = loops_from_project(project_with(entry), full_tags())[0]
    settings = default_settings(tuned)
    assert (settings.delay_s, settings.ultimate_period_s) == (5.0, 60.0)
    assert settings.amplitude_limit == 0.25


def test_default_settings_fall_back_for_a_loop_without_settings():
    plain = loops_from_project(project_with(loop_entry()), full_tags())[0]
    settings = default_settings(plain)
    assert (settings.delay_s, settings.ultimate_period_s) == (30.0, 600.0)


def ranged_tags():
    """Tags whose PV and OUT rows both carry a range."""
    return [
        tag("PV1", unit="degC", eng_min=0.0, eng_max=100.0),
        tag("SP1"),
        tag("OUT1", eng_min=0.0, eng_max=100.0),
        tag("MODE1"),
    ]


def test_entry_pv_range_wins_over_the_tag_row():
    entry = loop_entry(pv_eng_min=-10.0, pv_eng_max=50.0)
    loop = loops_from_project(project_with(entry), ranged_tags())[0]
    assert (loop.eng_min, loop.eng_max) == (-10.0, 50.0)


def test_entry_out_range_wins_over_the_tag_row():
    entry = loop_entry(out_eng_min=4.0, out_eng_max=20.0)
    loop = loops_from_project(project_with(entry), ranged_tags())[0]
    assert (loop.out_low, loop.out_high) == (4.0, 20.0)


def test_a_single_override_keeps_the_other_bound_from_the_tag_row():
    entry = loop_entry(pv_eng_max=80.0, out_eng_min=0.5)
    loop = loops_from_project(project_with(entry), ranged_tags())[0]
    assert (loop.eng_min, loop.eng_max) == (0.0, 80.0)
    assert (loop.out_low, loop.out_high) == (0.5, 100.0)


def test_a_zero_override_is_a_real_value_not_absent():
    tags = [tag("PV1", eng_min=5.0, eng_max=9.0), tag("SP1"), tag("OUT1"), tag("MODE1")]
    loop = loops_from_project(project_with(loop_entry(pv_eng_min=0.0)), tags)[0]
    assert loop.eng_min == 0.0


def test_override_supplies_a_range_the_tag_row_lacks():
    entry = loop_entry(out_eng_min=0.0, out_eng_max=10.0)
    loop = loops_from_project(project_with(entry), full_tags())[0]
    assert (loop.out_low, loop.out_high) == (0.0, 10.0)


def test_vendor_is_copied_from_the_entry_and_defaults_to_none():
    with_vendor = loops_from_project(project_with(loop_entry(vendor="abb_pidcc")), full_tags())
    without = loops_from_project(project_with(loop_entry()), full_tags())
    assert (with_vendor[0].vendor, without[0].vendor) == ("abb_pidcc", None)
