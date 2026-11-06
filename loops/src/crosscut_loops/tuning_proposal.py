"""Pure builder of tuning proposal records and their rollbacks (ADR 014, sections 1 and 6).

`build_proposal` turns a `TuningReport` (SIMC / AMIGO settings in seconds, kc in OUT per PV unit)
and the values read live from the DCS into a record of `schemas/tuning-proposal.schema.json`:
items in the unit of the vendor form, confidence level, caveats, expiry and a model-predicted
preview. `build_rollback` inverts an applied record. Every refusal is a `ProposalRefused` with a
code. No I/O, no network, no clock (time and id are injected), no gateway import: this module only
builds data; nothing here writes to a control system.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from crosscut_loops.tuning_preview import PidTerms, preview_record, step_metrics
from crosscut_loops.tuning_report import LOW_CONFIDENCE_PREFIX, TuningReport
from crosscut_loops.tuning_rules import ConversionForm, FopdtModel
from crosscut_loops.vendor_forms import DEFAULT_OUT_SPAN, VENDOR_FORMS, normalise_gain

Record = dict[str, Any]

RECORD_VERSION = 1
PARAMS = ("gain", "ti", "td", "tf")  # item order in a record
SIMC, AMIGO, AMIGO_PID = "simc", "amigo", "amigo_pid"
DEFAULT_TTL = timedelta(hours=8)
MAX_TTL = timedelta(hours=12)  # hard cap of ADR 014 section 1
STALE_WINDOW = timedelta(hours=24)  # older data lowers the confidence
NO_OP_REL_TOL = 1e-9  # |to - from| below this share of the larger value is no change
SECONDS_PER_MINUTE = 60.0
PERCENT = 100.0
NORMALISED_GAIN_KEYS = frozenset({"abb_pidcc"})  # Gain entered normalised (vendor_forms docs)
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class ProposalRefused(Exception):
    """A proposal that must not be created; `code` is a short machine-readable reason."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Stamp:
    """Who, when and under which id a record is created (all injected by the caller).

    Attributes:
        proposal_id: Lower-case UUID string of the new record.
        created_by: User name of the proposer.
        now: Creation time, timezone-aware.
        ttl: Lifetime until `expires_at`; at most 12 h (ValueError above), 8 h by default.
    """

    proposal_id: str
    created_by: str
    now: datetime
    ttl: timedelta = DEFAULT_TTL

    def __post_init__(self) -> None:
        """Reject a malformed id, an empty user, a naive time and a lifetime outside (0, 12 h]."""
        if str(uuid.UUID(self.proposal_id)) != self.proposal_id:
            raise ValueError("proposal_id must be a lower-case UUID")
        if not self.created_by or len(self.created_by) > 128:
            raise ValueError("created_by must be 1..128 characters")
        if self.now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if self.ttl <= timedelta(0) or self.ttl > MAX_TTL:
            raise ValueError(f"ttl must be in (0, {MAX_TTL}]")

    @property
    def created_at(self) -> str:
        """Creation time as UTC timestamp with a trailing Z."""
        return _utc_text(self.now)

    @property
    def expires_at(self) -> str:
        """Expiry time (created + ttl) as UTC timestamp with a trailing Z."""
        return _utc_text(self.now + self.ttl)


@dataclass(frozen=True)
class WindowSpec:
    """Data window the report was made from; `dataset_id` None means the history store."""

    start: datetime
    end: datetime
    dataset_id: str | None = None


@dataclass(frozen=True)
class Scaling:
    """Spans to normalise the ABB PidCC gain: PV span in PV units, OUT span in OUT units."""

    pv_span: float | None = None
    out_span: float = DEFAULT_OUT_SPAN


@dataclass(frozen=True)
class ProposalRequest:
    """What to propose for which loop.

    Attributes:
        loop_id: Loop identifier.
        vendor_form_key: Key of `VENDOR_FORMS`.
        method: "simc" (PI), "amigo" (PI) or "amigo_pid" (PID with filter).
        targets: Policy target tag per parameter ("gain", "ti", "td", "tf"); gain and ti are
            required, td too for "amigo_pid", tf is optional (no tf item without a target).
        window: Data window of the report.
        step_test_id: Optional Steps-view test that confirms the model.
        scaling: Spans for the normalised ABB gain.
    """

    loop_id: str
    vendor_form_key: str
    method: str
    targets: Mapping[str, str]
    window: WindowSpec
    step_test_id: str | None = None
    scaling: Scaling = field(default_factory=Scaling)


