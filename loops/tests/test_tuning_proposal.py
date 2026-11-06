"""
Tests for tuning_proposal and tuning_preview: schema validity, refusals, unit conversion,
determinism, confidence rules, rollback inversion and the model-prediction preview.
Everything is synthetic (FOPDT K=2, tau=100 s, theta=10 s); time and id are injected.
"""

import copy
import dataclasses
import json
import math
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from crosscut_loops.tuning_preview import PidTerms, step_metrics
from crosscut_loops.tuning_proposal import (
    Conv,
    ProposalRefused,
    ProposalRequest,
    Scaling,
    Stamp,
    WindowSpec,
    build_proposal,
    build_rollback,
    proposal_digest,
)
from crosscut_loops.tuning_report import LOW_CONFIDENCE_PREFIX, TuningReport, report_from_model
from crosscut_loops.tuning_rules import FopdtModel, PiSettings

jsonschema = pytest.importorskip("jsonschema")

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "tuning-proposal.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
MODEL = FopdtModel(gain=2.0, time_constant_s=100.0, delay_s=10.0)
NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)
ID_A = "11111111-2222-4333-8444-555555555555"
ID_B = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
TARGETS = {"gain": "FIC101.Gain", "ti": "FIC101.Ti", "td": "FIC101.Td", "tf": "FIC101.Tf"}
SLOW = {"gain": 0.2, "ti": 400.0, "td": 0.0}  # a clearly detuned loop as read from the DCS
FRESH = WindowSpec(NOW - timedelta(hours=2), NOW - timedelta(hours=1))


def make_report(robustness: float = 0.5) -> TuningReport:
    """Report for the synthetic model: SIMC kc 1.25, ti 100 s at robustness 0.5."""
    return report_from_model("FIC101", MODEL, robustness)


def make_request(**changes: object) -> ProposalRequest:
    """Siemens SIMC request on a fresh history window."""
    base = ProposalRequest("FIC101", "siemens_pid_compact", "simc", TARGETS, FRESH)
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def make_stamp(**changes: object) -> Stamp:
    """Stamp with the injected id and time."""
    base = Stamp(ID_A, "alice", NOW)
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def propose(current: dict[str, float] | None = None, **request_changes: object) -> dict:
    """Build a Siemens SIMC proposal against a detuned loop."""
    return build_proposal(
        make_report(), make_request(**request_changes), current or SLOW, make_stamp()
    )


def assert_valid(record: dict) -> None:
    """The record validates against the repo schema and survives strict JSON."""
    jsonschema.Draft202012Validator(SCHEMA).validate(record)
    json.dumps(record, allow_nan=False)


def refusal_code(call: object) -> str:
    """Run `call` and return the code of the ProposalRefused it raises."""
    with pytest.raises(ProposalRefused) as caught:
        call()  # type: ignore[operator]
    return caught.value.code


# --- schema validity -------------------------------------------------------------------------


def test_pi_proposal_validates_and_has_expected_content() -> None:
    record = propose()
    assert_valid(record)
    assert [i["param"] for i in record["items"]] == ["gain", "ti"]
    gain, ti = record["items"]
    assert (gain["from"], gain["to"], gain["target"]) == (0.2, pytest.approx(1.25), "FIC101.Gain")
    assert (ti["from"], ti["to"], ti["unit"]) == (400.0, pytest.approx(100.0), "s")
    assert record["status"] == "draft" and record["rollback_of"] is None
    assert record["source"]["window"]["history"] is True
    assert record["source"]["model"]["process_kind"] == "self_regulating"
    assert record["vendor_form"] == {"key": "siemens_pid_compact", "evidence": "verified"}


def test_pid_proposal_has_four_items_and_dataset_window() -> None:
    current = {"gain": 0.5, "ti": 200.0, "td": 1.0, "tf": 0.5}
    window = WindowSpec(NOW - timedelta(hours=3), NOW - timedelta(hours=2), "ds-1")
    request = make_request(method="amigo_pid", window=window, step_test_id="st-7")
    record = build_proposal(make_report(), request, current, make_stamp())
    assert_valid(record)
    assert [i["param"] for i in record["items"]] == ["gain", "ti", "td", "tf"]
    assert record["source"]["window"]["dataset_id"] == "ds-1"
    assert "history" not in record["source"]["window"]
    assert record["source"]["step_test_id"] == "st-7"


