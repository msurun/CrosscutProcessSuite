"""Schema and cross-reference checks of a controller of type mpc (Phase 7.3, #184)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from crosscut_connectors.site import validate_site

ROOT = Path(__file__).resolve().parents[2]
BASE: dict[str, Any] = json.loads(
    (ROOT / "docs/examples/generic_concentrator/_site/site.json").read_text(encoding="utf-8")
)
MPC = {"model": {"artifact": "wb", "sha256": "a" * 64}, "prediction_horizon": 30}
Mutation = Callable[[dict[str, Any]], None]


def _mpc_doc() -> dict[str, Any]:
    doc = copy.deepcopy(BASE)
    controller = doc["controllers"][0]
    controller["type"] = "mpc"
    controller.pop("rule_base", None)
    controller["mpc"] = copy.deepcopy(MPC)
    return doc


def _problems(mutate: Mutation) -> list[str]:
    doc = _mpc_doc()
    mutate(doc)
    return validate_site(doc)


def test_valid_mpc_controller() -> None:
    assert validate_site(_mpc_doc()) == []


def test_mpc_controller_needs_settings() -> None:
    problems = _problems(lambda d: d["controllers"][0].pop("mpc"))
    assert any("needs its mpc settings" in line for line in problems), problems


def test_fuzzy_controller_has_no_mpc_settings() -> None:
    doc = copy.deepcopy(BASE)
    doc["controllers"][0]["mpc"] = copy.deepcopy(MPC)
    assert any("only a controller of type mpc" in line for line in validate_site(doc))


def test_mpc_controller_has_no_rule_base() -> None:
    problems = _problems(lambda d: d["controllers"][0].update(rule_base="rb"))
    assert any("only a fuzzy controller has a rule_base" in line for line in problems)


@pytest.mark.parametrize("sha", ["", "xyz", "A" * 64, "a" * 63])
def test_model_hash_must_be_sha256_hex(sha: str) -> None:
    problems = _problems(lambda d: d["controllers"][0]["mpc"]["model"].update(sha256=sha))
    assert problems


def test_unknown_mpc_key_is_refused() -> None:
    assert _problems(lambda d: d["controllers"][0]["mpc"].update(mode="supervised"))


def test_target_only_on_a_cv_of_an_mpc_controller() -> None:
    def put(doc: dict[str, Any]) -> None:
        mv = next(v for v in doc["controllers"][0]["variables"] if v["role"] == "MV")
        mv["target"] = 1.0

    assert any("only a CV of an mpc controller" in line for line in _problems(put))
    doc = copy.deepcopy(BASE)
    doc["controllers"][0]["variables"][0]["target"] = 1.0
    assert any("only a CV" in line for line in validate_site(doc))


def test_cv_target_is_accepted() -> None:
    def put(doc: dict[str, Any]) -> None:
        cv = next(v for v in doc["controllers"][0]["variables"] if v["role"] == "CV")
        cv["target"] = 12.5

    assert _problems(put) == []