@dataclass(frozen=True)
class Conv:
    """Conversion between seconds / kc (output per PV unit) and the unit of one vendor form.

    `factor` scales kc to the DCS gain (1 for raw, pv_span / out_span for a normalised gain).
    """

    form: ConversionForm
    factor: float
    normalised: bool

    def to_dcs(self, param: str, si: float) -> float:
        """Return the value of `param` in the vendor unit; `si` is kc or seconds (kc > 0)."""
        if param == "gain":
            kc = si * self.factor
            return PERCENT / kc if self.form == "proportional_band_minutes" else kc
        if self.form == "gain_seconds":
            return si
        if param == "ti" and self.form == "gain_repeats_per_minute":
            return SECONDS_PER_MINUTE / si
        return si / SECONDS_PER_MINUTE

    def from_dcs(self, param: str, value: float) -> float:
        """Inverse of `to_dcs`: the value in kc or seconds; `value` must be valid (> 0 for gain)."""
        if param == "gain":
            kc = PERCENT / value if self.form == "proportional_band_minutes" else value
            return kc / self.factor
        if self.form == "gain_seconds":
            return value
        if param == "ti" and self.form == "gain_repeats_per_minute":
            return SECONDS_PER_MINUTE / value
        return value * SECONDS_PER_MINUTE

    def unit(self, param: str) -> str:
        """Return the unit text of `param` in this form."""
        if param == "gain":
            if self.form == "proportional_band_minutes":
                return "%"
            return "normalised" if self.normalised else "OUT/PV"
        if self.form == "gain_seconds":
            return "s"
        if param == "ti" and self.form == "gain_repeats_per_minute":
            return "repeats/min"
        return "min"


# Fields of a record that is not yet sent to the gateway.
_UNSENT: Record = {"status": "draft", "gateway_key": None, "applied": None, "review": None}


def _envelope(stamp: Stamp, loop_id: str) -> Record:
    """The identity fields of a new record: id, version, loop, proposer, creation and expiry."""
    return {
        "id": stamp.proposal_id,
        "version": RECORD_VERSION,
        "loop_id": loop_id,
        "created_by": stamp.created_by,
        "created_at": stamp.created_at,
        "expires_at": stamp.expires_at,
    }


def _utc_text(moment: datetime) -> str:
    """Format a timezone-aware time as UTC with a trailing Z."""
    return moment.astimezone(UTC).strftime(TIMESTAMP_FORMAT)


def _canonical(obj: object) -> str:
    """Canonical JSON: sorted keys, no spaces, ASCII."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _sha256(obj: object) -> str:
    """Hex SHA-256 of the canonical JSON of `obj`."""
    return hashlib.sha256(_canonical(obj).encode("ascii")).hexdigest()


def proposal_digest(record: Mapping[str, Any]) -> str:
    """Return the SHA-256 (hex) of the canonical JSON of the loop id and the items, for display.

    Equal digests mean equal loop, targets, units and from/to values; id, times and the
    preview do not change it.
    """
    return _sha256({"loop_id": record["loop_id"], "items": record["items"]})


def _check_value(param: str, value: float, code: str) -> None:
    """Refuse a non-finite value, gain <= 0, ti <= 0, td < 0 or tf < 0 (ADR 014 item checks)."""
    bad = not math.isfinite(value)
    if param in ("gain", "ti"):
        bad = bad or value <= 0.0
    else:
        bad = bad or value < 0.0
    if bad:
        raise ProposalRefused(code, f"{param} = {value}")


def _is_noop(old: float, new: float) -> bool:
    """True when `new` differs from `old` by less than 1e-9 of the larger magnitude."""
    return abs(new - old) <= NO_OP_REL_TOL * max(abs(old), abs(new))


def _conv_for(key: str, scaling: Scaling) -> Conv:
    """Return the conversion of vendor form `key`; refuse an unknown key or a missing range."""
    if key not in VENDOR_FORMS:
        raise ProposalRefused("unknown_vendor_form", key)
    normalised = key in NORMALISED_GAIN_KEYS
    factor = 1.0
    if normalised:
        if scaling.pv_span is None or scaling.pv_span <= 0.0 or scaling.out_span <= 0.0:
            raise ProposalRefused("missing_range", "PV and OUT span are needed for " + key)
        factor = normalise_gain(1.0, scaling.pv_span, scaling.out_span)
    return Conv(VENDOR_FORMS[key].form, factor, normalised)


def _settings_si(report: TuningReport, method: str) -> dict[str, float]:
    """Return the report's settings of `method` in kc / seconds, keyed by parameter."""
    if report.blocked_reason is not None:
        raise ProposalRefused("blocked", report.blocked_reason)
    if method not in (SIMC, AMIGO, AMIGO_PID):
        raise ProposalRefused("unsupported_method", method)
    if method == AMIGO_PID:
        return _pid_si(report)
    pi = report.amigo if method == AMIGO else report.simc
    if pi is None:
        raise ProposalRefused("no_settings", f"the report has no {method} settings")
    return {"gain": pi.kc, "ti": pi.ti_s}


