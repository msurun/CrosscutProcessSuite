"""Validation report generator from a frozen template (issue #40).

Reproduces by configuration what exp31 did by hand for one online analyser against one lab
tag: coverage, stamp and missing-code checks, delay scan, bias, RMSE, MAE, correlation,
Bland-Altman limits and drift. Plant data validates; it never defines features or thresholds.

Input: a long-format CSV (timestamp, tag, value) and a JSON config (docs/customer_kit/
VALIDATION_REPORT.md). Output: report.md and report.json, byte-identical for equal input.
Run: python tools/validation_report.py DATA.csv CONFIG.json OUT_DIR
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Any

import numpy as np

from crosscut_softsensor import validation_stats as stats
from crosscut_softsensor.alignment import scan_alignment, window_means_at_delay
from crosscut_softsensor.long_format import (
    LabReadSettings,
    TagSeries,
    load_long_csv,
    parse_stamp,
)
from crosscut_softsensor.validation_template import (
    TEMPLATE_V1,
    TEMPLATE_VERSION,
    template_sha256,
)

GENERATOR = "crosscut_softsensor.validation_report"
REQUIRED_KEYS = ("analyser_tag", "lab_tag", "composite_window_s", "delay_scan")
SIGN_CONVENTION = "positive delay means the analyser is recorded later than the lab process time"
SOURCES = {
    "coverage": "validation_report.coverage_section, validation_stats.gap_count",
    "stamp_checks": "validation_report.scan_raw_rows",
    "alignment": "alignment.scan_alignment (#38)",
    "agreement": "validation_stats.pair_statistics at alignment.window_means_at_delay",
    "drift": "validation_stats.drift_statistics",
    "process": "validation_stats.correlation of process window mean with the difference",
    "thresholds": "validation_report.check_thresholds",
}


class ReportError(ValueError):
    """The dataset or the config cannot produce a report."""


@dataclass(frozen=True)
class ReportConfig:
    """Everything a run needs besides the data; every field is user configuration."""

    analyser_tag: str
    lab_tag: str
    composite_window_s: float
    delay_scan: dict
    process_tags: tuple[str, ...] = ()
    metadata_extra: dict | None = None
    window_start: str | None = None
    window_end: str | None = None
    gap_factor: float = 3.0
    drift_bins: int = 4
    bland_altman_z: float = 1.96
    thresholds: dict | None = None


def parse_config(document: dict[str, Any]) -> ReportConfig:
    """Validate the JSON config and build a `ReportConfig`."""
    missing = [key for key in REQUIRED_KEYS if key not in document]
    if missing:
        raise ReportError(f"config: missing {', '.join(missing)}.")
    window = document.get("window") or {}
    return ReportConfig(
        analyser_tag=document["analyser_tag"], lab_tag=document["lab_tag"],
        composite_window_s=float(document["composite_window_s"]),
        delay_scan=dict(document["delay_scan"]),
        process_tags=tuple(document.get("process_tags", ())),
        metadata_extra={"stamp": document["stamp"]} if "stamp" in document else {},
        window_start=window.get("start"), window_end=window.get("end"),
        gap_factor=float(document.get("gap_factor", 3.0)),
        drift_bins=int(document.get("drift_bins", 4)),
        bland_altman_z=float(document.get("bland_altman_z", 1.96)),
        thresholds=document.get("thresholds") or {},
    )


def scan_raw_rows(path: Path, tags: Sequence[str], settings: LabReadSettings | None) -> dict:
    """Count rows, missing-code rows, text rows, duplicate and out-of-order stamps per tag."""
    keys = ("rows", "missing_code", "non_numeric", "duplicate_stamps", "out_of_order")
    counts = {tag: dict.fromkeys(keys, 0) for tag in tags}
    last: dict[str, str] = {}
    seen: dict[str, set[str]] = {tag: set() for tag in tags}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            tag = (row.get("tag") or "").strip()
            if tag in counts:
                _count_row(counts[tag], row, settings, last, seen[tag], tag)
    return counts


def _count_row(entry: dict, row: dict, settings: LabReadSettings | None,
               last: dict[str, str], seen: set[str], tag: str) -> None:
    """Update the raw-row counters of one tag with one CSV row."""
    entry["rows"] += 1
    stamp = (row.get("timestamp") or "").strip().replace("T", " ")
    entry["duplicate_stamps"] += stamp in seen
    entry["out_of_order"] += tag in last and stamp < last[tag]
    seen.add(stamp)
    last[tag] = stamp
    try:
        value = float((row.get("value") or "").strip())
    except ValueError:
        entry["non_numeric"] += 1
        return
    if settings is not None and value in settings.missing_for(tag):
        entry["missing_code"] += 1


def load_series(path: Path, config: ReportConfig, settings: LabReadSettings | None) -> dict:
    """Load the configured tags, apply the time window and fail on a tag without rows."""
    wanted = (config.analyser_tag, config.lab_tag, *config.process_tags)
    loaded = load_long_csv(path, tags=wanted, settings=settings)
    absent = [tag for tag in wanted if tag not in loaded]
    if absent:
        raise ReportError(f"{path.name}: no usable rows for tag(s) {', '.join(absent)}.")
    start = parse_stamp(config.window_start, settings) if config.window_start else -np.inf
    end = parse_stamp(config.window_end, settings) if config.window_end else np.inf
    return {tag: _cut(series, start, end) for tag, series in loaded.items()}


def _cut(series: TagSeries, start_s: float, end_s: float) -> TagSeries:
    """Keep samples with start_s <= t <= end_s."""
    keep = (series.t_s >= start_s) & (series.t_s <= end_s)
    return TagSeries(series.tag, series.t_s[keep], series.values[keep])


def coverage_section(series: dict, gap_factor: float) -> dict:
    """Per tag: samples, first/last stamp (Unix s), median period (s) and gap count."""
    section = {}
    for tag, item in series.items():
        period, gaps = stats.gap_count(item.t_s, gap_factor)
        section[tag] = {
            "samples": int(len(item.t_s)),
            "first_s": float(item.t_s[0]) if len(item.t_s) else None,
            "last_s": float(item.t_s[-1]) if len(item.t_s) else None,
            "median_period_s": period, "gaps": gaps,
        }
    return section


def process_section(series: dict, config: ReportConfig, delay_s: float,
                    analyser_means: np.ndarray, diff: np.ndarray) -> dict:
    """Correlation of each process tag's composite mean with the analyser-lab difference."""
    section = {}
    lab_series = series[config.lab_tag]
    for tag in config.process_tags:
        _, _, means = window_means_at_delay(lab_series, series[tag], _metadata(config), delay_s)
        finite = np.isfinite(means) & np.isfinite(analyser_means)
        section[tag] = {"pairs": int(np.count_nonzero(finite)),
                        "correlation_with_difference": stats.correlation(
                            means[finite], diff[finite])}
    return section


