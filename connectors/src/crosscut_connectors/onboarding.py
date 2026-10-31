"""Module onboarding and dataset readiness evaluation (Phase 1, #39).

Verifies whether a recorded dataset and site mapping satisfy the structural
and numerical prerequisites for control loop monitoring, anomaly detection,
and soft sensor calibration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from crosscut_loops.overview import LoopTags
from crosscut_loops.readiness import (
    FAIL,
    WARN,
    ReadinessConfig,
    check_readiness,
)

VERDICT_OK = "ok"
VERDICT_WARNING = "warning"
VERDICT_NOT_READY = "not_ready"


@dataclass(frozen=True)
class ModuleVerdict:
    """Readiness verdict and actionable checklist for a single product module."""

    status: str  # "ok" | "warning" | "not_ready"
    reasons: list[str] = field(default_factory=list)
    items_checked: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert verdict to JSON-serializable dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class DatasetReadiness:
    """Overall and per-module readiness summary for a dataset."""

    dataset_id: str
    verdict: str  # "ok" | "warning" | "not_ready"
    modules: dict[str, ModuleVerdict]

    def to_dict(self) -> dict[str, Any]:
        """Convert readiness summary to JSON-serializable dictionary."""
        return {
            "dataset_id": self.dataset_id,
            "verdict": self.verdict,
            "modules": {k: v.to_dict() for k, v in self.modules.items()},
        }


def config_from_site(site_doc: dict[str, Any] | None) -> ReadinessConfig:
    """Extract ReadinessConfig from the site document's readiness block with defaults."""
    if not site_doc or "readiness" not in site_doc:
        return ReadinessConfig()
    r = site_doc["readiness"]
    return ReadinessConfig(
        min_duration_h=float(r.get("min_duration_h", 6.0)),
        warn_duration_h=float(r.get("warn_duration_h", 24.0)),
        max_sample_period_s=float(r.get("max_sample_period_s", 60.0)),
        warn_sample_period_s=float(r.get("warn_sample_period_s", 15.0)),
        max_missing_share=float(r.get("max_missing_share", 0.30)),
        warn_missing_share=float(r.get("warn_missing_share", 0.05)),
        max_flat_share=float(r.get("max_flat_share", 0.90)),
        warn_flat_share=float(r.get("warn_flat_share", 0.50)),
        min_anomaly_inputs=int(r.get("min_anomaly_inputs", 2)),
        min_softsensor_inputs=int(r.get("min_softsensor_inputs", 2)),
    )


def evaluate_dataset_readiness(
    dataset_id: str,
    t_s: np.ndarray,
    columns: Mapping[str, np.ndarray],
    loops: Sequence[LoopTags],
    site_doc: dict[str, Any] | None = None,
) -> DatasetReadiness:
    """Evaluate structural and statistical readiness across all core product modules."""
    cfg = config_from_site(site_doc)
    loop_verdict = _evaluate_loop_readiness(t_s, columns, loops, cfg)
    anomaly_verdict = _evaluate_anomaly_readiness(columns, site_doc, cfg)
    softsensor_verdict = _evaluate_softsensor_readiness(columns, site_doc, cfg)

    modules = {
        "loops": loop_verdict,
        "anomaly": anomaly_verdict,
        "softsensor": softsensor_verdict,
    }
    overall = _aggregate_verdicts(modules.values())
    return DatasetReadiness(dataset_id=dataset_id, verdict=overall, modules=modules)


def _aggregate_verdicts(verdicts: Sequence[ModuleVerdict]) -> str:
    """Aggregate per-module statuses into a single dataset-level traffic light."""
    statuses = {v.status for v in verdicts}
    if VERDICT_NOT_READY in statuses:
        return VERDICT_NOT_READY
    if VERDICT_WARNING in statuses:
        return VERDICT_WARNING
    return VERDICT_OK


def _evaluate_loop_readiness(
    t_s: np.ndarray,
    columns: Mapping[str, np.ndarray],
    loops: Sequence[LoopTags],
    cfg: ReadinessConfig,
) -> ModuleVerdict:
    """Evaluate loop monitoring readiness based on roles and time-series quality."""
    if not loops:
        return ModuleVerdict(
            status=VERDICT_NOT_READY,
            reasons=["No control loops defined or discovered."],
            items_checked=0,
        )

    reasons: list[str] = []
    has_fail, has_warn = _check_loop_structural_roles(loops, reasons)
    report = check_readiness(t_s, columns, loops, cfg)

    for check in report.checks:
        if check.status == FAIL:
            has_fail = True
            reasons.append(check.message)
        elif check.status == WARN:
            has_warn = True
            reasons.append(check.message)

    status = VERDICT_NOT_READY if has_fail else (VERDICT_WARNING if has_warn else VERDICT_OK)
    return ModuleVerdict(status=status, reasons=reasons, items_checked=len(loops))


