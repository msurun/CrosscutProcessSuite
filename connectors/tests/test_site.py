"""Tests for crosscut_connectors.site."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_connectors.site import (
    SiteError,
    load_site,
    read_settings_from_site,
    save_site,
    site_path,
    validate_site,
)

BASE_DOC: dict[str, Any] = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "docs/examples/generic_concentrator/_site/site.json"
    ).read_text(encoding="utf-8")
)


def test_load_site_round_trip(tmp_path: Path) -> None:
    doc = copy.deepcopy(BASE_DOC)
    save_site(tmp_path, doc)
    loaded_doc = load_site(tmp_path)
    assert loaded_doc == doc


def test_load_site_missing_file_raises_site_error(tmp_path: Path) -> None:
    with pytest.raises(SiteError):
        load_site(tmp_path)


def test_invalid_json_file_raises_site_error(tmp_path: Path) -> None:
    path = site_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("invalid json", encoding="utf-8")
    with pytest.raises(SiteError):
        load_site(tmp_path)


def test_non_object_json_raises_site_error(tmp_path: Path) -> None:
    path = site_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(SiteError):
        load_site(tmp_path)


def test_validate_site_base_doc_is_valid() -> None:
    doc = copy.deepcopy(BASE_DOC)
    assert validate_site(doc) == []


def test_validate_site_invalid_tag_role_returns_error_line() -> None:
    doc = copy.deepcopy(BASE_DOC)
    doc["tags"][0]["role"] = "XX"
    errors = validate_site(doc)
    assert any(line.startswith("tags.0.role") for line in errors)


def test_validate_site_duplicate_tag_id_returns_error() -> None:
    doc = copy.deepcopy(BASE_DOC)
    doc["tags"][0]["id"] = doc["tags"][1]["id"]
    errors = validate_site(doc)
    assert any("duplicate id" in line for line in errors)


def test_validate_site_duplicate_source_id_returns_error() -> None:
    doc = copy.deepcopy(BASE_DOC)
    dup = copy.deepcopy(doc["sources"][0])
    doc["sources"].append(dup)
    errors = validate_site(doc)
    assert any("duplicate id" in line for line in errors)


def test_validate_site_unknown_source_returns_error() -> None:
    doc = copy.deepcopy(BASE_DOC)
    doc["tags"][0]["source"] = "unknown"
    errors = validate_site(doc)
    assert any("unknown source" in line for line in errors)


def test_validate_site_eng_limits_min_above_max_returns_error() -> None:
    doc = copy.deepcopy(BASE_DOC)
    doc["tags"][0]["eng_limits"]["min"] = 100
    doc["tags"][0]["eng_limits"]["max"] = 0
    errors = validate_site(doc)
    assert any("min is above max" in line for line in errors)


def test_validate_site_range_min_above_max_returns_error() -> None:
    doc = copy.deepcopy(BASE_DOC)
    doc["tags"][0]["range"] = {"min": 100, "max": 0}
    errors = validate_site(doc)
    assert any("min is above max" in line for line in errors)


def test_validate_site_decimal_comma_with_comma_delimiter_returns_error() -> None:
    doc = copy.deepcopy(BASE_DOC)
    doc["import"]["decimal_comma"] = True
    doc["import"]["delimiter"] = ","
    errors = validate_site(doc)
    assert any("decimal_comma: needs a delimiter other than a comma" in line for line in errors)


def test_save_site_rejects_invalid_doc_and_writes_no_file(tmp_path: Path) -> None:
    doc = copy.deepcopy(BASE_DOC)
    doc["tags"][0]["role"] = "XX"
    with pytest.raises(SiteError):
        save_site(tmp_path, doc)
    assert not site_path(tmp_path).exists()


def test_save_site_leaves_no_tmp_file_in_site_dir(tmp_path: Path) -> None:
    doc = copy.deepcopy(BASE_DOC)
    save_site(tmp_path, doc)
    assert not any(path.suffix == ".tmp" for path in site_path(tmp_path).parent.iterdir())


def test_read_settings_from_site_empty_doc_returns_empty_dict() -> None:
    assert read_settings_from_site({}) == {}


def test_read_settings_from_site_missing_codes_converts_to_tuple_of_floats() -> None:
    doc = {"import": {"missing_codes": ["-999"]}}
    settings = read_settings_from_site(doc)
    assert settings["missing_codes"] == (-999.0,)


def test_read_settings_from_site_time_names_converts_to_frozenset_of_lowercase_strings() -> None:
    doc = {"import": {"time_names": ["Time"]}}
    settings = read_settings_from_site(doc)
    assert settings["time_names"] == frozenset({"time"})


def test_read_settings_from_site_unstated_keys_absent_from_result() -> None:
    doc = {"import": {"decimal_comma": True}}
    settings = read_settings_from_site(doc)
    assert "delimiter" not in settings