def _metadata(config: ReportConfig) -> dict:
    """Alignment metadata of the lab series; missing codes were removed when loading."""
    return {"composite_window_s": config.composite_window_s, **(config.metadata_extra or {})}


def check_thresholds(agreement: dict, drift: dict, limits: dict) -> dict:
    """Pass, fail or not assessed for each configured threshold; none has a default."""
    rules = {
        "max_abs_bias": lambda lim: abs(agreement["bias"]) <= lim,
        "max_rmse": lambda lim: agreement["rmse"] <= lim,
        "min_correlation": lambda lim: agreement["correlation"] >= lim,
        "max_abs_trend_per_day": lambda lim: abs(drift["trend_per_day"]) <= lim,
    }
    unknown = sorted(set(limits) - set(rules))
    if unknown:
        raise ReportError(f"thresholds: unknown field(s) {', '.join(unknown)}.")
    return {name: _verdict(rule, limits.get(name)) for name, rule in rules.items()}


def _verdict(rule: Any, limit: float | None) -> dict:
    """One threshold entry; NaN statistics fail because they cannot be shown to pass."""
    if limit is None:
        return {"limit": None, "result": "not assessed"}
    return {"limit": float(limit), "result": "pass" if bool(rule(float(limit))) else "fail"}


def compute_report(data_path: Path, document: dict[str, Any],
                   settings: LabReadSettings | None = None) -> dict:
    """Run every analysis step and return the report as plain data (the JSON content).

    `settings` carries the site time zone and missing codes (see tools/validation_report.py,
    which reads them from the site file); without it stamps are UTC and no code is missing.
    """
    config = parse_config(document)
    series = load_series(data_path, config, settings)
    tags = (config.analyser_tag, config.lab_tag, *config.process_tags)
    scan = scan_alignment(series[config.lab_tag], series[config.analyser_tag],
                          _metadata(config), config.delay_scan)
    result = agreement_sections(series, config, scan["best_delay_s"])
    return {
        "template": {"version": TEMPLATE_VERSION, "sha256": template_sha256()},
        "generator": GENERATOR, "sign_convention": SIGN_CONVENTION,
        "dataset": {"name": data_path.name, "sha256": file_sha256(data_path)},
        "config": {"document": document, "sha256": canonical_sha256(document)},
        "coverage": coverage_section(series, config.gap_factor),
        "stamp_checks": scan_raw_rows(data_path, tags, settings),
        "alignment": scan, **result, "sources": SOURCES,
    }


def agreement_sections(series: dict, config: ReportConfig, delay_s: float) -> dict:
    """Agreement, drift, process and threshold sections at one delay."""
    t_s, lab, analyser = window_means_at_delay(
        series[config.lab_tag], series[config.analyser_tag], _metadata(config), delay_s)
    finite = np.isfinite(analyser) & np.isfinite(lab)
    if np.count_nonzero(finite) < stats.MIN_PAIRS_FOR_SPREAD:
        raise ReportError("fewer than 3 paired composites; cannot compute agreement.")
    diff = analyser[finite] - lab[finite]
    agreement = stats.pair_statistics(analyser[finite], lab[finite], config.bland_altman_z)
    drift = stats.drift_statistics(t_s[finite], diff, config.drift_bins)
    process = process_section(series, config, delay_s, np.where(finite, analyser, np.nan),
                              np.where(finite, analyser - lab, np.nan))
    return {"agreement": agreement, "drift": drift, "process": process,
            "thresholds": check_thresholds(agreement, drift, config.thresholds or {})}


