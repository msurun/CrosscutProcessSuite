"""Tests for PID parameter policy targets (ADR 014 step 1): schemas, parsing, item checks.

Covers the write-policy and plant-map oneOf schemas, back-compat of setpoint policies,
params_from_dict, policies_from_dict and every refusal code of check_param_items.
Nothing is ever clamped: a value outside the rules is refused.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest
from crosscut_gateway.interfaces import ParamItem, ParamPolicy
from crosscut_gateway.policy import (
    PolicyError,
    check_param_items,
    params_from_dict,
    policies_from_dict,
    policy_from_dict,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
POLICY_SCHEMA = ROOT / "schemas" / "write-policy.schema.json"
PLANT_SCHEMA = ROOT / "schemas" / "plant-map.schema.json"
EXAMPLE_POLICY = ROOT / "deploy" / "examples" / "write-policy.example.json"
EXAMPLE_PLANT = ROOT / "deploy" / "examples" / "plant-map.example.json"

SETPOINT: dict[str, Any] = {
    "limits": [0.0, 100.0], "max_step": 10.0, "max_rate_per_s": 5.0, "min_interval_s": 1.0,
    "allowed_loop_modes": ["CAS", "AUTO"], "hold_off_s": 60.0, "watchdog_s": 5.0,
    "readback_tolerance": 0.5,
}
GAIN: dict[str, Any] = {
    "kind": "pid_param", "loop": "FIC101", "param": "gain", "unit": "1",
    "vendor_form": "siemens_pid_compact", "limits": [0.1, 10.0], "max_ratio": 2.0,
    "readback_tolerance": 0.0, "min_interval_s": 600.0, "allowed_loop_modes": ["AUTO"],
}


def _ti() -> dict[str, Any]:
    """A valid Ti target for the same loop, in seconds."""
    return {**GAIN, "param": "ti", "unit": "s", "limits": [5.0, 600.0]}


def _doc(**targets: dict[str, Any]) -> dict[str, Any]:
    """A policy document in confirm mode with the given targets."""
    return {"version": 1, "mode": "confirm", "targets": copy.deepcopy(targets)}


def _validator(path: Path) -> Draft202012Validator:
    """Validator for a schema file, checking the schema itself first."""
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _item(**kw: Any) -> ParamItem:
    """A valid gain item 1.0 -> 1.5 against the GAIN policy; keywords override fields."""
    base: dict[str, Any] = {
        "param": "gain", "target": "FIC101.KP", "unit": "1",
        "vendor_form": "siemens_pid_compact", "from_value": 1.0, "to_value": 1.5,
    }
    return ParamItem(**{**base, **kw})


def _policies() -> dict[str, ParamPolicy]:
    """Parsed policies of FIC101.KP (gain), FIC101.TI (ti) and FIC101.TD (td)."""
    td = {**GAIN, "param": "td", "unit": "s", "limits": [0.0, 60.0]}
    doc = _doc(**{"FIC101.KP": GAIN, "FIC101.TI": _ti(), "FIC101.TD": td})
    return params_from_dict(doc)


def _check(item: ParamItem, current: Any = 1.0) -> list[str]:
    """Run check_param_items for one item with the live reading ``current``."""
    return check_param_items(_policies(), [item], {item.target: current})


# --- schema acceptance and rejection -------------------------------------------------------


def test_policy_schema_accepts_setpoint_without_kind_and_with_kind() -> None:
    """A missing kind means setpoint; kind setpoint is accepted too."""
    v = _validator(POLICY_SCHEMA)
    assert v.is_valid(_doc(**{"A.SP": SETPOINT}))
    assert v.is_valid(_doc(**{"A.SP": {**SETPOINT, "kind": "setpoint"}}))


def test_policy_schema_accepts_pid_param_and_mixed() -> None:
    """A pid_param target and a setpoint target may share one document."""
    v = _validator(POLICY_SCHEMA)
    assert v.is_valid(_doc(**{"FIC101.KP": GAIN}))
    assert v.is_valid(_doc(**{"FIC101.KP": GAIN, "FIC101.SP": SETPOINT}))


def test_policy_schema_accepts_existing_example() -> None:
    """The shipped example policy stays valid: two setpoints and one gain target."""
    data = json.loads(EXAMPLE_POLICY.read_text(encoding="utf-8"))
    assert _validator(POLICY_SCHEMA).is_valid(data)
    assert set(policy_from_dict(data)) == {"FIC101.SP", "TIC201.SP"}
    assert set(params_from_dict(data)) == {"FIC101.KP"}


@pytest.mark.parametrize("field", list(GAIN))
def test_policy_schema_rejects_missing_pid_field(field: str) -> None:
    """Every pid_param field is required (a missing kind is a setpoint with extra keys)."""
    target = {k: v for k, v in GAIN.items() if k != field}
    assert not _validator(POLICY_SCHEMA).is_valid(_doc(**{"X.KP": target}))


@pytest.mark.parametrize("extra", ["max_step", "max_rate_per_s", "hold_off_s", "watchdog_s", "x"])
def test_policy_schema_rejects_setpoint_fields_on_pid_param(extra: str) -> None:
    """A parameter target has no rate, watchdog or hold-off fields."""
    assert not _validator(POLICY_SCHEMA).is_valid(_doc(**{"X.KP": {**GAIN, extra: 1.0}}))


@pytest.mark.parametrize(
    "patch",
    [
        {"kind": "other"}, {"param": "kc"}, {"max_ratio": 1.0}, {"max_ratio": 0.5},
        {"readback_tolerance": -0.1}, {"min_interval_s": -1}, {"allowed_loop_modes": []},
        {"limits": [0.1]}, {"limits": [0.0, 10.0]}, {"limits": [-1.0, 10.0]},
        {"limits": [0.1, "x"]}, {"unit": ""}, {"loop": "bad loop"}, {"vendor_form": ""},
    ],
)
def test_policy_schema_rejects_bad_pid_values(patch: dict[str, Any]) -> None:
    """Out-of-contract values of a pid_param target fail schema validation."""
    assert not _validator(POLICY_SCHEMA).is_valid(_doc(**{"X.KP": {**GAIN, **patch}}))


def test_policy_schema_td_and_tf_allow_zero_lower_limit() -> None:
    """Td and Tf may start at 0; gain and Ti may not."""
    v = _validator(POLICY_SCHEMA)
    assert v.is_valid(_doc(**{"X.TD": {**GAIN, "param": "td", "limits": [0.0, 60.0]}}))
    assert v.is_valid(_doc(**{"X.TF": {**GAIN, "param": "tf", "limits": [0.0, 60.0]}}))
    assert not v.is_valid(_doc(**{"X.TI": {**GAIN, "param": "ti", "limits": [0.0, 60.0]}}))


def test_plant_schema_accepts_example_and_pid_target() -> None:
    """The shipped plant map stays valid; a pid_param target is accepted."""
    v = _validator(PLANT_SCHEMA)
    plant = json.loads(EXAMPLE_PLANT.read_text(encoding="utf-8"))
    assert v.is_valid(plant)
    pid = {"param_node": "ns=2;s=P.KP", "data_type": "Float", "mode_node": "ns=2;s=P.M",
           "mode_values": {"AUTO": 1}}
    plant["targets"]["FIC101.KP"] = pid
    assert v.is_valid(plant)
    plant["targets"]["FIC101.KP"] = {**pid, "readback_node": "ns=2;s=P.KP_R", "data_type": "Double"}
    assert v.is_valid(plant)


@pytest.mark.parametrize(
    "patch",
    [{"data_type": "Int32"}, {"data_type": "float"}, {"mode_values": {}}, {"extra": 1},
     {"param_node": ""}, {"setpoint_node": "ns=2;s=x"}],
)
def test_plant_schema_rejects_bad_pid_target(patch: dict[str, Any]) -> None:
    """Bad data_type, empty mode_values, unknown keys and mixed branches are rejected."""
    plant = json.loads(EXAMPLE_PLANT.read_text(encoding="utf-8"))
    pid = {"param_node": "ns=2;s=P.KP", "data_type": "Float", "mode_node": "ns=2;s=P.M",
           "mode_values": {"AUTO": 1}, **patch}
    plant["targets"]["FIC101.KP"] = pid
    assert not _validator(PLANT_SCHEMA).is_valid(plant)


def test_plant_schema_rejects_missing_pid_required() -> None:
    """param_node, mode_node, data_type and mode_values are required."""
    pid = {"param_node": "a", "data_type": "Float", "mode_node": "b", "mode_values": {"A": 1}}
    plant = json.loads(EXAMPLE_PLANT.read_text(encoding="utf-8"))
    for field in pid:
        plant["targets"]["K"] = {k: v for k, v in pid.items() if k != field}
        assert not _validator(PLANT_SCHEMA).is_valid(plant), field


# --- parsing ---------------------------------------------------------------------------------


def test_policy_from_dict_back_compat_and_skips_pid() -> None:
    """Setpoint targets parse as before (with or without kind); pid_param targets are skipped."""
    doc = _doc(**{"A.SP": SETPOINT, "B.SP": {**SETPOINT, "kind": "setpoint"}, "A.KP": GAIN})
    parsed = policy_from_dict(doc)
    assert set(parsed) == {"A.SP", "B.SP"}
    assert parsed["A.SP"] == parsed["B.SP"]
    assert policy_from_dict({"A.SP": SETPOINT}).keys() == {"A.SP"}


def test_unknown_kind_is_rejected_by_both_parsers() -> None:
    """A kind other than setpoint or pid_param fails in both functions."""
    doc = _doc(**{"A.SP": {**SETPOINT, "kind": "other"}})
    for fn in (policy_from_dict, params_from_dict):
        with pytest.raises(PolicyError, match="kind"):
            fn(doc)
    for bad in (1, None, ["pid_param"]):
        with pytest.raises(PolicyError):
            params_from_dict(_doc(**{"A.SP": {**SETPOINT, "kind": bad}}))


def test_policies_from_dict_returns_both() -> None:
    """policies_from_dict splits one document into setpoint and parameter policies."""
    sp, pp = policies_from_dict(_doc(**{"A.SP": SETPOINT, "A.KP": GAIN}))
    assert set(sp) == {"A.SP"}
    assert pp["A.KP"].param == "gain"
    assert pp["A.KP"].limits == (0.1, 10.0)
    assert pp["A.KP"].max_ratio == 2.0
    assert pp["A.KP"].allowed_loop_modes == ("AUTO",)


def test_setpoint_extra_pid_key_still_rejected() -> None:
    """A setpoint target with a pid_param key is an unknown field."""
    with pytest.raises(PolicyError, match="unknown field"):
        policy_from_dict(_doc(**{"A.SP": {**SETPOINT, "max_ratio": 2.0}}))


@pytest.mark.parametrize(
    "patch",
    [
        {"x": 1}, {"param": "kc"}, {"param": 3}, {"max_ratio": 1.0}, {"max_ratio": 0.9},
        {"max_ratio": True}, {"max_ratio": float("nan")}, {"max_ratio": float("inf")},
        {"max_ratio": 10**400}, {"limits": [10.0, 1.0]}, {"limits": [0.0, 10.0]},
        {"limits": [-1.0, 10.0]}, {"limits": [float("nan"), 10.0]}, {"limits": [0.1, math.inf]},
        {"limits": [True, 10.0]}, {"limits": "ab"}, {"limits": [1.0]},
        {"readback_tolerance": -1.0}, {"readback_tolerance": "0"},
        {"min_interval_s": -1.0}, {"min_interval_s": math.nan},
        {"allowed_loop_modes": []}, {"allowed_loop_modes": ["AUTO", "AUTO"]},
        {"allowed_loop_modes": "AUTO"}, {"unit": ""}, {"unit": " s"}, {"unit": 1},
        {"unit": "s\n"}, {"unit": "x" * 65}, {"loop": ""}, {"loop": "FIC 101"},
        {"loop": "FIC１01"}, {"vendor_form": "siemensа"}, {"vendor_form": 5},
    ],
)
def test_params_from_dict_rejects_bad_values(patch: dict[str, Any]) -> None:
    """Every malformed field of a pid_param target raises PolicyError."""
    with pytest.raises(PolicyError):
        params_from_dict(_doc(**{"A.KP": {**GAIN, **patch}}))


@pytest.mark.parametrize("field", [f for f in GAIN if f != "kind"])
def test_params_from_dict_rejects_missing_field(field: str) -> None:
    """Every pid_param field is required."""
    target = {k: v for k, v in GAIN.items() if k != field}
    with pytest.raises(PolicyError, match="missing"):
        params_from_dict(_doc(**{"A.KP": target}))


def test_params_from_dict_td_tf_zero_lower_limit_ok_ti_not() -> None:
    """Td and Tf may have lower limit 0; gain and Ti may not."""
    for param in ("td", "tf"):
        assert params_from_dict(_doc(A={**GAIN, "param": param, "limits": [0.0, 5.0]}))
    for param in ("gain", "ti"):
        with pytest.raises(PolicyError):
            params_from_dict(_doc(A={**GAIN, "param": param, "limits": [0.0, 5.0]}))
    with pytest.raises(PolicyError):
        params_from_dict(_doc(A={**GAIN, "param": "td", "limits": [-0.5, 5.0]}))


def test_params_from_dict_rejects_duplicate_loop_param() -> None:
    """Two targets for the same (loop, param) are refused; different loops are fine."""
    with pytest.raises(PolicyError, match="both define"):
        params_from_dict(_doc(A=GAIN, B=GAIN))
    assert len(params_from_dict(_doc(A=GAIN, B={**GAIN, "loop": "FIC102"}))) == 2


@pytest.mark.parametrize("tag", ["FICА101.KP", "FIC１.KP", "FIC 1", "", "x" * 129, "Tаg"])
def test_unicode_and_malformed_tags_rejected(tag: str) -> None:
    """Tag lookalikes (Cyrillic, fullwidth) and bad lengths fail the existing tag pattern."""
    with pytest.raises(PolicyError):
        params_from_dict(_doc(**{tag: GAIN}))
    with pytest.raises(PolicyError):
        policies_from_dict(_doc(**{tag: GAIN}))


def test_non_dict_inputs_rejected() -> None:
    """Non-dict documents and targets raise PolicyError."""
    with pytest.raises(PolicyError):
        params_from_dict([])  # type: ignore[arg-type]
    with pytest.raises(PolicyError):
        params_from_dict({"targets": []})
    with pytest.raises(PolicyError):
        params_from_dict(_doc(A=GAIN) | {"targets": {"A": 5}})


# --- check_param_items -----------------------------------------------------------------------


def test_check_accepts_valid_item() -> None:
    """A change inside limits and ratio with matching unit and form passes."""
    assert _check(_item()) == []
    assert _check(_item(to_value=2.0)) == []
    assert _check(_item(to_value=0.5)) == []


def test_check_out_of_limits_is_refused_not_clamped() -> None:
    """Above or below the limits: out_of_limits, in a list (no value is returned)."""
    assert "out_of_limits" in _check(_item(to_value=10.5), current=9.0)
    assert "out_of_limits" in _check(_item(to_value=0.05), current=0.1)
    assert _check(_item(to_value=10.0), current=9.0) == []


def test_check_ratio_exceeded_both_directions_and_boundary() -> None:
    """new/current outside [1/r, r] is refused; exactly r and 1/r pass."""
    assert _check(_item(to_value=2.1)) == ["ratio_exceeded"]
    assert _check(_item(to_value=0.4)) == ["ratio_exceeded"]
    assert _check(_item(to_value=2.0)) == []
    assert _check(_item(to_value=0.5)) == []


def test_check_ratio_with_non_positive_current() -> None:
    """A zero or negative live value cannot define a ratio; any change is refused."""
    td = _item(param="td", target="FIC101.TD", unit="s", to_value=10.0)
    assert "ratio_exceeded" in _check(td, current=0.0)
    assert _check(_item(param="td", target="FIC101.TD", unit="s", to_value=0.0), 0.0) == []
    assert "ratio_exceeded" in _check(_item(to_value=1.0), current=-1.0)


def test_check_unit_and_form_mismatch() -> None:
    """A different unit or vendor form is refused; lookalike characters do not match."""
    assert _check(_item(unit="s")) == ["unit_mismatch"]
    assert _check(_item(unit="1 ")) == ["unit_mismatch"]
    assert _check(_item(vendor_form="abb_pidcc")) == ["form_mismatch"]
    assert _check(_item(vendor_form="siemens_pid_cоmpact")) == ["form_mismatch"]


def test_check_param_mismatch_is_refused() -> None:
    """An item of another parameter than the target policy is refused."""
    assert "param_mismatch" in _check(_item(param="ti"))


def test_check_nonpositive_gain_ti_and_negative_td() -> None:
    """The code-fixed sign rules hold even if the policy limits were wrong."""
    pol = _policies()
    wide = {
        "FIC101.KP": ParamPolicy("L", "gain", "1", "f", (-10.0, 10.0), 1e9, 0.0, 0.0, ("AUTO",)),
        "FIC101.TI": ParamPolicy("L", "ti", "s", "f", (-10.0, 10.0), 1e9, 0.0, 0.0, ("AUTO",)),
        "FIC101.TD": ParamPolicy("L", "td", "s", "f", (-10.0, 10.0), 1e9, 0.0, 0.0, ("AUTO",)),
    }
    assert pol
    for tag, param, unit, code in (
        ("FIC101.KP", "gain", "1", "nonpositive_gain"),
        ("FIC101.TI", "ti", "s", "nonpositive_ti"),
        ("FIC101.TD", "td", "s", "negative_td"),
    ):
        it = ParamItem(param, tag, unit, "f", 1.0, -1.0)
        assert code in check_param_items(wide, [it], {tag: 1.0})
    zero = ParamItem("gain", "FIC101.KP", "1", "f", 1.0, 0.0)
    assert "nonpositive_gain" in check_param_items(wide, [zero], {"FIC101.KP": 1.0})
    zero_ti = ParamItem("ti", "FIC101.TI", "s", "f", 1.0, 0.0)
    assert "nonpositive_ti" in check_param_items(wide, [zero_ti], {"FIC101.TI": 1.0})
    zero_td = ParamItem("td", "FIC101.TD", "s", "f", 1.0, 0.0)
    assert "negative_td" not in check_param_items(wide, [zero_td], {"FIC101.TD": 1.0})


def test_check_negative_td_in_real_policy() -> None:
    """With real limits a negative Td is out of limits and negative_td."""
    it = _item(param="td", target="FIC101.TD", unit="s", to_value=-1.0)
    codes = _check(it, current=1.0)
    assert "negative_td" in codes
    assert "out_of_limits" in codes


@pytest.mark.parametrize(
    "bad", [math.nan, math.inf, -math.inf, True, False, None, "1.0", 10**400, [1.0]]
)
def test_check_bad_proposed_value(bad: Any) -> None:
    """NaN, inf, bool, text, None and integers beyond float range give bad_value only."""
    assert _check(_item(to_value=bad)) == ["bad_value"]


@pytest.mark.parametrize("bad", [math.nan, math.inf, True, None, "1", 10**400])
def test_check_bad_live_value(bad: Any) -> None:
    """A non-finite or non-numeric live reading refuses the set."""
    assert _check(_item(), current=bad) == ["bad_value"]


def test_check_missing_live_value_and_missing_policy() -> None:
    """No live reading is bad_value; an unknown target is no_policy; empty items no_items."""
    assert check_param_items(_policies(), [_item()], {}) == ["bad_value"]
    assert check_param_items(_policies(), [_item(target="OTHER.KP")], {"OTHER.KP": 1.0}) == [
        "no_policy"
    ]
    assert check_param_items(_policies(), [], {}) == ["no_items"]


def test_check_unicode_target_lookalike_has_no_policy() -> None:
    """A target tag with a Cyrillic lookalike does not find the ASCII policy."""
    tag = "FIC101.KР"
    assert check_param_items(_policies(), [_item(target=tag)], {tag: 1.0}) == ["no_policy"]


def test_check_collects_distinct_codes_over_items() -> None:
    """Codes of several items are merged without duplicates, in first-seen order."""
    items = [
        _item(to_value=20.0),
        _item(param="ti", target="FIC101.TI", unit="s", from_value=60.0, to_value=1000.0),
        _item(to_value=30.0),
    ]
    current = {"FIC101.KP": 1.0, "FIC101.TI": 60.0}
    codes = check_param_items(_policies(), items, current)
    assert codes == ["out_of_limits", "ratio_exceeded"]


def test_check_does_not_mutate_inputs_and_returns_no_value() -> None:
    """The check returns codes only; policies and items are unchanged (frozen)."""
    pols = _policies()
    before = dict(pols)
    check_param_items(pols, [_item(to_value=99.0)], {"FIC101.KP": 1.0})
    assert pols == before
    with pytest.raises(AttributeError):
        _item().to_value = 2.0  # type: ignore[misc]
