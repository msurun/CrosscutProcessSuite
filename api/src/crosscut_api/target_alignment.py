"""Resolve catalogue timing and quality rules for soft-sensor targets.

The same metadata is used for training, causal bias tracking and delay scans.
"""

from pathlib import Path
from typing import Any

import numpy as np
from crosscut_connectors.site import SiteError, load_site, site_path
from crosscut_softsensor.alignment import AlignmentError, align_target
from crosscut_softsensor.config import SoftSensorConfig
from crosscut_softsensor.long_format import TagSeries
from crosscut_softsensor.runner import LabResults
from fastapi import HTTPException


def catalogue_metadata(root: Path, tag: str) -> dict[str, Any]:
    """Resolve missing codes from site, tag and lab overrides, in that order."""
    try:
        document = load_site(root) if site_path(root).is_file() else {}
    except SiteError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    metadata = {"missing_codes": document.get("import", {}).get("missing_codes", [])}
    tag_entry = next((entry for entry in document.get("tags", []) if entry["id"] == tag), {})
    metadata.update({key: tag_entry[key] for key in ("missing_codes",) if key in tag_entry})
    lab_entry = next((entry for entry in document.get("labs", [])
                      if entry.get("tag", entry["id"]) == tag), {})
    return {**metadata, **lab_entry}


def aligned_labs(
    root: Path, rows: list[tuple[float, float]], config: SoftSensorConfig
) -> LabResults:
    """Align uploaded stamps using catalogue rules, retaining the legacy delay fallback."""
    metadata = catalogue_metadata(root, config.target_tag)
    if "report_delay_s" not in metadata and "latency_s" not in metadata:
        metadata["report_delay_s"] = config.lab_delay_s
    series = rows_series(config.target_tag, rows)
    try:
        return align_target(series, metadata)
    except AlignmentError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def rows_series(tag: str, rows: list[tuple[float, float]]) -> TagSeries:
    """Build float arrays from uploaded (seconds, value) rows."""
    return TagSeries(tag, np.array([row[0] for row in rows]),
                     np.array([row[1] for row in rows]))


def training_target(t_bins: np.ndarray, labs: LabResults, end_s: float) -> np.ndarray:
    """Place finite targets in sample bins only after their result became available."""
    target = np.full(len(t_bins), np.nan)
    # A corrected physical sample time and a report availability time serve different purposes:
    # features use the former, while the latter prevents future reports leaking into training.
    for stamp_s, value, available_s in zip(labs.t_s, labs.values, labs.available_s, strict=True):
        row = int(np.searchsorted(t_bins, stamp_s, side="right")) - 1
        if row >= 0 and stamp_s < end_s and available_s < end_s and np.isfinite(value):
            target[row] = value
    return target