def test_abb_proposal_normalises_gain_and_is_low_confidence() -> None:
    request = make_request(vendor_form_key="abb_pidcc", scaling=Scaling(pv_span=200.0))
    record = build_proposal(make_report(), request, {"gain": 0.5, "ti": 400.0}, make_stamp())
    assert_valid(record)
    assert record["items"][0]["to"] == pytest.approx(1.25 * 200.0 / 100.0)
    assert record["items"][0]["unit"] == "normalised"
    assert record["confidence"]["level"] == "low"


def test_caveats_are_copied_from_the_vendor_form() -> None:
    from crosscut_loops.vendor_forms import VENDOR_FORMS

    assert propose()["caveats"] == list(VENDOR_FORMS["siemens_pid_compact"].caveats)


def test_expiry_is_eight_hours_by_default_and_ttl_is_capped() -> None:
    record = propose()
    assert record["created_at"] == "2026-11-06T12:00:00Z"
    assert record["expires_at"] == "2026-11-06T20:00:00Z"
    assert Stamp(ID_A, "alice", NOW, timedelta(hours=12)).expires_at == "2026-11-07T00:00:00Z"
    with pytest.raises(ValueError):
        Stamp(ID_A, "alice", NOW, timedelta(hours=12, seconds=1))
    with pytest.raises(ValueError):
        Stamp(ID_A, "alice", NOW, timedelta(0))


def test_stamp_rejects_naive_time_bad_id_and_empty_user() -> None:
    with pytest.raises(ValueError):
        Stamp(ID_A, "alice", datetime(2026, 11, 6, 12, 0))
    with pytest.raises(ValueError):
        Stamp("not-a-uuid", "alice", NOW)
    with pytest.raises(ValueError):
        Stamp(ID_A, "", NOW)