def _check_loop_structural_roles(
    loops: Sequence[LoopTags],
    reasons: list[str],
) -> tuple[bool, bool]:
    """Inspect loop PV, SP, OUT signal presence and record actionable reasons."""
    has_fail = False
    has_warn = False
    for loop in loops:
        if not loop.pv or not loop.sp:
            has_fail = True
            reasons.append(f"Loop '{loop.name}' is missing required PV or SP tag.")
        if not loop.out:
            has_warn = True
            reasons.append(f"Loop '{loop.name}' has no OUT tag mapped (monitoring only).")
    return has_fail, has_warn


def _evaluate_anomaly_readiness(
    columns: Mapping[str, np.ndarray],
    site_doc: dict[str, Any] | None,
    cfg: ReadinessConfig,
) -> ModuleVerdict:
    """Evaluate anomaly detection readiness based on input tags count and quality."""
    inputs = _extract_mapped_inputs(columns, site_doc)
    reasons: list[str] = []

    if len(inputs) < cfg.min_anomaly_inputs:
        msg = f"At least {cfg.min_anomaly_inputs} inputs required (found {len(inputs)})."
        return ModuleVerdict(status=VERDICT_NOT_READY, reasons=[msg], items_checked=len(inputs))

    has_fail, has_warn = _inspect_series_quality(columns, inputs, cfg, reasons)
    status = VERDICT_NOT_READY if has_fail else (VERDICT_WARNING if has_warn else VERDICT_OK)
    return ModuleVerdict(status=status, reasons=reasons, items_checked=len(inputs))


def _evaluate_softsensor_readiness(
    columns: Mapping[str, np.ndarray],
    site_doc: dict[str, Any] | None,
    cfg: ReadinessConfig,
) -> ModuleVerdict:
    """Evaluate soft sensor readiness based on target, input features, and lab references."""
    target = _extract_target(site_doc)
    reasons: list[str] = []

    if not target:
        reasons.append("No target tag mapped for soft sensor.")
        return ModuleVerdict(status=VERDICT_NOT_READY, reasons=reasons, items_checked=0)

    inputs = _extract_mapped_inputs(columns, site_doc)
    if len(inputs) < cfg.min_softsensor_inputs:
        msg = (
            f"At least {cfg.min_softsensor_inputs} predictor inputs required "
            f"(found {len(inputs)})."
        )
        reasons.append(msg)
        return ModuleVerdict(status=VERDICT_NOT_READY, reasons=reasons, items_checked=len(inputs))

    has_lab = _has_lab_reference(site_doc)
    if not has_lab:
        reasons.append("No lab references or lab data available for calibration.")

    has_fail, has_warn = _inspect_series_quality(columns, [target, *inputs], cfg, reasons)
    if not has_lab:
        has_warn = True

    status = VERDICT_NOT_READY if has_fail else (VERDICT_WARNING if has_warn else VERDICT_OK)
    return ModuleVerdict(status=status, reasons=reasons, items_checked=len(inputs) + 1)


def _extract_target(site_doc: dict[str, Any] | None) -> str | None:
    """Extract primary target tag from signals block."""
    if not site_doc:
        return None
    for sig in site_doc.get("signals", []):
        if sig.get("role") == "target":
            return str(sig.get("tag"))
    return None


def _extract_mapped_inputs(
    columns: Mapping[str, np.ndarray],
    site_doc: dict[str, Any] | None,
) -> list[str]:
    """Identify available input tags from site signals or numeric column list."""
    if not site_doc or "signals" not in site_doc:
        return [c for c in columns if not c.startswith("_") and c != "timestamp"]
    inputs = [s["tag"] for s in site_doc.get("signals", []) if s.get("role") == "input"]
    return [inp for inp in inputs if inp in columns] or list(columns.keys())


def _has_lab_reference(site_doc: dict[str, Any] | None) -> bool:
    """Check whether site document contains lab signal roles or lab definitions."""
    if not site_doc:
        return False
    if site_doc.get("labs"):
        return True
    return any(s.get("role") == "lab" for s in site_doc.get("signals", []))


def _inspect_series_quality(
    columns: Mapping[str, np.ndarray],
    tags: Sequence[str],
    cfg: ReadinessConfig,
    reasons: list[str],
) -> tuple[bool, bool]:
    """Test missing share and frozen values across a list of tag series."""
    has_fail = False
    has_warn = False
    for tag in tags:
        if tag not in columns:
            continue
        vals = np.asarray(columns[tag], dtype=float)
        missing = float(np.mean(np.isnan(vals)))
        if missing > cfg.max_missing_share:
            has_fail = True
            reasons.append(f"Tag '{tag}' missing share {missing:.1%} exceeds limit.")
        elif missing > cfg.warn_missing_share:
            has_warn = True
            reasons.append(f"Tag '{tag}' has {missing:.1%} missing samples.")
    return has_fail, has_warn
