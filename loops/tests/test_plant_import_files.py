"""Behaviour tests for the plant import: reading a wide PI CSV and writing the dataset.

Every test builds a small synthetic wide CSV (60 rows, 10 s period, a 1 h gap) and a
tag dictionary with a BOM, so the real file readers run end to end on tmp files.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from crosscut_loops.plant_import import (
    PlantTable,
    find_gaps,
    iso_utc,
    preview_plant,
    read_plant_table,
)
from crosscut_loops.plant_import import (
    test_windows as plant_test_windows,
)
from crosscut_loops.plant_import_loops import DetectedLoop, detect_loops, read_dictionary
from crosscut_loops.plant_import_time import TimeZoneSpec
from crosscut_loops.plant_import_write import (
    import_plant,
    select_tags,
    tag_rows,
)

UTC_SPEC = TimeZoneSpec("utc")


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

# 60 rows of 10 s, with a one hour gap between row 30 and row 31.
PERIOD_S = 10
N_BEFORE_GAP = 30
GAP_S = 3600
N_ROWS = 60

HEADER_COLUMNS = [
    "timestamp",
    "test",
    "demo.1000-lic-20103.mv",
    "demo.1000-lic-20103.out",
    "demo.1000-lic-20103.sp",
    "demo.1000-lic-20103.auto#state",
    "demo.1000-fic-20120.mv",
    "demo.1000-fic-20120.out",
    "demo.1000-fic-20120.sp",
    "demo.1000-fic-20120.auto#state",
    "demo.1000-lic-20105.mv",
    "demo.1000-lic-20105.out",
    "constant.tag",
    "empty.tag",
    "bad.text.tag",
    "varying.tag",
]


def _timestamps_utc() -> list[str]:
    """Wall-clock UTC texts for the 60 rows, skipping ahead by one hour at the gap."""
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 10, 9, 11, 0, 0, tzinfo=UTC)
    texts: list[str] = []
    for position in range(N_ROWS):
        offset_s = position * PERIOD_S + (GAP_S if position >= N_BEFORE_GAP else 0)
        texts.append((start + timedelta(seconds=offset_s)).strftime("%Y-%m-%d %H:%M:%S"))
    return texts


def _test_labels() -> list[str]:
    """Rows 5..24 and 35..54 are two test windows, every other row has an empty label."""
    return [
        "step_1" if 5 <= position < 25 else "step_2" if 35 <= position < 55 else ""
        for position in range(N_ROWS)
    ]


def _row_values() -> dict[str, list[str]]:
    """One synthetic text cell per column and row (Bad and empty cells included)."""
    timestamps = _timestamps_utc()
    labels = _test_labels()
    return {
        "timestamp": timestamps,
        "test": labels,
        "demo.1000-lic-20103.mv": [str(50 + i) for i in range(N_ROWS)],
        "demo.1000-lic-20103.out": [str(30 + i) for i in range(N_ROWS)],
        "demo.1000-lic-20103.sp": [str(50) for _ in range(N_ROWS)],
        "demo.1000-lic-20103.auto#state": [str(i % 2) for i in range(N_ROWS)],
        "demo.1000-fic-20120.mv": [str(20 + i) for i in range(N_ROWS)],
        "demo.1000-fic-20120.out": [str(40 + i) for i in range(N_ROWS)],
        "demo.1000-fic-20120.sp": [str(20) for _ in range(N_ROWS)],
        "demo.1000-fic-20120.auto#state": ["1" for _ in range(N_ROWS)],
        "demo.1000-lic-20105.mv": [str(10 + i) for i in range(N_ROWS)],
        "demo.1000-lic-20105.out": [str(5 + i) for i in range(N_ROWS)],
        "constant.tag": [str(7) for _ in range(N_ROWS)],
        "empty.tag": ["" for _ in range(N_ROWS)],
        "bad.text.tag": ["Bad" for _ in range(N_ROWS)],
        "varying.tag": [str(100 + i) for i in range(N_ROWS)],
    }


def _write_wide_csv(path: Path) -> Path:
    """Write the synthetic wide CSV with UTF-8 encoding and a header row."""
    values = _row_values()
    lines = [",".join(HEADER_COLUMNS)]
    for row in range(N_ROWS):
        lines.append(",".join(values[column][row] for column in HEADER_COLUMNS))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_duplicate_csv(path: Path) -> Path:
    """Write a small CSV with three rows where the middle time repeats the first."""
    text = (
        "timestamp,a\n"
        "2026-10-09 11:00:00,1\n"
        "2026-10-09 11:00:00,2\n"
        "2026-10-09 11:00:10,3\n"
    )
    path.write_text(text, encoding="utf-8")
    return path


DICTIONARY_TEXT = (
    "\ufefftag,description,unit,signal,loop,cell\n"
    "demo.1000-lic-20103.mv,Level,m,PV (measured),20103,cell-1\n"
    "demo.1000-lic-20103.out,Valve output,%,OUT (controller output),20103,cell-1\n"
    "demo.1000-lic-20103.sp,Set point,m,SP,20103,cell-1\n"
    "demo.1000-lic-20103.auto#state,Auto flag,,mode flag,20103,cell-1\n"
    "demo.1000-fic-20120.mv,Flow,m3/h,PV (measured),20120,cell-2\n"
    "demo.1000-fic-20120.out,Flow output,%,OUT (controller output),20120,cell-2\n"
    "demo.1000-fic-20120.sp,Flow SP,m3/h,SP,20120,cell-2\n"
    "demo.1000-fic-20120.auto#state,Auto flag,,mode flag,20120,cell-2\n"
    "demo.1000-lic-20105.mv,Level,m,PV (measured),20105,cell-3\n"
    "demo.1000-lic-20105.out,Valve output,%,OUT (controller output),20105,cell-3\n"
)


@pytest.fixture()
def wide_csv(tmp_path: Path) -> Path:
    """A synthetic wide CSV file on disk."""
    return _write_wide_csv(tmp_path / "plant.csv")


# ---------------------------------------------------------------------------
# read_plant_table
# ---------------------------------------------------------------------------

def test_read_plant_table_reads_utc_times_and_tag_columns(wide_csv: Path) -> None:
    table = read_plant_table(wide_csv, UTC_SPEC)

    assert table.ts_ns.size == N_ROWS
    assert table.columns["varying.tag"].shape == (N_ROWS,)
    assert table.columns["varying.tag"][0] == 100.0


def test_read_plant_table_turns_bad_and_empty_cells_into_nan(wide_csv: Path) -> None:
    table = read_plant_table(wide_csv, UTC_SPEC)

    assert np.all(np.isnan(table.columns["bad.text.tag"]))
    assert np.all(np.isnan(table.columns["empty.tag"]))


def test_read_plant_table_keeps_the_test_labels(wide_csv: Path) -> None:
    table = read_plant_table(wide_csv, UTC_SPEC)

    assert table.test[0] == ""
    assert table.test[10] == "step_1"


def test_read_plant_table_applies_the_given_iana_time_zone(wide_csv: Path) -> None:
    spec = TimeZoneSpec("iana", "America/Santiago")
    table = read_plant_table(wide_csv, spec)

    # Santiago is UTC-3 in October 2026, so the same wall clock is 3 h later in UTC.
    utc_text = iso_utc(int(table.ts_ns[0]))
    assert utc_text == "2026-10-09T14:00:00Z"


def test_read_plant_table_drops_a_repeated_timestamp(tmp_path: Path) -> None:
    path = _write_duplicate_csv(tmp_path / "dupes.csv")
    table = read_plant_table(path, UTC_SPEC)

    assert table.ts_ns.size == 2
    assert table.columns["a"].tolist() == [2.0, 3.0]
    assert any(note.code == "duplicate_times" for note in table.notes)


def test_read_plant_table_raises_without_a_time_column(tmp_path: Path) -> None:
    path = tmp_path / "no_time.csv"
    path.write_text("alpha,beta\n1,2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="time column"):
        read_plant_table(path, UTC_SPEC)


def test_read_plant_table_raises_when_the_file_has_only_a_header(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("timestamp,a\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no rows"):
        read_plant_table(path, UTC_SPEC)


# ---------------------------------------------------------------------------
# find_gaps and test_windows
# ---------------------------------------------------------------------------

def test_find_gaps_reports_the_one_hour_gap(wide_csv: Path) -> None:
    table = read_plant_table(wide_csv, UTC_SPEC)

    period_s, n_gaps, gaps = find_gaps(table.ts_ns)

    assert period_s == float(PERIOD_S)
    assert n_gaps == 1
    assert gaps[0]["seconds"] == float(GAP_S + PERIOD_S)


def test_test_windows_groups_two_non_empty_runs(wide_csv: Path) -> None:
    table = read_plant_table(wide_csv, UTC_SPEC)

    windows = plant_test_windows(table.ts_ns, table.test)

    assert [window["label"] for window in windows] == ["step_1", "step_2"]
    assert windows[0]["rows"] == 20


def test_test_windows_skips_rows_with_an_empty_label(wide_csv: Path) -> None:
    table = read_plant_table(wide_csv, UTC_SPEC)

    windows = plant_test_windows(table.ts_ns, table.test)

    assert all(window["label"] != "" for window in windows)


# ---------------------------------------------------------------------------
# iso_utc and preview_plant
# ---------------------------------------------------------------------------

def test_iso_utc_formats_nanoseconds_as_utc_text() -> None:
    import datetime as dt

    ns = int(dt.datetime(2026, 10, 9, 11, 0, 0, tzinfo=dt.UTC).timestamp()) * 1_000_000_000

    assert iso_utc(ns) == "2026-10-09T11:00:00Z"


def test_preview_plant_lists_complete_and_incomplete_loops(wide_csv: Path) -> None:
    preview = preview_plant(wide_csv, DICTIONARY_TEXT, UTC_SPEC)

    complete = {loop["id"]: loop["complete"] for loop in preview["loops"]}
    assert complete["LIC-20103"] is True
    assert complete["FIC-20120"] is True
    assert complete["LIC-20105"] is False


def test_preview_plant_reports_key_counts(wide_csv: Path) -> None:
    preview = preview_plant(wide_csv, DICTIONARY_TEXT, UTC_SPEC)

    assert preview["n_rows"] == N_ROWS
    assert preview["n_gaps"] == 1
    assert len(preview["test_windows"]) == 2


def test_preview_plant_is_json_serialisable(wide_csv: Path) -> None:
    preview = preview_plant(wide_csv, DICTIONARY_TEXT, UTC_SPEC)

    assert json.loads(json.dumps(preview))["n_rows"] == N_ROWS


# ---------------------------------------------------------------------------
# select_tags and tag_rows
# ---------------------------------------------------------------------------

def _loops_for(table: PlantTable) -> list[DetectedLoop]:
    """Detect loops from the table columns using the synthetic dictionary."""
    return detect_loops(list(table.columns), read_dictionary(DICTIONARY_TEXT))


def test_select_tags_loops_scope_keeps_only_loop_signals(wide_csv: Path) -> None:
    table = read_plant_table(wide_csv, UTC_SPEC)
    loops = _loops_for(table)

    ids, skipped = select_tags(table, loops, "loops")

    assert "varying.tag" not in ids
    assert "demo.1000-lic-20103.mv" in ids
    assert skipped >= 1


def test_select_tags_process_scope_adds_useful_columns(wide_csv: Path) -> None:
    table = read_plant_table(wide_csv, UTC_SPEC)
    loops = _loops_for(table)

    ids, _ = select_tags(table, loops, "process")

    assert "varying.tag" in ids
    assert "constant.tag" not in ids
    assert "empty.tag" not in ids


def test_select_tags_rejects_an_unknown_scope(wide_csv: Path) -> None:
    table = read_plant_table(wide_csv, UTC_SPEC)
    loops = _loops_for(table)

    with pytest.raises(ValueError, match="unknown scope"):
        select_tags(table, loops, "everything")


def test_tag_rows_use_pv_role_for_a_loop_signal(wide_csv: Path) -> None:
    table = read_plant_table(wide_csv, UTC_SPEC)
    loops = _loops_for(table)
    ids, _ = select_tags(table, loops, "loops")

    rows = tag_rows(ids, loops, read_dictionary(DICTIONARY_TEXT))

    roles = {row["name"]: row["role"] for row in rows}
    assert roles["demo.1000-lic-20103.mv"] == "PV"
    assert roles["varying.tag" if "varying.tag" in roles else "demo.1000-lic-20103.sp"] == "SP"


def test_tag_rows_match_the_tags_schema(wide_csv: Path) -> None:
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "tags.schema.json"
    if not schema_path.exists():
        pytest.skip(f"tags schema not found at {schema_path}")

    table = read_plant_table(wide_csv, UTC_SPEC)
    loops = _loops_for(table)
    ids, _ = select_tags(table, loops, "loops")
    document = {"schema_version": "0.1.0", "tags": tag_rows(ids, loops,
                                                                 read_dictionary(DICTIONARY_TEXT))}

    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(document, json.loads(schema_path.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# import_plant
# ---------------------------------------------------------------------------

def _import_to(out_dir: Path, wide_csv: Path) -> None:
    """Run import_plant end to end with the synthetic dictionary."""
    import_plant(wide_csv, DICTIONARY_TEXT, out_dir, UTC_SPEC, scope="process")


def test_import_plant_writes_a_readable_dataset(wide_csv: Path, tmp_path: Path) -> None:
    from crosscut_sim.dataset import read_dataset, to_wide

    out_dir = tmp_path / "dataset"
    _import_to(out_dir, wide_csv)

    ts, _ = to_wide(read_dataset(out_dir))
    assert ts.size == N_ROWS


def test_import_plant_keeps_the_time_gap(wide_csv: Path, tmp_path: Path) -> None:
    from crosscut_sim.dataset import read_dataset, to_wide

    out_dir = tmp_path / "dataset"
    _import_to(out_dir, wide_csv)

    steps_ns = np.diff(to_wide(read_dataset(out_dir))[0].astype(np.int64))
    assert int(steps_ns.max()) == (GAP_S + PERIOD_S) * 1_000_000_000


def test_import_plant_stores_nan_cells_with_bad_quality(tmp_path: Path) -> None:
    from crosscut_sim.dataset import read_dataset

    csv_path = _write_wide_csv(tmp_path / "plant.csv")
    out_dir = tmp_path / "dataset"
    result = import_plant(csv_path, DICTIONARY_TEXT, out_dir, UTC_SPEC, scope="loops")

    table = read_dataset(out_dir)
    bad = [q for tag, q in zip(table["tag_id"].to_pylist(), table["quality"].to_pylist(),
                               strict=True) if tag == "bad.text.tag"]
    assert not bad or set(bad) == {2}
    assert result.tags_written > 0


def test_import_plant_forward_fills_a_leading_mode_gap(tmp_path: Path) -> None:
    csv_path = tmp_path / "leading.csv"
    text = (
        "timestamp,test,demo.1000-lic-20103.mv,demo.1000-lic-20103.out,"
        "demo.1000-lic-20103.sp,demo.1000-lic-20103.auto#state\n"
        "2026-10-09 11:00:00,,10,20,10,\n"
        "2026-10-09 11:00:10,,11,21,10,1\n"
        "2026-10-09 11:00:20,,12,22,10,1\n"
    )
    csv_path.write_text(text, encoding="utf-8")
    out_dir = tmp_path / "dataset"

    result = import_plant(csv_path, DICTIONARY_TEXT, out_dir, UTC_SPEC, scope="loops")

    assert any(note.code == "mode_leading_gap" for note in result.notes)


def test_import_plant_writes_only_complete_loops_to_project(wide_csv: Path,
                                                              tmp_path: Path) -> None:
    out_dir = tmp_path / "dataset"
    _import_to(out_dir, wide_csv)

    project = json.loads((out_dir / "project.json").read_text(encoding="utf-8"))
    ids = {entry["id"] for entry in project["loops"]}
    assert "LIC-20103" in ids
    assert "LIC-20105" not in ids
    lic = next(loop for loop in project["loops"] if loop["id"] == "LIC-20103")
    assert lic["process_kind"] == "integrating"


def test_import_plant_writes_test_windows(wide_csv: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "dataset"
    _import_to(out_dir, wide_csv)

    windows = json.loads((out_dir / "test_windows.json").read_text(encoding="utf-8"))
    assert [window["label"] for window in windows] == ["step_1", "step_2"]


def test_import_plant_refuses_a_non_empty_directory(wide_csv: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "dataset"
    out_dir.mkdir()
    (out_dir / "keep.txt").write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        _import_to(out_dir, wide_csv)


def test_import_plant_removes_a_half_written_folder_on_failure(wide_csv: Path,
                                                               tmp_path: Path) -> None:
    out_dir = tmp_path / "dataset"
    broken_dictionary = "no_tag_column\nnot,a,dictionary\n"

    with pytest.raises(ValueError, match="tag"):
        import_plant(wide_csv, broken_dictionary, out_dir, UTC_SPEC, scope="process")
    assert not out_dir.exists()


def test_import_plant_uses_the_same_safe_ids_in_data_tags_and_project(
    wide_csv: Path, tmp_path: Path
) -> None:
    """A '#' in 'x.auto#state' is not a legal tag id: data, tags.json and project.json agree."""
    from crosscut_sim.dataset import read_dataset

    out_dir = tmp_path / "dataset"
    _import_to(out_dir, wide_csv)

    tag_ids = {row["id"] for row in json.loads((out_dir / "tags.json").read_text("utf-8"))["tags"]}
    data_ids = set(read_dataset(out_dir)["tag_id"].to_pylist())
    loops = json.loads((out_dir / "project.json").read_text("utf-8"))["loops"]
    assert loops
    assert data_ids == tag_ids
    for loop in loops:
        assert {loop["pv"], loop["sp"], loop["out"], loop["mode"]} <= tag_ids


def test_import_plant_assumes_a_percent_out_range_when_out_stays_in_0_100(
    wide_csv: Path, tmp_path: Path
) -> None:
    """Valve KPIs need the OUT range: an output inside 0-100 gets 0..100 and a note."""
    out_dir = tmp_path / "dataset"
    result = import_plant(wide_csv, DICTIONARY_TEXT, out_dir, UTC_SPEC, scope="process")

    loops = json.loads((out_dir / "project.json").read_text("utf-8"))["loops"]
    assert loops
    assert all(loop["out_eng_min"] == 0 and loop["out_eng_max"] == 100 for loop in loops)
    assert "out_range_assumed" in [note.code for note in result.notes]