def test_non_utc_time_is_written_as_utc() -> None:
    plus_two = datetime(2026, 11, 6, 14, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert Stamp(ID_A, "alice", plus_two).created_at == "2026-11-06T12:00:00Z"


# --- refusals --------------------------------------------------------------------------------


def test_blocked_report_is_refused() -> None:
    report = dataclasses.replace(make_report(), blocked_reason="stiction suspected")
    code = refusal_code(lambda: build_proposal(report, make_request(), SLOW, make_stamp()))
    assert code == "blocked"


def test_report_without_settings_or_model_is_refused() -> None:
    bare = dataclasses.replace(make_report(), simc=None)
    assert refusal_code(lambda: build_proposal(bare, make_request(), SLOW, make_stamp())) == (
        "no_settings"
    )
    no_pid = dataclasses.replace(make_report(), pid=None)
    request = make_request(method="amigo_pid")
    current = {**SLOW, "td": 0.0}
    assert refusal_code(lambda: build_proposal(no_pid, request, current, make_stamp())) == (
        "no_settings"
    )
    no_model = dataclasses.replace(make_report(), model=None)
    assert refusal_code(lambda: build_proposal(no_model, make_request(), SLOW, make_stamp())) == (
        "no_model"
    )


def test_missing_current_value_is_refused() -> None:
    assert refusal_code(lambda: propose({"gain": 0.2})) == "missing_current"


def test_pid_without_current_td_is_refused() -> None:
    request = make_request(method="amigo_pid")
    code = refusal_code(
        lambda: build_proposal(make_report(), request, {"gain": 0.2, "ti": 400.0}, make_stamp())
    )
    assert code == "missing_current"


def test_missing_target_is_refused() -> None:
    assert refusal_code(lambda: propose(targets={"gain": "FIC101.Gain"})) == "missing_target"


@pytest.mark.parametrize(
    "bad", [{"gain": 0.0, "ti": 400.0}, {"gain": 0.2, "ti": -1.0}, {"gain": math.nan, "ti": 1.0}]
)
def test_invalid_current_values_are_refused(bad: dict[str, float]) -> None:
    assert refusal_code(lambda: propose(bad)) == "invalid_current"


def test_negative_current_td_is_refused() -> None:
    assert refusal_code(lambda: propose({**SLOW, "td": -1.0})) == "invalid_current"


def test_non_finite_proposed_value_is_refused() -> None:
    report = dataclasses.replace(make_report(), simc=PiSettings(kc=math.inf, ti_s=100.0))
    code = refusal_code(lambda: build_proposal(report, make_request(), SLOW, make_stamp()))
    assert code == "invalid_value"


def test_no_op_item_is_refused() -> None:
    same = {"gain": 1.25, "ti": 100.0 * (1.0 + 1e-12)}
    assert refusal_code(lambda: propose(same)) == "no_op"


def test_small_but_real_change_is_not_a_no_op() -> None:
    assert_valid(propose({"gain": 1.25 * (1.0 + 1e-6), "ti": 400.0}))


def test_unknown_form_method_and_missing_range_are_refused() -> None:
    assert refusal_code(lambda: propose(vendor_form_key="nope")) == "unknown_vendor_form"
    assert refusal_code(lambda: propose(method="manual")) == "unsupported_method"
    assert refusal_code(lambda: propose(vendor_form_key="abb_pidcc")) == "missing_range"


def test_unstable_model_prediction_is_refused() -> None:
    report = dataclasses.replace(make_report(), simc=PiSettings(kc=30.0, ti_s=5.0))
    code = refusal_code(lambda: build_proposal(report, make_request(), SLOW, make_stamp()))
    assert code == "preview_unstable"


# --- unit conversion -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("form", "normalised", "gain", "ti", "td"),
    [
        ("gain_seconds", False, 2.0, 120.0, 30.0),
        ("gain_minutes", False, 2.0, 2.0, 0.5),
        ("proportional_band_minutes", False, 50.0, 2.0, 0.5),
        ("gain_repeats_per_minute", False, 2.0, 0.5, 0.5),
    ],
)
def test_conversion_values(form, normalised, gain, ti, td) -> None:  # type: ignore[no-untyped-def]
    conv = Conv(form, 1.0, normalised)
    assert conv.to_dcs("gain", 2.0) == pytest.approx(gain)
    assert conv.to_dcs("ti", 120.0) == pytest.approx(ti)
    assert conv.to_dcs("td", 30.0) == pytest.approx(td)
    assert conv.to_dcs("tf", 30.0) == pytest.approx(td)


@pytest.mark.parametrize(
    "form",
    ["gain_seconds", "gain_minutes", "proportional_band_minutes", "gain_repeats_per_minute"],
)
@pytest.mark.parametrize("param", ["gain", "ti", "td", "tf"])
def test_conversion_round_trip(form, param) -> None:  # type: ignore[no-untyped-def]
    conv = Conv(form, 2.0, True)
    assert conv.from_dcs(param, conv.to_dcs(param, 37.0)) == pytest.approx(37.0)


def test_units_per_form() -> None:
    assert Conv("gain_seconds", 1.0, False).unit("gain") == "OUT/PV"
    assert Conv("gain_seconds", 2.0, True).unit("gain") == "normalised"
    assert Conv("gain_seconds", 1.0, False).unit("ti") == "s"
    assert Conv("gain_minutes", 1.0, False).unit("td") == "min"
    assert Conv("proportional_band_minutes", 1.0, False).unit("gain") == "%"
    assert Conv("gain_repeats_per_minute", 1.0, False).unit("ti") == "repeats/min"
    assert Conv("gain_repeats_per_minute", 1.0, False).unit("td") == "min"


# --- determinism, digest ---------------------------------------------------------------------


def test_same_input_gives_identical_records() -> None:
    assert propose() == propose()
    first = json.dumps(propose(), sort_keys=True)
    assert first == json.dumps(propose(), sort_keys=True)


