# loops/tests/test_output_range.py
"""Behaviour of the OUT tag's engineering range: saturation uses the actuator span, not 0-100 %.

A 4-20 mA controller output pinned at 20 mA is fully open, but on the default 0-100 % scale it
looks like a healthy value. These tests check that the OUT tag's own eng_min/eng_max reach the
saturation checks, and that the range is read from the tag rows in every place loops are built.
"""

import numpy as np
from crosscut_loops.overview import LoopTags, analyze_dataset, discover_loops
from crosscut_loops.project_loops import loops_from_project

SAMPLE_COUNT = 4000
SAMPLE_INTERVAL_S = 1.0
RANDOM_SEED = 0
NOISE_SCALE = 0.1

MA_LOW = 4.0
MA_HIGH = 20.0
MA_MID_LOW = 4.5
MA_MID_HIGH = 19.5

PV_BASE = 12.0
SP_BASE = 12.0
MODE_AUTO = 1

SATURATED_CODE = "saturated"


def _time_vector() -> np.ndarray:
    """Return SAMPLE_COUNT timestamps, one per second, starting at zero."""
    return np.arange(SAMPLE_COUNT, dtype=float) * SAMPLE_INTERVAL_S


def _ma_loop(out_low: float | None, out_high: float | None) -> LoopTags:
    """Return a 4-20 mA loop whose OUT tag carries the given engineering range."""
    return LoopTags(
        name="level",
        pv="PV",
        sp="SP",
        out="OUT",
        mode="MODE",
        unit="mA",
        eng_min=MA_LOW,
        eng_max=MA_HIGH,
        out_low=out_low,
        out_high=out_high,
    )


def _pinned_columns(out_value: float) -> dict[str, np.ndarray]:
    """Columns of a loop whose PV drifts below SP while OUT stays at out_value."""
    return {
        "PV": np.linspace(PV_BASE - 2.0, PV_BASE - 1.0, SAMPLE_COUNT),
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": np.full(SAMPLE_COUNT, out_value),
        "MODE": np.full(SAMPLE_COUNT, MODE_AUTO),
    }


def _mid_range_columns() -> dict[str, np.ndarray]:
    """Columns of a healthy-looking loop whose OUT wanders randomly inside 4.5-19.5 mA."""
    rng = np.random.default_rng(RANDOM_SEED)
    return {
        "PV": PV_BASE + NOISE_SCALE * rng.standard_normal(SAMPLE_COUNT),
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": rng.uniform(MA_MID_LOW, MA_MID_HIGH, SAMPLE_COUNT),
        "MODE": np.full(SAMPLE_COUNT, MODE_AUTO),
    }


def _findings_with_code(result: dict, code: str) -> list[dict]:
    """The findings of one analysis row whose code matches."""
    return [finding for finding in result["findings"] if finding["code"] == code]


def test_a_full_scale_output_on_a_four_to_twenty_ma_loop_is_saturated():
    time_vector = _time_vector()
    columns = _pinned_columns(MA_HIGH)

    [result] = analyze_dataset(time_vector, columns, [_ma_loop(MA_LOW, MA_HIGH)])

    assert len(_findings_with_code(result, SATURATED_CODE)) == 1


def test_the_saturated_window_covers_the_whole_record_when_output_is_pinned():
    time_vector = _time_vector()
    columns = _pinned_columns(MA_HIGH)

    [result] = analyze_dataset(time_vector, columns, [_ma_loop(MA_LOW, MA_HIGH)])

    [finding] = _findings_with_code(result, SATURATED_CODE)
    assert finding["window_s"] == [time_vector[0], time_vector[-1]]


def test_a_pinned_output_is_not_saturated_when_the_range_is_the_default_scale():
    time_vector = _time_vector()
    columns = _pinned_columns(MA_HIGH)

    [result] = analyze_dataset(time_vector, columns, [_ma_loop(None, None)])

    assert _findings_with_code(result, SATURATED_CODE) == []


def test_an_output_between_the_range_ends_is_not_saturated_on_a_four_to_twenty_ma_loop():
    time_vector = _time_vector()
    columns = _mid_range_columns()

    results = analyze_dataset(time_vector, columns, [_ma_loop(MA_LOW, MA_HIGH)])

    assert _findings_with_code(results[0], SATURATED_CODE) == []


def _tag_row(tag_id: str, role: str, **extra: object) -> dict:
    """One raw tag row as the tag database delivers it, with optional extra attributes."""
    return {"id": tag_id, "role": role, "unit": "mA", **extra}


def test_discovery_takes_the_out_range_from_the_out_tag_row():
    rows = [
        _tag_row("PV", "PV", eng_min=0.0, eng_max=100.0),
        _tag_row("PV_sp", "SP"),
        _tag_row("PV_out", "OUT", eng_min=MA_LOW, eng_max=MA_HIGH),
        _tag_row("PV_mode", "MODE"),
    ]

    [loop] = discover_loops(rows)

    assert (loop.out_low, loop.out_high) == (MA_LOW, MA_HIGH)


def test_discovery_leaves_the_out_range_empty_when_the_out_tag_has_none():
    rows = [
        _tag_row("PV", "PV", eng_min=0.0, eng_max=100.0),
        _tag_row("PV_sp", "SP"),
        _tag_row("PV_out", "OUT"),
        _tag_row("PV_mode", "MODE"),
    ]

    [loop] = discover_loops(rows)

    assert (loop.out_low, loop.out_high) == (None, None)


def _project_tags(out_extra: dict[str, float]) -> list[dict]:
    """Tag rows of one project loop whose OUT tag carries the given range attributes."""
    return [
        {"id": "PV1", "unit": "mA", "eng_min": 0.0, "eng_max": 100.0},
        {"id": "SP1", "unit": "", "eng_min": None, "eng_max": None},
        {"id": "OUT1", "unit": "mA", "eng_min": None, "eng_max": None, **out_extra},
        {"id": "MODE1", "unit": "", "eng_min": None, "eng_max": None},
    ]


PROJECT_LOOP = {"id": "L1", "pv": "PV1", "sp": "SP1", "out": "OUT1", "mode": "MODE1"}


def test_a_project_loop_takes_the_out_range_from_the_out_tag_row():
    project = {"loops": [PROJECT_LOOP]}
    tags = _project_tags({"eng_min": MA_LOW, "eng_max": MA_HIGH})

    [loop] = loops_from_project(project, tags)

    assert (loop.out_low, loop.out_high) == (MA_LOW, MA_HIGH)


def test_a_project_loop_leaves_the_out_range_empty_when_the_out_tag_has_none():
    project = {"loops": [PROJECT_LOOP]}
    tags = _project_tags({})

    [loop] = loops_from_project(project, tags)

    assert (loop.out_low, loop.out_high) == (None, None)
