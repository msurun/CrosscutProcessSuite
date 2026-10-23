"""Behaviour tests for plant_import_loops (loop detection) and plant_import_time (UTC conversion).

All data here is synthetic and built inside each test, so the tests document the loop roles
and the DST rules the modules promise without depending on any real plant file.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from crosscut_loops.plant_import_loops import (
    DetectedLoop,
    DictRow,
    detect_loops,
    read_dictionary,
)
from crosscut_loops.plant_import_time import TimeZoneSpec, to_utc_ns

SANTIAGO = ZoneInfo("America/Santiago")

# Tags of one complete level loop (LIC-20103), used by several tests.
LIC_TAGS = [
    "demo.1000-lic-20103.mv",
    "demo.1000-lic-20103.out",
    "demo.1000-lic-20103.sp",
    "demo.1000-lic-20103.feedback",
    "demo.1000-lic-20103.auto#state",
    "demo.1000-lv-20103-a-ao",
    "demo.1000-lv-20103-a-ai",
    "demo.1000-li-20103",
]


def _utc_ns_of(moment: datetime) -> int:
    """Nanoseconds since the Unix epoch for an aware UTC datetime."""
    return int(moment.timestamp()) * 1_000_000_000


def _naive_series(*wall_times: datetime) -> np.ndarray:
    """Build a datetime64[ns] array from naive datetimes."""
    return np.array([np.datetime64(wall_time) for wall_time in wall_times], dtype="datetime64[ns]")


def _notes_by_code(notes: list) -> dict[str, dict]:
    """Index notes by their code so a test can read the parameters directly."""
    return {note.code: note.params for note in notes}


def _lic_dictionary() -> list[DictRow]:
    """Dictionary rows describing the complete LIC-20103 loop."""
    return [
        DictRow("demo.1000-lic-20103.out", "level controller out", "%", "OUT (controller output)",
                "20103", "3500"),
        DictRow("demo.1000-lic-20103.sp", "level controller sp", "%", "SP", "20103", "3500"),
        DictRow("demo.1000-li-20103", "level sensor", "%", "PV (measured)", "20103", "3500"),
        DictRow("demo.1000-lic-20103.feedback", "valve position", "%",
                "feedback (actuator position)", "20103", "3500"),
        DictRow("demo.1000-lic-20103.auto#state", "controller mode", "", "mode flag", "20103",
                "3500"),
        DictRow("demo.1000-lv-20103-a-ao", "valve reference", "%", "valve reference (AO)",
                "20103", "3500"),
        DictRow("demo.1000-lv-20103-a-ai", "valve position", "%", "valve position (AI)",
                "20103", "3500"),
    ]


# --- read_dictionary -------------------------------------------------------


def test_read_dictionary_strips_bom_and_keeps_quoted_commas():
    text = '\ufefftag,description,unit,signal,loop,cell\n' \
           't1,"level, primary",%,PV (measured),20103,3500\n'

    rows = read_dictionary(text)

    assert rows[0].description == "level, primary"
    assert rows[0].tag == "t1"


def test_read_dictionary_fills_missing_columns_with_empty_strings():
    text = "tag,signal\nt1,SP\n"

    rows = read_dictionary(text)

    assert rows[0].unit == ""
    assert rows[0].loop == ""
    assert rows[0].cell == ""


def test_a_dictionary_without_a_tag_column_raises_value_error():
    text = "name,signal\nt1,SP\n"

    with pytest.raises(ValueError):
        read_dictionary(text)


# --- detect_loops with a dictionary ----------------------------------------


def _loops_from_dictionary(columns: list[str]) -> dict[str, DetectedLoop]:
    """Detect loops from the LIC dictionary plus a FIC loop and the given columns."""
    dictionary = _lic_dictionary() + [
        DictRow("demo.1000-fic-20120.out", "flow controller out", "%",
                "OUT (controller output)", "20120", "3500"),
        DictRow("demo.1000-fic-20120.sp", "flow controller sp", "m3/h", "SP", "20120", "3500"),
        DictRow("demo.1000-fi-20120", "flow sensor", "m3/h", "PV (measured)", "20120", "3500"),
        DictRow("demo.1000-fic-20120.auto#state", "flow mode", "", "mode flag", "20120", "3500"),
    ]
    return {loop.id: loop for loop in detect_loops(columns, dictionary)}


def test_a_complete_level_loop_collects_all_signals():
    loops = _loops_from_dictionary(LIC_TAGS)

    level_loop = loops["LIC-20103"]
    assert level_loop.pv == "demo.1000-li-20103"
    assert level_loop.sp == "demo.1000-lic-20103.sp"
    assert level_loop.mode == "demo.1000-lic-20103.auto#state"
    assert level_loop.complete is True
    assert level_loop.missing == ()


def test_the_controller_output_is_preferred_over_the_mv_tag():
    loops = _loops_from_dictionary(LIC_TAGS)

    assert loops["LIC-20103"].out == "demo.1000-lic-20103.out"


def test_valves_are_collected_and_sorted_on_the_level_loop():
    loops = _loops_from_dictionary(LIC_TAGS)

    assert loops["LIC-20103"].valves == (
        "demo.1000-lv-20103-a-ai",
        "demo.1000-lv-20103-a-ao",
    )


def test_the_level_sensor_is_not_a_loop_of_its_own():
    loops = _loops_from_dictionary(LIC_TAGS)

    assert "LOOP-20103" not in loops


def test_a_level_controller_is_integrating():
    loops = _loops_from_dictionary(LIC_TAGS)

    assert loops["LIC-20103"].process_kind == "integrating"


def test_a_flow_controller_is_self_regulating():
    columns = ["demo.1000-fic-20120.out", "demo.1000-fic-20120.sp", "demo.1000-fi-20120",
               "demo.1000-fic-20120.auto#state"]

    loops = _loops_from_dictionary(columns)

    assert loops["FIC-20120"].process_kind == "self_regulating"


def test_a_loop_without_its_mode_flag_is_incomplete_and_names_the_missing_role():
    columns = ["demo.1000-fic-20120.out", "demo.1000-fic-20120.sp", "demo.1000-fi-20120"]

    loops = _loops_from_dictionary(columns)

    assert loops["FIC-20120"].complete is False
    assert loops["FIC-20120"].missing == ("mode",)


def test_a_loop_whose_columns_are_absent_is_not_detected():
    columns = ["demo.1000-fic-20120.out"]

    loops = _loops_from_dictionary(columns)

    assert "LIC-20103" not in loops


# --- detect_loops without a dictionary -------------------------------------


def test_name_based_detection_yields_the_same_loop_ids():
    columns = LIC_TAGS + ["demo.1000-fic-20120.out", "demo.1000-fic-20120.sp",
                          "demo.1000-fi-20120"]

    loops = detect_loops(columns, None)

    assert [loop.id for loop in loops] == ["FIC-20120", "LIC-20103"]


def test_loops_are_sorted_by_id():
    columns = ["demo.1000-fic-20120.out", "demo.1000-lic-20103.out"]

    loops = detect_loops(columns, None)

    assert [loop.id for loop in loops] == ["FIC-20120", "LIC-20103"]


# --- to_utc_ns: utc and fixed offset ---------------------------------------


def test_utc_times_pass_through_unchanged():
    naive = _naive_series(datetime(2026, 10, 9, 12, 0))

    utc_ns, notes = to_utc_ns(naive, TimeZoneSpec(kind="utc"))

    assert utc_ns[0] == _utc_ns_of(datetime(2026, 10, 9, 12, 0, tzinfo=UTC))
    assert notes[0].code == "tz_utc"


def test_fixed_offset_minus_three_shifts_local_noon_to_fifteen_utc():
    naive = _naive_series(datetime(2026, 10, 9, 12, 0))

    utc_ns, notes = to_utc_ns(naive, TimeZoneSpec(kind="offset", value=-3))

    assert utc_ns[0] == _utc_ns_of(datetime(2026, 10, 9, 15, 0, tzinfo=UTC))
    assert notes[0].code == "tz_offset"


def test_an_offset_beyond_fourteen_hours_raises_value_error():
    naive = _naive_series(datetime(2026, 10, 9, 12, 0))

    with pytest.raises(ValueError):
        to_utc_ns(naive, TimeZoneSpec(kind="offset", value=20))


# --- to_utc_ns: IANA zone ---------------------------------------------------


def test_santiago_winter_noon_is_sixteen_utc():
    naive = _naive_series(datetime(2026, 6, 6, 12, 0))

    utc_ns, _ = to_utc_ns(naive, TimeZoneSpec(kind="iana", value="America/Santiago"))

    assert utc_ns[0] == _utc_ns_of(datetime(2026, 6, 6, 16, 0, tzinfo=UTC))


def test_santiago_early_october_noon_is_fifteen_utc():
    naive = _naive_series(datetime(2026, 10, 9, 12, 0))

    utc_ns, _ = to_utc_ns(naive, TimeZoneSpec(kind="iana", value="America/Santiago"))

    assert utc_ns[0] == _utc_ns_of(datetime(2026, 10, 9, 15, 0, tzinfo=UTC))


def test_an_unknown_zone_name_raises_value_error():
    naive = _naive_series(datetime(2026, 10, 9, 12, 0))

    with pytest.raises(ValueError):
        to_utc_ns(naive, TimeZoneSpec(kind="iana", value="Mars/Olympus_Mons"))


# --- to_utc_ns: DST edges ---------------------------------------------------


def _santiago_offset(wall_time: datetime) -> timedelta:
    """Offset of a naive local Santiago time, as zoneinfo resolves it."""
    return wall_time.replace(tzinfo=SANTIAGO).utcoffset()


def test_a_series_crossing_the_september_dst_start_converts_every_row():
    # 2026 DST starts at 24:00 on the first Saturday of September; these times are before
    # the change (-4) and after it (-3).
    wall_times = [datetime(2026, 9, 6, 12, 0), datetime(2026, 9, 7, 12, 0)]
    naive = _naive_series(*wall_times)
    expected = [_utc_ns_of(wall.replace(tzinfo=SANTIAGO).astimezone(UTC)) for wall in wall_times]

    utc_ns, _ = to_utc_ns(naive, TimeZoneSpec(kind="iana", value="America/Santiago"))

    assert list(utc_ns) == expected


def test_an_ambiguous_local_time_is_counted_in_a_tz_ambiguous_note():
    # A local time occurs twice when clocks go back; Santiago does that in April 2026.
    repeated_wall = datetime(2026, 4, 4, 23, 30)
    first = repeated_wall.replace(tzinfo=SANTIAGO, fold=0).utcoffset()
    second = repeated_wall.replace(tzinfo=SANTIAGO, fold=1).utcoffset()
    assert first != second  # the test's own precondition: this time really is ambiguous
    naive = _naive_series(repeated_wall)

    _, notes = to_utc_ns(naive, TimeZoneSpec(kind="iana", value="America/Santiago"))

    assert _notes_by_code(notes)["tz_ambiguous"]["rows"] == 1


def test_a_nonexistent_local_time_is_counted_in_a_tz_nonexistent_note():
    # A local time is skipped when clocks go forward: 00:00 on 2026-09-06 in Santiago.
    skipped_wall = datetime(2026, 9, 6, 0, 0)
    round_trip = (
        skipped_wall.replace(tzinfo=SANTIAGO).astimezone(UTC).astimezone(SANTIAGO)
        .replace(tzinfo=None)
    )
    assert round_trip != skipped_wall  # the test's own precondition: this time does not exist
    naive = _naive_series(skipped_wall)

    _, notes = to_utc_ns(naive, TimeZoneSpec(kind="iana", value="America/Santiago"))

    assert _notes_by_code(notes)["tz_nonexistent"]["rows"] == 1


def test_an_iana_conversion_always_reports_its_zone():
    naive = _naive_series(datetime(2026, 10, 9, 12, 0))

    _, notes = to_utc_ns(naive, TimeZoneSpec(kind="iana", value="America/Santiago"))

    zone_params = _notes_by_code(notes)["tz_iana"]
    assert zone_params["zone"] == "America/Santiago"
    # The Santiago offset of the test dates is computed by zoneinfo, not hard-coded here.
    assert zone_params["offset_last_hours"] == _santiago_offset(
        datetime(2026, 10, 9, 12, 0)
    ).total_seconds() / 3600