def _pid_si(report: TuningReport) -> dict[str, float]:
    """AMIGO PID settings (ideal form) in kc / seconds; refuse a report without them."""
    pid = report.pid
    if pid is None:
        raise ProposalRefused("no_settings", "the report has no amigo_pid settings")
    return {"gain": pid.kc, "ti": pid.ti_s, "td": pid.td_s, "tf": pid.filter_time_s}


def _check_current(request: ProposalRequest, current: Mapping[str, float]) -> None:
    """Refuse missing targets, missing current values and invalid current values."""
    required = ("gain", "ti", "td") if request.method == AMIGO_PID else ("gain", "ti")
    for param in required:
        if param not in request.targets:
            raise ProposalRefused("missing_target", param)
        if param not in current:
            raise ProposalRefused("missing_current", param)
    for param in PARAMS:
        if param in current:
            _check_value(param, current[param], "invalid_current")


def _build_items(
    si: Mapping[str, float], request: ProposalRequest, current: Mapping[str, float], conv: Conv
) -> list[Record]:
    """Build the items in vendor units; refuse invalid values and no-op items."""
    items: list[Record] = []
    for param in PARAMS:
        if param not in si or param not in request.targets:
            continue
        if param not in current:
            raise ProposalRefused("missing_current", param)
        new = conv.to_dcs(param, si[param])
        _check_value(param, new, "invalid_value")
        if _is_noop(current[param], new):
            raise ProposalRefused("no_op", f"{param} would not change")
        items.append(_item(param, request.targets[param], conv.unit(param), (current[param], new)))
    return items


def _item(param: str, target: str, unit: str, change: tuple[float, float]) -> Record:
    """One record item; `change` = (from, to) in `unit`."""
    return {"param": param, "target": target, "unit": unit, "from": change[0], "to": change[1]}


def _terms(values: Mapping[str, float], conv: Conv) -> PidTerms:
    """PID terms in kc / seconds from vendor-unit values (td defaults to 0)."""
    td = conv.from_dcs("td", values["td"]) if "td" in values else 0.0
    return PidTerms(conv.from_dcs("gain", values["gain"]), conv.from_dcs("ti", values["ti"]), td)


def _preview(
    model: FopdtModel, current: Mapping[str, float], items: list[Record], conv: Conv
) -> Record:
    """Simulate current versus proposed; refuse a proposal that makes the model loop diverge."""
    proposed = {**current, **{item["param"]: item["to"] for item in items}}
    before = step_metrics(model, _terms(current, conv))
    after = step_metrics(model, _terms(proposed, conv))
    if after.diverged:
        raise ProposalRefused("preview_unstable", "the model predicts an unstable closed loop")
    return preview_record(before, after)


def _confidence(report: TuningReport, request: ProposalRequest, now: datetime) -> Record:
    """Level "low" for a vendor form not verified, a weak model fit or a window older than 24 h.

    The report has no numeric fit quality: a weak fit is the low-confidence note that
    `build_tuning_report` appends. Otherwise "high" with a step test referenced, else "medium".
    """
    reasons: list[str] = []
    evidence = VENDOR_FORMS[request.vendor_form_key].evidence
    if evidence != "verified":
        reasons.append(f"vendor form evidence is {evidence}, not verified")
    if any(note.startswith(LOW_CONFIDENCE_PREFIX) for note in report.notes):
        reasons.append("model fit is weak (low-confidence note in the report)")
    if now - request.window.end > STALE_WINDOW:
        reasons.append("data window is older than 24 h")
    if reasons:
        return {"level": "low", "reasons": reasons}
    if request.step_test_id is not None:
        return {"level": "high", "reasons": ["verified form, sound fit, fresh window, step test"]}
    return {"level": "medium", "reasons": ["no step test referenced"]}


def _window_block(window: WindowSpec) -> Record:
    """The `source.window` block."""
    block: Record = {"start": _utc_text(window.start), "end": _utc_text(window.end)}
    if window.dataset_id is None:
        block["history"] = True
    else:
        block["dataset_id"] = window.dataset_id
    return block


def _source(report: TuningReport, request: ProposalRequest) -> Record:
    """The `source` block: method, robustness, model, window, digest of the report."""
    model = _model_of(report)
    source: Record = {
        "method": request.method,
        "robustness": report.robustness,
        "model": {
            "K": model.gain,
            "tau_s": model.time_constant_s,
            "theta_s": model.delay_s,
            "process_kind": "self_regulating",  # IPDT reports are not supported here
        },
        "window": _window_block(request.window),
        "report_digest": _sha256(asdict(report)),
    }
    if request.step_test_id is not None:
        source["step_test_id"] = request.step_test_id
    return source


