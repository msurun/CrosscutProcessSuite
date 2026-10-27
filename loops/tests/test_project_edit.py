# Tests for project_edit: knowledge validation, per-loop editing, project building and
# atomic writing. Each test pins one behaviour a user of the module depends on.
"""Behavioural tests for ``crosscut_loops.project_edit``."""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

import pytest
from crosscut_loops.overview import LoopTags
from crosscut_loops.project_edit import (
    KnowledgeError,
    apply_knowledge,
    find_entry,
    loop_knowledge,
    project_from_loops,
    tag_range_defaults,
    validate_knowledge,
    write_project_atomic,
)
from crosscut_loops.project_loops import (
    AMPLITUDE_LIMIT_KEY,
    DEFAULT_PROCESS_KIND,
    DELAY_KEY,
    ID_KEY,
    LOOPS_KEY,
    MODE_KEY,
    NAME_KEY,
    OUT_KEY,
    PROCESS_KIND_KEY,
    PV_KEY,
    SP_KEY,
    ULTIMATE_PERIOD_KEY,
    loops_from_project,
)


def make_loop(
    name: str = "TIC-101",
    delay_s: float | None = None,
    ultimate_period_s: float | None = None,
    amplitude_limit: float | None = None,
    process_kind: str = DEFAULT_PROCESS_KIND,
) -> LoopTags:
    """A minimal analysable LoopTags for tests, with no engineering range on pv or out."""
    return LoopTags(
        name=name,
        pv=f"{name}_pv",
        sp=f"{name}_sp",
        out=f"{name}_out",
        mode=f"{name}_mode",
        unit="degC",
        eng_min=None,
        eng_max=None,
        delay_s=delay_s,
        ultimate_period_s=ultimate_period_s,
        amplitude_limit=amplitude_limit,
        out_low=None,
        out_high=None,
        process_kind=process_kind,
    )


def make_project() -> dict:
    """A project with two loops; the first carries every knowledge key set."""
    return {
        LOOPS_KEY: [
            {
                ID_KEY: "LIC-101",
                NAME_KEY: "LIC-101",
                PV_KEY: "LIC-101_pv",
                SP_KEY: "LIC-101_sp",
                OUT_KEY: "LIC-101_out",
                MODE_KEY: "LIC-101_mode",
                DELAY_KEY: 3.0,
                ULTIMATE_PERIOD_KEY: 12.0,
                AMPLITUDE_LIMIT_KEY: 5.0,
                PROCESS_KIND_KEY: "integrating",
            },
            {
                ID_KEY: "TIC-202",
                NAME_KEY: "TIC-202",
                PV_KEY: "TIC-202_pv",
                SP_KEY: "TIC-202_sp",
                OUT_KEY: "TIC-202_out",
                MODE_KEY: "TIC-202_mode",
            },
        ]
    }


def make_tag_rows(loop_name: str) -> list[dict]:
    """Tag rows for one loop's four tags, with id, unit and engineering range."""
    return [
        {"id": f"{loop_name}_pv", "unit": "degC", "eng_min": 0.0, "eng_max": 100.0},
        {"id": f"{loop_name}_sp", "unit": "degC", "eng_min": 0.0, "eng_max": 100.0},
        {"id": f"{loop_name}_out", "unit": "%", "eng_min": 0.0, "eng_max": 100.0},
        {"id": f"{loop_name}_mode", "unit": "", "eng_min": 0.0, "eng_max": 1.0},
    ]


# --- validate_knowledge -----------------------------------------------------


@pytest.mark.parametrize("key", [DELAY_KEY, ULTIMATE_PERIOD_KEY, AMPLITUDE_LIMIT_KEY])
def test_each_numeric_knowledge_key_is_accepted(key: str) -> None:
    cleaned = validate_knowledge({key: 2.5})
    assert cleaned[key] == 2.5


def test_process_kind_key_is_accepted() -> None:
    cleaned = validate_knowledge({PROCESS_KIND_KEY: "integrating"})
    assert cleaned[PROCESS_KIND_KEY] == "integrating"


def test_none_value_is_kept_as_none_to_signal_clearing() -> None:
    cleaned = validate_knowledge({DELAY_KEY: None})
    assert cleaned[DELAY_KEY] is None


def test_unknown_key_raises_knowledge_error() -> None:
    with pytest.raises(KnowledgeError):
        validate_knowledge({"mystery": 1.0})


def test_bool_value_is_rejected_as_a_number() -> None:
    with pytest.raises(KnowledgeError):
        validate_knowledge({DELAY_KEY: True})


def test_string_number_is_rejected() -> None:
    with pytest.raises(KnowledgeError):
        validate_knowledge({DELAY_KEY: "1.5"})


def test_zero_is_rejected() -> None:
    with pytest.raises(KnowledgeError):
        validate_knowledge({DELAY_KEY: 0})


def test_negative_is_rejected() -> None:
    with pytest.raises(KnowledgeError):
        validate_knowledge({DELAY_KEY: -1.0})