def file_sha256(path: Path) -> str:
    """SHA-256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(document: Any) -> str:
    """SHA-256 of a JSON document with sorted keys, so key order does not matter."""
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode("utf-8")).hexdigest()


def json_text(report: dict) -> str:
    """Deterministic JSON: sorted keys, NaN and infinity written as null, trailing newline."""
    return json.dumps(_finite(report), indent=2, sort_keys=True, allow_nan=False) + "\n"


def _finite(value: Any) -> Any:
    """Recursively replace non-finite floats by None (JSON has no NaN)."""
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_finite(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _num(value: Any) -> str:
    """Format a number with 6 significant digits; None and NaN become n/a."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "n/a"
    return f"{value:.6g}" if isinstance(value, float) else str(value)


def _iso(seconds: float | None) -> str:
    """Unix seconds as an ISO UTC stamp."""
    if seconds is None:
        return "n/a"
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%d %H:%M:%S")


def _table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """A Markdown table."""
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def render_markdown(report: dict) -> str:
    """Fill the frozen template with the numbers of `report`."""
    align, agree = report["alignment"], report["agreement"]
    cover = [(tag, _num(c["samples"]), _iso(c["first_s"]), _iso(c["last_s"]),
              _num(c["median_period_s"]), c["gaps"]) for tag, c in report["coverage"].items()]
    stamp = [(tag, *(c[key] for key in ("rows", "missing_code", "non_numeric",
                                         "duplicate_stamps", "out_of_order")))
             for tag, c in report["stamp_checks"].items()]
    return Template(TEMPLATE_V1).substitute(
        analyser_tag=report["config"]["document"]["analyser_tag"],
        lab_tag=report["config"]["document"]["lab_tag"],
        template_version=report["template"]["version"],
        template_sha256=report["template"]["sha256"],
        generator=report["generator"], dataset_name=report["dataset"]["name"],
        dataset_sha256=report["dataset"]["sha256"], config_sha256=report["config"]["sha256"],
        coverage_table=_table(("Tag", "Samples", "First (UTC)", "Last (UTC)", "Period s", "Gaps"),
                              cover),
        stamp_table=_table(("Tag", "Rows", "Missing code", "Non-numeric", "Duplicate stamps",
                            "Out of order"), stamp),
        sign_convention=report["sign_convention"], best_delay_s=_num(align["best_delay_s"]),
        interval_low_s=_num(align["interval_low_s"]),
        interval_high_s=_num(align["interval_high_s"]),
        alignment_pairs=align["pairs"], boundary=str(align["boundary"]).lower(),
        pairs=agree["pairs"], agreement_table=_agreement_table(agree),
        loa_lower=_num(agree["loa_lower"]), loa_upper=_num(agree["loa_upper"]),
        z=_num(report["config"]["document"].get("bland_altman_z", 1.96)),
        trend_per_day=_num(report["drift"]["trend_per_day"]), drift_table=_drift_table(report),
        process_table=_process_table(report), threshold_table=_threshold_table(report),
    )


def _agreement_table(agree: dict) -> str:
    """Bias, RMSE, MAE, correlation and spread of the differences."""
    rows = [(name, _num(agree[key])) for name, key in (
        ("Bias", "bias"), ("RMSE", "rmse"), ("MAE", "mae"),
        ("Correlation", "correlation"), ("SD of differences", "diff_sd"))]
    return _table(("Statistic", "Value"), rows)


def _drift_table(report: dict) -> str:
    """Mean difference in each time slice."""
    rows = [(_iso(b["first_s"]), _iso(b["last_s"]), b["pairs"], _num(b["mean_difference"]))
            for b in report["drift"]["bins"]]
    return _table(("From (UTC)", "To (UTC)", "Pairs", "Mean difference"), rows)


def _process_table(report: dict) -> str:
    """Correlation of each process tag with the difference, or a note when none is set."""
    if not report["process"]:
        return "No process tags configured."
    rows = [(tag, p["pairs"], _num(p["correlation_with_difference"]))
            for tag, p in report["process"].items()]
    return _table(("Tag", "Pairs", "Correlation with difference"), rows)


def _threshold_table(report: dict) -> str:
    """The configured limit and the result for every threshold field."""
    rows = [(name, _num(t["limit"]), t["result"]) for name, t in report["thresholds"].items()]
    return _table(("Threshold", "Limit", "Result"), rows)


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    """Write report.json and report.md (LF line ends) into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / "report.json", out_dir / "report.md"
    json_path.write_bytes(json_text(report).encode("utf-8"))
    md_path.write_bytes(render_markdown(_finite(report)).encode("utf-8"))
    return json_path, md_path