def build_proposal(
    report: TuningReport,
    request: ProposalRequest,
    current_values: Mapping[str, float],
    stamp: Stamp,
) -> Record:
    """Build a proposal record (status "draft") that validates against the repo schema.

    Args:
        report: Tuning report of the loop (FOPDT model, SIMC / AMIGO settings in kc / seconds).
        request: Loop, vendor form, method, target tags, window (see `ProposalRequest`).
        current_values: Values read live from the DCS, in the unit of the vendor form, keyed by
            parameter ("gain", "ti", ...); they become the `from` of the items.
        stamp: Id, proposer, creation time and lifetime.

    Raises:
        ProposalRefused: blocked report, no settings, unknown form or method, missing target,
            missing or invalid current value, invalid or no-op item, unstable preview.
        ValueError: a lifetime above 12 h (raised when the `Stamp` is made).
    """
    si = _settings_si(report, request.method)
    conv = _conv_for(request.vendor_form_key, request.scaling)
    _check_current(request, current_values)
    items = _build_items(si, request, current_values, conv)
    spec = VENDOR_FORMS[request.vendor_form_key]
    return {
        **_envelope(stamp, request.loop_id),
        "vendor_form": {"key": spec.key, "evidence": spec.evidence},
        "source": _source(report, request),
        "confidence": _confidence(report, request, stamp.now),
        "caveats": list(spec.caveats),
        "items": items,
        "preview": _preview(_model_of(report), current_values, items, conv),
        "rollback_of": None,
        **_UNSENT,
    }


def _model_of(report: TuningReport) -> FopdtModel:
    """Return the FOPDT model of the report; refuse a report without one."""
    if report.model is None:
        raise ProposalRefused("no_model", "the report has no identified model")
    return report.model


def _swapped_preview(preview: Mapping[str, Any]) -> Record:
    """The preview of the reverse change: current and proposed swapped, IAE ratio inverted."""
    ratio = preview["iae_ratio"]
    if not ratio > 0.0:
        raise ProposalRefused("invalid_preview", "the original IAE ratio is not positive")
    swapped: Record = {"label": preview["label"], "iae_ratio": 1.0 / ratio}
    for key in ("overshoot_pct", "settling_time_s", "ms"):
        swapped[key] = {"current": preview[key]["proposed"], "proposed": preview[key]["current"]}
    return swapped


def _rollback_items(original: Mapping[str, Any]) -> list[Record]:
    """Items that put the audited `from_read` back: from = to_read, to = from_read."""
    applied = original["applied"]
    items: list[Record] = []
    for item in original["items"]:
        target = item["target"]
        if target not in applied["from_read"] or target not in applied["to_read"]:
            raise ProposalRefused("missing_read", f"no audited read for {target}")
        old, new = applied["to_read"][target], applied["from_read"][target]
        _check_value(item["param"], new, "invalid_value")
        if _is_noop(old, new):
            raise ProposalRefused("no_op", f"{item['param']} would not change")
        items.append(_item(item["param"], target, item["unit"], (old, new)))
    return items


def build_rollback(applied_record: Mapping[str, Any], stamp: Stamp) -> Record:
    """Build the rollback record of an applied proposal (ADR 014 section 6), status "draft".

    method "rollback", `rollback_of` = id of the original, `to` = the original's
    `applied.from_read` and `from` = its `applied.to_read`, per target, in the item units. Source
    (model, window, digest), vendor form and caveats are copied; the preview is the original's
    with current and proposed swapped. The gateway still decides about `from_mismatch`.

    Raises:
        ProposalRefused: the original has no `applied` block ("not_applied"), a target has no
            audited read, a value is invalid or the rollback would change nothing.
    """
    if applied_record.get("applied") is None:
        raise ProposalRefused("not_applied", "the proposal has no applied block")
    source = copy.deepcopy(applied_record["source"])
    source["method"] = "rollback"
    return {
        **_envelope(stamp, applied_record["loop_id"]),
        "vendor_form": copy.deepcopy(applied_record["vendor_form"]),
        "source": source,
        "confidence": {
            "level": "medium",
            "reasons": ["rollback to the values read before the applied change"],
        },
        "caveats": list(applied_record["caveats"]),
        "items": _rollback_items(applied_record),
        "preview": _swapped_preview(applied_record["preview"]),
        "rollback_of": applied_record["id"],
        **_UNSENT,
    }
