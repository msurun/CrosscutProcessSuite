"""Consistency check across repeated step tests of one loop.

Repeated bump tests should yield similar parameters. A closed-loop or valve-nonlinearity
bias can make one fit look precise (small SE) yet disagree with its siblings; this module
flags such rows so the operator sees a contradiction instead of a plausible-looking number.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# MAD-to-sigma scale factor for normally distributed data (Croux & Rousseeuw).
MAD_SCALE = 1.4826

# Outlier threshold as a multiple of the scaled MAD.
MAD_OUTLIER_FACTOR = 3.0

# Relative fallback threshold: 25 % of the median key parameter.
RELATIVE_OUTLIER_FRACTION = 0.25

# Minimum number of 'ok' rows of one model needed before a consistency check runs.
MIN_ROWS_FOR_CHECK = 4

# Key parameter name per model and model kind.
FOPDT = "fopdt"
IPDT = "ipdt"
KEY_PARAMETER = {FOPDT: "gain", IPDT: "slope"}

# Reason code appended to rows that disagree with the group median.
REASON_INCONSISTENT = "inconsistent_with_median"


def add_consistency(rows: list[dict]) -> list[dict]:
    """Flag rows that disagree with their model group and summarise each group.

    Args:
        rows: Step-analyzer payload rows. Mutated in place: an outlier gets REASON_INCONSISTENT
            appended to ``row['reasons']`` and its verdict turned from 'ok' to 'weak'.

    Returns:
        One summary dict per model that had at least one row, with ``model``, ``n_rows``
        (rows that were 'ok' before the check), ``n_consistent``, the key parameter
        (``gain`` or ``slope``) as ``{'median','mad'}``, and for FOPDT ``tau_s`` and
        ``theta_s`` medians/MADs over the consistent rows.
    """
    summaries: list[dict] = []
    for model, key_parameter in KEY_PARAMETER.items():
        group = [row for row in rows if row.get("model") == model]
        if not group:
            continue
        summaries.append(_process_group(group, model, key_parameter))
    return summaries


def _process_group(group: list[dict], model: str, key_parameter: str) -> dict[str, Any]:
    """Run the consistency check for one model and return its summary dict."""
    ok_rows = [row for row in group if row.get("verdict") == "ok"]
    key_values = _key_values(ok_rows, key_parameter)
    is_checkable = len(ok_rows) >= MIN_ROWS_FOR_CHECK and len(key_values) >= MIN_ROWS_FOR_CHECK

    # In plain words: with too few usable values there is no group to compare against,
    # so every row stays as it is and counts as consistent.
    if not is_checkable:
        return _summary(model, n_rows=len(ok_rows), key_values=key_values, consistent=ok_rows)

    median = float(np.median(key_values))
    mad = _scaled_mad(key_values, median)
    limit = max(MAD_OUTLIER_FACTOR * mad, RELATIVE_OUTLIER_FRACTION * abs(median))
    consistent = _flag_outliers_and_keep_consistent(ok_rows, key_parameter, median, limit)
    return _summary(model, n_rows=len(ok_rows), key_values=key_values, consistent=consistent)


def _key_values(rows: list[dict], key_parameter: str) -> np.ndarray:
    """Collect finite key-parameter values of the rows, skipping missing or invalid ones."""
    values = [_param_value(row, key_parameter) for row in rows]
    finite = [value for value in values if value is not None]
    return np.asarray(finite, dtype=float)


def _param_value(row: dict, name: str) -> float | None:
    """Return a finite parameter value from ``row['params'][name]['value']``, else None."""
    param = row.get("params", {}).get(name)
    if not isinstance(param, dict):
        return None
    value = param.get("value")
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _scaled_mad(values: np.ndarray, median: float) -> float:
    """Median absolute deviation from the given median, scaled to a sigma estimate."""
    return MAD_SCALE * float(np.median(np.abs(values - median)))


def _flag_outliers_and_keep_consistent(
    ok_rows: list[dict], key_parameter: str, median: float, limit: float
) -> list[dict]:
    """Append the inconsistency reason to outliers and return the remaining rows."""
    consistent: list[dict] = []
    for row in ok_rows:
        value = _param_value(row, key_parameter)
        if value is not None and abs(value - median) > limit:
            row.setdefault("reasons", []).append(REASON_INCONSISTENT)
            row["verdict"] = "weak"
        else:
            consistent.append(row)
    return consistent


def _summary(
    model: str, *, n_rows: int, key_values: np.ndarray, consistent: list[dict]
) -> dict[str, Any]:
    """Build the summary dict with medians/MADs of the key parameter and (FOPDT) tau/theta."""
    summary: dict[str, Any] = {
        "model": model,
        "n_rows": n_rows,
        "n_consistent": len(consistent),
        KEY_PARAMETER[model]: _median_and_mad(key_values),
    }
    if model == FOPDT:
        summary["tau_s"] = _median_and_mad(_key_values(consistent, "tau_s"))
        summary["theta_s"] = _median_and_mad(_key_values(consistent, "theta_s"))
    return summary


def _median_and_mad(values: np.ndarray) -> dict[str, float | None]:
    """Return {'median','mad'} JSON-safe floats, None when the array is empty."""
    if values.size == 0:
        return {"median": None, "mad": None}
    median = float(np.median(values))
    return {"median": _json_float(median), "mad": _json_float(_scaled_mad(values, median))}


def _json_float(value: Any) -> float | None:
    """Convert a number to a JSON-safe float, or None when it is not finite."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None
