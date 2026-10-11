"""Behaviour of crosscut_fuzzy.versions: saving history, listing it and diffing rule bases."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from crosscut_fuzzy.model import FuzzyModelError
from crosscut_fuzzy.versions import diff_documents, list_versions, load_version, save_version

EARLY = datetime(2026, 10, 11, 10, 15, 0, 0, tzinfo=UTC)
LATE = datetime(2026, 10, 11, 10, 15, 0, 500, tzinfo=UTC)
EARLY_ID = "20261011T101500000000Z"
LATE_ID = "20261011T101500000500Z"


def make_variable(variable_id: str, low: float = 0.0, high: float = 1.0) -> dict[str, Any]:
    """A variable with one triangular term, enough for diff tests."""
    return {
        "id": variable_id,
        "low": low,
        "high": high,
        "terms": [{"name": "cold", "shape": "tri", "params": [low, (low + high) / 2, high]}],
    }


def make_rule(rule_id: str, **overrides: Any) -> dict[str, Any]:
    """A rule with the required fields only; optional fields come from the caller."""
    rule = {
        "id": rule_id,
        "if": [{"variable": "temp", "is": "cold"}],
        "then": {"variable": "fan", "is": "cold"},
    }
    rule.update(overrides)
    return rule


def make_document(**overrides: Any) -> dict[str, Any]:
    """A minimal valid rule base: one input, one output, one rule."""
    document = {
        "name": "climate",
        "inputs": [make_variable("temp")],
        "outputs": [make_variable("fan")],
        "rules": [make_rule("r1")],
    }
    document.update(overrides)
    return document


def test_saving_a_version_returns_the_formatted_utc_timestamp(tmp_path: Path) -> None:
    version_id = save_version("climate", make_document(), tmp_path, now=EARLY)

    assert version_id == EARLY_ID


def test_a_saved_version_is_written_under_the_history_directory(tmp_path: Path) -> None:
    save_version("climate", make_document(), tmp_path, now=EARLY)

    assert (tmp_path / "_history" / "climate" / f"{EARLY_ID}.json").is_file()


def test_an_invalid_system_id_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    with pytest.raises(FuzzyModelError):
        save_version("../x", make_document(), tmp_path, now=EARLY)

    assert not (tmp_path / "_history").exists()


def test_listing_returns_newest_version_first(tmp_path: Path) -> None:
    save_version("climate", make_document(), tmp_path, now=EARLY)
    save_version("climate", make_document(), tmp_path, now=LATE)

    assert list_versions("climate", tmp_path) == [LATE_ID, EARLY_ID]


def test_listing_a_system_without_history_is_empty(tmp_path: Path) -> None:
    assert list_versions("climate", tmp_path) == []


def test_a_loaded_version_is_the_saved_document(tmp_path: Path) -> None:
    document = make_document(name="saved")
    save_version("climate", document, tmp_path, now=EARLY)

    assert load_version("climate", EARLY_ID, tmp_path) == document


def test_loading_an_unknown_version_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_version("climate", EARLY_ID, tmp_path)


def test_a_version_id_that_could_be_a_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FuzzyModelError):
        load_version("climate", "../secret", tmp_path)


def test_identical_documents_have_no_difference() -> None:
    assert diff_documents(make_document(), make_document()) == []


def test_a_changed_term_parameter_is_reported(tmp_path: Path) -> None:
    old = make_document()
    new = make_document()
    new["inputs"][0]["terms"][0]["params"] = [0.0, 0.3, 1.0]

    changes = diff_documents(old, new)

    assert changes == [
        {
            "code": "term_changed",
            "variable": "temp",
            "term": "cold",
            "old": {"shape": "tri", "params": [0.0, 0.5, 1.0]},
            "new": {"shape": "tri", "params": [0.0, 0.3, 1.0]},
        }
    ]


def test_added_and_removed_terms_and_variables_are_reported() -> None:
    old = make_document()
    new = make_document()
    new["inputs"].append(make_variable("humidity"))
    new["outputs"][0]["terms"].append(
        {"name": "hot", "shape": "tri", "params": [0.5, 0.75, 1.0]}
    )
    new["outputs"][0]["terms"] = [
        term for term in new["outputs"][0]["terms"] if term["name"] != "cold"
    ]

    changes = diff_documents(old, new)

    assert changes == [
        {"code": "term_added", "variable": "fan", "term": "hot"},
        {"code": "term_removed", "variable": "fan", "term": "cold"},
        {"code": "variable_added", "variable": "humidity"},
    ]


def test_a_range_change_and_a_rule_weight_change_are_reported() -> None:
    old = make_document()
    new = make_document()
    new["inputs"][0]["high"] = 100.0
    new["rules"] = [make_rule("r1", weight=2.0)]

    changes = diff_documents(old, new)

    range_change = {
        "code": "range_changed",
        "variable": "temp",
        "old": [0.0, 1.0],
        "new": [0.0, 100.0],
    }
    assert range_change in changes
    weight_change = [change for change in changes if change["code"] == "rule_changed"]
    assert weight_change == [{"code": "rule_changed", "rule": "r1", "fields": ["weight"]}]


def test_missing_optional_rule_fields_equal_their_defaults() -> None:
    explicit = make_document(rules=[make_rule("r1", operator="and", weight=1.0, enabled=True)])

    assert diff_documents(make_document(), explicit) == []


def test_adding_and_removing_a_rule_is_reported_in_a_stable_order() -> None:
    old = make_document(rules=[make_rule("r1"), make_rule("r2")])
    new = make_document(rules=[make_rule("r2"), make_rule("r3")])

    assert diff_documents(old, new) == [
        {"code": "rule_added", "rule": "r3"},
        {"code": "rule_removed", "rule": "r1"},
    ]