def test_only_id_and_time_differ_with_other_stamp() -> None:
    other = build_proposal(
        make_report(), make_request(), SLOW, Stamp(ID_B, "alice", NOW + timedelta(minutes=5))
    )
    base = propose()
    differing = {k for k in base if base[k] != other[k]}
    assert differing == {"id", "created_at", "expires_at"}


def test_digest_depends_on_loop_and_items_only() -> None:
    base = propose()
    other = build_proposal(make_report(), make_request(), SLOW, make_stamp(proposal_id=ID_B))
    assert proposal_digest(base) == proposal_digest(other)
    assert len(proposal_digest(base)) == 64
    changed = copy.deepcopy(base)
    changed["items"][0]["to"] += 0.1
    assert proposal_digest(changed) != proposal_digest(base)
    renamed = {**base, "loop_id": "FIC102"}
    assert proposal_digest(renamed) != proposal_digest(base)


def test_report_digest_changes_with_the_report() -> None:
    other = build_proposal(make_report(0.9), make_request(), SLOW, make_stamp())
    assert other["source"]["report_digest"] != propose()["source"]["report_digest"]


# --- confidence ------------------------------------------------------------------------------


def test_verified_fresh_sound_fit_is_medium_or_high_with_step_test() -> None:
    assert propose()["confidence"]["level"] == "medium"
    assert propose(step_test_id="st-1")["confidence"]["level"] == "high"


def test_unverified_evidence_is_low() -> None:
    confidence = propose(vendor_form_key="abb_pidcc", scaling=Scaling(100.0))["confidence"]
    assert confidence["level"] == "low"
    assert any("partly_verified" in reason for reason in confidence["reasons"])


def test_old_window_is_low() -> None:
    old = WindowSpec(NOW - timedelta(hours=26), NOW - timedelta(hours=25))
    confidence = propose(window=old)["confidence"]
    assert confidence["level"] == "low"
    assert any("24 h" in reason for reason in confidence["reasons"])
    edge = WindowSpec(NOW - timedelta(hours=25), NOW - timedelta(hours=24))
    assert propose(window=edge)["confidence"]["level"] == "medium"


def test_weak_fit_note_is_low() -> None:
    report = make_report()
    report.notes.append(LOW_CONFIDENCE_PREFIX + "single input step")
    record = build_proposal(report, make_request(), SLOW, make_stamp())
    assert record["confidence"]["level"] == "low"
    assert any("fit" in reason for reason in record["confidence"]["reasons"])


# --- preview ---------------------------------------------------------------------------------


def test_preview_is_labelled_and_better_for_a_detuned_loop() -> None:
    preview = propose()["preview"]
    assert preview["label"] == "model prediction"
    assert preview["iae_ratio"] < 0.1
    assert preview["settling_time_s"]["current"] is None  # 400 s integral time: never settles
    assert preview["settling_time_s"]["proposed"] == pytest.approx(121.6, abs=3.0)
    assert preview["ms"]["proposed"] > preview["ms"]["current"]


def test_preview_is_worse_when_the_proposal_is_slower_than_the_current_tuning() -> None:
    current = {"gain": 1.25, "ti": 110.0}
    record = build_proposal(make_report(1.0), make_request(), current, make_stamp())
    assert record["preview"]["iae_ratio"] > 1.0


def test_step_metrics_match_the_pole_cancelling_simc_tuning() -> None:
    metrics = step_metrics(MODEL, PidTerms(1.25, 100.0))
    assert metrics.iae == pytest.approx(100.0 / (1.25 * 2.0), rel=0.01)  # IAE = Ti / (Kc K)
    assert metrics.overshoot_pct == pytest.approx(0.0, abs=1e-6)
    assert 1.0 < metrics.ms < 1.6 and not metrics.diverged


def test_step_metrics_see_overshoot_and_divergence() -> None:
    assert step_metrics(MODEL, PidTerms(3.0, 20.0)).overshoot_pct > 50.0
    assert step_metrics(MODEL, PidTerms(30.0, 5.0)).diverged