def test_nan_is_rejected() -> None:
    with pytest.raises(KnowledgeError):
        validate_knowledge({DELAY_KEY: float("nan")})


def test_inf_is_rejected() -> None:
    with pytest.raises(KnowledgeError):
        validate_knowledge({DELAY_KEY: float("inf")})


def test_bad_process_kind_is_rejected() -> None:
    with pytest.raises(KnowledgeError):
        validate_knowledge({PROCESS_KIND_KEY: "neither"})


def test_int_value_becomes_float() -> None:
    cleaned = validate_knowledge({DELAY_KEY: 4})
    assert isinstance(cleaned[DELAY_KEY], float)


def test_error_message_names_the_offending_key() -> None:
    with pytest.raises(KnowledgeError) as error_info:
        validate_knowledge({AMPLITUDE_LIMIT_KEY: -3.0})
    assert AMPLITUDE_LIMIT_KEY in str(error_info.value)


# --- find_entry -------------------------------------------------------------


def test_find_entry_by_name() -> None:
    project = make_project()
    entry = find_entry(project, "TIC-202")
    assert entry[ID_KEY] == "TIC-202"


def test_find_entry_by_id_when_name_is_absent() -> None:
    project = {LOOPS_KEY: [{ID_KEY: "FIC-303"}]}
    entry = find_entry(project, "FIC-303")
    assert entry[ID_KEY] == "FIC-303"


def test_find_entry_empty_name_falls_back_to_id() -> None:
    project = {LOOPS_KEY: [{ID_KEY: "AIC-404", NAME_KEY: ""}]}
    entry = find_entry(project, "AIC-404")
    assert entry[ID_KEY] == "AIC-404"


def test_find_entry_unknown_name_raises_key_error() -> None:
    with pytest.raises(KeyError):
        find_entry(make_project(), "nope")


def test_find_entry_returns_the_real_dict_inside_the_project() -> None:
    project = make_project()
    entry = find_entry(project, "TIC-202")
    assert entry is project[LOOPS_KEY][1]


# --- loop_knowledge ---------------------------------------------------------


def test_loop_knowledge_is_none_for_absent_keys() -> None:
    knowledge = loop_knowledge(make_project(), "TIC-202")
    assert knowledge[DELAY_KEY] is None


def test_loop_knowledge_defaults_process_kind_to_self_regulating() -> None:
    knowledge = loop_knowledge(make_project(), "TIC-202")
    assert knowledge[PROCESS_KIND_KEY] == "self_regulating"


# --- apply_knowledge --------------------------------------------------------


def test_apply_knowledge_sets_values() -> None:
    edited = apply_knowledge(make_project(), "TIC-202", {DELAY_KEY: 2.0})
    assert loop_knowledge(edited, "TIC-202")[DELAY_KEY] == 2.0


def test_apply_knowledge_none_removes_a_key() -> None:
    edited = apply_knowledge(make_project(), "LIC-101", {DELAY_KEY: None})
    entry = find_entry(edited, "LIC-101")
    assert DELAY_KEY not in entry


def test_apply_knowledge_leaves_input_project_unchanged() -> None:
    project = make_project()
    before = copy.deepcopy(project)
    apply_knowledge(project, "LIC-101", {DELAY_KEY: 9.0})
    assert project == before


def test_apply_knowledge_leaves_other_loops_untouched() -> None:
    project = make_project()
    edited = apply_knowledge(project, "TIC-202", {DELAY_KEY: 9.0})
    assert edited[LOOPS_KEY][0] == project[LOOPS_KEY][0]


def test_apply_knowledge_invalid_update_raises_knowledge_error() -> None:
    with pytest.raises(KnowledgeError):
        apply_knowledge(make_project(), "LIC-101", {DELAY_KEY: -1.0})


def test_apply_knowledge_unknown_loop_raises_key_error() -> None:
    with pytest.raises(KeyError):
        apply_knowledge(make_project(), "nope", {DELAY_KEY: 1.0})


# --- project_from_loops -----------------------------------------------------


def test_project_from_loops_omits_none_knowledge() -> None:
    project = project_from_loops([make_loop()])
    entry = find_entry(project, "TIC-101")
    assert DELAY_KEY not in entry


def test_project_from_loops_omits_default_process_kind() -> None:
    project = project_from_loops([make_loop(process_kind=DEFAULT_PROCESS_KIND)])
    entry = find_entry(project, "TIC-101")
    assert PROCESS_KIND_KEY not in entry


def test_project_from_loops_includes_non_default_knowledge() -> None:
    loop = make_loop(
        delay_s=2.0,
        ultimate_period_s=8.0,
        amplitude_limit=1.5,
        process_kind="integrating",
    )
    project = project_from_loops([loop])
    entry = find_entry(project, "TIC-101")
    assert entry[PROCESS_KIND_KEY] == "integrating"


