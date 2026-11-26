"""Round-trip and refusal tests for the site catalogue CSV import/export."""

import copy
import csv
import io

import pytest
from crosscut_connectors.catalogue_csv import (
    CsvImport,
    RowError,
    apply_tags_import,
    export_tags_csv,
    parse_tags_csv,
)
from crosscut_connectors.site import validate_site

FIELDS = (
    "id,address,area,compression,description,dtype,eng_limits,missing_codes,"
    "missing_text_codes,name,quality_map,range,sampling,source,unit"
).split(",")


def _site() -> dict:
    """A valid minimal site whose tags exercise every catalogue field."""
    return {
        "schema_version": 1,
        "site": {"name": "Demo Plant"},
        "sources": [{"id": "pi", "driver": "pi"}],
        "tags": [
            {
                "id": "ti_101",
                "name": "Reactor feed temperature",
                "description": "Evaporateur \u2014 zone \u00e0 haute temp\u00e9rature, \u00b0C",
                "unit": "\u00b0C",
                "area": "reactor",
                "address": "pi://pi-01/TEMP/101",
                "dtype": "float",
                "missing_codes": [1, -1],
                "missing_text_codes": ["NoData"],
                "range": {"min": 40.0, "max": 200.0},
                "eng_limits": {"min": 0.0, "max": 150.0},
                "quality_map": {
                    "0": "good",
                    "16": "good",
                    "-1": "bad",
                    "1": "bad",
                    "2": "uncertain",
                    "17": "uncertain",
                },
                "sampling": {"period_s": 5, "on_change": True},
                "compression": {"deadband": 0.5, "deadband_unit": "engineering"},
            },
            {"id": "ti_102"},
        ],
    }


def _export() -> str:
    return export_tags_csv(_site())


def _csv(text: str) -> CsvImport:
    """Parse CSV text against a minimal valid site document."""
    return parse_tags_csv(text, {"schema_version": 1, "site": {"name": "x"}})


def _read(text: str) -> list:
    """The CSV rows as the module would see them, header first."""
    return list(csv.reader(io.StringIO(text)))


def _cell(row: int, column: str, text: str) -> str:
    """Cell value in `row` (0 = header) for `column`."""
    rows = _read(text)
    return rows[row][rows[0].index(column)]


def test_header_lists_id_first_then_remaining_fields_sorted():
    assert _read(_export())[0] == FIELDS


def test_export_writes_one_row_per_tag_in_site_order():
    rows = _read(_export())
    assert [row[0] for row in rows[1:]] == ["ti_101", "ti_102"]


def test_export_json_encodes_structured_fields_in_cells():
    text = _export()
    assert _cell(1, "missing_codes", text) == "[1, -1]"
    assert _cell(1, "eng_limits", text) == '{"min": 0.0, "max": 150.0}'
    assert '"deadband_unit": "engineering"' in _cell(1, "compression", text)


def test_export_leaves_unstated_optional_fields_as_empty_cells():
    row = _read(_export())[2]
    assert row[1] == row[3] == "" and row[3] != row[0]
    assert row == ["ti_102", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]


def test_export_round_trip_rebuilds_the_same_site():
    site = _site()
    assert apply_tags_import(site, parse_tags_csv(export_tags_csv(site), site)) == site


def test_apply_returns_a_new_document_and_leaves_the_input_untouched():
    site = _site()
    original = copy.deepcopy(site)
    result = parse_tags_csv(export_tags_csv(site), site)
    applied = apply_tags_import(site, result)
    assert applied is not site and applied["tags"] is not site["tags"]
    assert site == original


def test_apply_updates_existing_ids_in_place_and_appends_new_tags_in_file_order():
    site = _site()
    text = _export().replace('"ti_102"', '"ti_102",,unit', 1)
    text += "\nti_300,,,,,float,,,,,,\n"
    result = _csv(text)
    assert [tag["id"] for tag in apply_tags_import(site, result)["tags"]] == [
        "ti_101",
        "ti_102",
        "ti_300",
    ]
    assert [tag["id"] for tag in site["tags"]] == ["ti_101", "ti_102"]


def test_parse_refuses_unknown_columns():
    result = _csv("id,foo\nx1\n")
    assert result.tags == []
    assert result.errors == [
        RowError(0, "foo", "column is not a tag field of the schema")
    ]


def test_parse_refuses_missing_required_columns():
    result = _csv("name,unit\nTank,\u00b0C\n")
    assert result.tags == []
    assert result.errors == [RowError(0, "id", "required column is missing")]


def test_parse_refuses_rows_with_missing_required_values():
    result = _csv("id,unit\n,\u00b0C\n")
    assert result.tags == []
    assert result.errors == [RowError(1, "id", "required value is missing")]


def test_parse_refuses_values_that_violate_the_schema():
    result = _csv("id,dtype\nx1,varchar\n")
    assert result.tags == []
    assert result.errors == [
        RowError(
            1,
            "dtype",
            "must be one of float/int/bool/string",
        )
    ]


def test_parse_refuses_list_fields_holding_non_numeric_members():
    result = _csv("id,missing_codes\nx1,[\"a\"]\n")
    assert result.tags == []
    assert result.errors == [
        RowError(
            1,
            "missing_codes",
            "must be a JSON list of numbers",
        )
    ]


def test_parse_refuses_cells_that_are_not_json():
    result = _csv("id,range\nx1,abc\n")
    assert result.tags == []
    assert result.errors[0].row == 1
    assert result.errors[0].column == "range"
    assert "must be JSON" in result.errors[0].message


def test_parse_refuses_duplicate_ids_in_one_file():
    result = _csv("id\nx1\nx1\n")
    assert result.tags == []
    assert result.errors == [RowError(2, "id", "duplicate id 'x1'")]


def test_apply_refuses_a_refused_import():
    site = _site()
    result = _csv("id\nx1\nx1\n")
    with pytest.raises(ValueError, match="cannot apply a refused import"):
        apply_tags_import(site, result)
    assert site == _site()


def test_non_ascii_text_survives_the_full_round_trip():
    site = _site()
    applied = apply_tags_import(
        site, parse_tags_csv(export_tags_csv(site), site)
    )
    expected = site["tags"][0]["description"]
    assert applied["tags"][0]["description"] == expected
    assert "\u2014" in applied["tags"][0]["description"]


def test_exported_site_still_validates_against_the_schema():
    site = _site()
    applied = apply_tags_import(site, parse_tags_csv(export_tags_csv(site), site))
    problems = validate_site(applied)
    assert problems == []