def test_derivative_term_changes_the_prediction() -> None:
    plain = step_metrics(MODEL, PidTerms(2.35, 42.0))
    derivative = step_metrics(MODEL, PidTerms(2.35, 42.0, 4.85))
    assert derivative.overshoot_pct != plain.overshoot_pct
    assert step_metrics(MODEL, PidTerms(2.35, 42.0, 4.85)) == derivative


# --- rollback --------------------------------------------------------------------------------


def applied_of(record: dict) -> dict:
    """The record as the API stores it after the gateway applied it."""
    applied = copy.deepcopy(record)
    applied["status"] = "applied"
    applied["applied"] = {
        "from_read": {"FIC101.Gain": 0.2, "FIC101.Ti": 400.0},
        "to_read": {"FIC101.Gain": 1.25, "FIC101.Ti": 100.0},
        "t": "2026-11-06T12:30:00Z",
        "approver": "bob",
    }
    return applied


def test_rollback_inverts_the_applied_values_and_validates() -> None:
    original = applied_of(propose())
    rollback = build_rollback(original, make_stamp(proposal_id=ID_B, created_by="carol"))
    assert_valid(rollback)
    assert rollback["source"]["method"] == "rollback"
    assert rollback["rollback_of"] == original["id"] and rollback["id"] == ID_B
    gain, ti = rollback["items"]
    assert (gain["from"], gain["to"], gain["target"]) == (1.25, 0.2, "FIC101.Gain")
    assert (ti["from"], ti["to"], ti["unit"]) == (100.0, 400.0, "s")
    assert rollback["caveats"] == original["caveats"]
    assert rollback["vendor_form"] == original["vendor_form"]
    assert rollback["source"]["model"] == original["source"]["model"]
    assert rollback["status"] == "draft" and rollback["applied"] is None


def test_rollback_uses_audited_reads_not_the_planned_values() -> None:
    original = applied_of(propose())
    original["applied"]["to_read"]["FIC101.Gain"] = 1.2  # the DCS rounded the written value
    rollback = build_rollback(original, make_stamp(proposal_id=ID_B))
    assert rollback["items"][0]["from"] == 1.2


def test_rollback_preview_is_the_swapped_original_preview() -> None:
    original = applied_of(propose())
    preview = build_rollback(original, make_stamp(proposal_id=ID_B))["preview"]
    assert preview["iae_ratio"] > 10.0  # going back to the detuned loop is much worse
    assert preview["iae_ratio"] == pytest.approx(1.0 / original["preview"]["iae_ratio"])
    assert preview["ms"]["current"] == original["preview"]["ms"]["proposed"]
    assert preview["label"] == "model prediction"


def test_rollback_without_applied_block_is_refused() -> None:
    assert refusal_code(lambda: build_rollback(propose(), make_stamp(proposal_id=ID_B))) == (
        "not_applied"
    )


def test_rollback_with_missing_read_invalid_value_or_no_change_is_refused() -> None:
    missing = applied_of(propose())
    del missing["applied"]["from_read"]["FIC101.Ti"]
    assert refusal_code(lambda: build_rollback(missing, make_stamp(proposal_id=ID_B))) == (
        "missing_read"
    )
    invalid = applied_of(propose())
    invalid["applied"]["from_read"]["FIC101.Gain"] = 0.0
    assert refusal_code(lambda: build_rollback(invalid, make_stamp(proposal_id=ID_B))) == (
        "invalid_value"
    )
    same = applied_of(propose())
    same["applied"]["from_read"] = dict(same["applied"]["to_read"])
    assert refusal_code(lambda: build_rollback(same, make_stamp(proposal_id=ID_B))) == "no_op"


def test_rollback_does_not_modify_the_original() -> None:
    original = applied_of(propose())
    snapshot = copy.deepcopy(original)
    build_rollback(original, make_stamp(proposal_id=ID_B))
    assert original == snapshot