def test_project_from_loops_round_trips_through_loops_from_project() -> None:
    loop = make_loop(delay_s=2.0)
    project = project_from_loops([loop])
    rebuilt = loops_from_project(project, make_tag_rows(loop.name))
    # Engineering ranges come from the tag rows, not from the project file, so they are masked.
    masked = dataclasses.replace(
        rebuilt[0], eng_min=None, eng_max=None, out_low=None, out_high=None
    )
    assert masked == loop


# --- write_project_atomic ---------------------------------------------------


def test_written_file_parses_back_to_the_same_mapping(tmp_path: Path) -> None:
    project = make_project()
    path = tmp_path / "project.json"
    write_project_atomic(path, project)
    assert json.loads(path.read_text(encoding="utf-8")) == project


def test_written_file_ends_with_a_newline(tmp_path: Path) -> None:
    path = tmp_path / "project.json"
    write_project_atomic(path, make_project())
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_written_file_keeps_non_ascii_text_readable(tmp_path: Path) -> None:
    path = tmp_path / "project.json"
    project = {LOOPS_KEY: [{NAME_KEY: "réacteur n°1"}]}
    write_project_atomic(path, project)
    assert "réacteur n°1" in path.read_text(encoding="utf-8")


def test_written_file_replaces_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "project.json"
    path.write_text("old content", encoding="utf-8")
    write_project_atomic(path, make_project())
    assert json.loads(path.read_text(encoding="utf-8")) == make_project()


def test_written_file_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    path = tmp_path / "project.json"
    write_project_atomic(path, make_project())
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


# --- engineering-range overrides --------------------------------------------

ENG_KEYS = ("pv_eng_min", "pv_eng_max", "out_eng_min", "out_eng_max")
ENG_LOOP = "LIC-101"


@pytest.mark.parametrize("key", ENG_KEYS)
def test_eng_override_accepts_zero_and_negative_numbers(key: str) -> None:
    assert validate_knowledge({key: -3})[key] == -3.0
    assert validate_knowledge({key: 0})[key] == 0.0


@pytest.mark.parametrize("key", ENG_KEYS)
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, "1"])
def test_eng_override_rejects_non_finite_and_non_numbers(key: str, bad: object) -> None:
    with pytest.raises(KnowledgeError):
        validate_knowledge({key: bad})


def test_eng_override_none_is_kept_to_signal_clearing() -> None:
    assert validate_knowledge({"pv_eng_min": None}) == {"pv_eng_min": None}


def test_apply_sets_and_then_clears_an_override() -> None:
    tags = make_tag_rows(ENG_LOOP)
    edited = apply_knowledge(make_project(), ENG_LOOP, {"pv_eng_min": -5, "pv_eng_max": 200}, tags)
    assert loop_knowledge(edited, ENG_LOOP)["pv_eng_max"] == 200.0
    cleared = apply_knowledge(edited, ENG_LOOP, {"pv_eng_min": None, "pv_eng_max": None}, tags)
    assert "pv_eng_min" not in cleared[LOOPS_KEY][0]
    assert loop_knowledge(cleared, ENG_LOOP)["pv_eng_max"] is None


def test_apply_rejects_min_not_below_max_in_one_update() -> None:
    tags = make_tag_rows(ENG_LOOP)
    with pytest.raises(KnowledgeError):
        apply_knowledge(make_project(), ENG_LOOP, {"out_eng_min": 10.0, "out_eng_max": 10.0}, tags)


def test_apply_rejects_override_crossing_the_tag_row_bound() -> None:
    tags = make_tag_rows(ENG_LOOP)
    with pytest.raises(KnowledgeError):
        apply_knowledge(make_project(), ENG_LOOP, {"pv_eng_min": 100.0}, tags)


def test_tag_range_defaults_come_from_the_tag_rows() -> None:
    tags = make_tag_rows(ENG_LOOP)
    edited = apply_knowledge(make_project(), ENG_LOOP, {"pv_eng_max": 50.0}, tags)
    defaults = tag_range_defaults(edited, ENG_LOOP, tags)
    assert defaults["pv_eng_default"] == {"min": 0.0, "max": 100.0}
    assert defaults["out_eng_default"] == {"min": 0.0, "max": 100.0}


# --- vendor key (#41) -------------------------------------------------------


@pytest.mark.parametrize("vendor", ["siemens_pid_compact", "abb_pidcc"])
def test_vendor_key_accepts_each_vendor_form(vendor: str) -> None:
    assert validate_knowledge({"vendor": vendor})["vendor"] == vendor


@pytest.mark.parametrize("vendor", ["honeywell", "", 3])
def test_vendor_key_rejects_an_unknown_form(vendor: object) -> None:
    with pytest.raises(KnowledgeError):
        validate_knowledge({"vendor": vendor})


def test_vendor_can_be_cleared() -> None:
    assert validate_knowledge({"vendor": None})["vendor"] is None


def test_schema_vendor_enum_matches_the_vendor_forms() -> None:
    from crosscut_loops.vendor_forms import VENDOR_FORMS

    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "project.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    loop_props = schema["properties"]["loops"]["items"]["properties"]
    assert set(loop_props["vendor"]["enum"]) == set(VENDOR_FORMS)
