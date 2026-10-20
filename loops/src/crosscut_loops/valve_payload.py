"""JSON contract layer for the valve stroke test: request parsing, payloads, CSV import.

This module sits between the stroke test analysis library (`valve_test.py`) and an HTTP API.
It validates user input, renders JSON-safe payloads, and parses CSV uploads.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any

import numpy as np

from crosscut_loops.valve_test import (
    StrokePlan,
    StrokeResult,
    analyze_stroke_test,
    plan_stroke_test,
    procedure_steps,
    reason_code,
)

MAX_CSV_CHARS = 5_000_000  # characters above which a CSV upload is rejected
MAX_CSV_ROWS = 10_000  # rows of a CSV record above which parsing is rejected
MIN_RECORD_SAMPLES = 20  # minimum samples required to analyse a window
MAX_RECORD_POINTS = 600  # maximum points sent to the browser for the analysed record
MAX_PLAN_STEPS = 500  # maximum number of test steps allowed in a plan
CSV_DELIMITERS = (";", "\t", ",")  # order of preference on ties


class ValveInputError(ValueError):
    """Input error with a stable machine code and the offending field.

    Attributes:
        code: stable error code for the API (e.g. "plan_invalid", "record_too_short").
        field: key name of the request field that caused the error, or None.
    """

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def plan_from_request(request: Mapping[str, Any]) -> StrokePlan:
    """Build a StrokePlan from a request mapping.

    Validates all keys and values, raising ValveInputError with a stable code and field
    on the first problem. The library's own ValueError (e.g. steps outside output limits)
    is re-raised as ValveInputError("plan_invalid").

    Args:
        request: mapping with keys op_start (required), dwell_s (required), op_low,
            op_high, pv_band, step_sizes, steps_per_leg.

    Returns:
        A StrokePlan.

    Raises:
        ValveInputError: on any invalid input.
    """
    op_start = _required_number(request, "op_start")
    dwell_s = _required_dwell(request)
    op_low = _optional_number(request, "op_low", 0.0)
    op_high = _optional_number(request, "op_high", 100.0)
    pv_band = _optional_band(request, "pv_band")
    step_sizes = _optional_positive_list(request, "step_sizes", (1.0, 0.25))
    steps_per_leg = _optional_positive_int_list(request, "steps_per_leg", (4, 12))

    try:
        plan = plan_stroke_test(
            op_start=op_start,
            dwell_s=dwell_s,
            op_low=op_low,
            op_high=op_high,
            pv_band=pv_band,
            step_sizes=step_sizes,
            steps_per_leg=steps_per_leg,
        )
    except ValueError as error:
        raise ValveInputError("plan_invalid", str(error)) from error

    if len(plan.steps) > MAX_PLAN_STEPS:
        raise ValveInputError(
            "plan_too_long",
            f"plan has {len(plan.steps)} steps; the maximum is {MAX_PLAN_STEPS}",
        )
    return plan


def _required_number(request: Mapping[str, Any], key: str) -> float:
    """Return request[key] as a finite float, or raise ValveInputError with field=key."""
    value = request.get(key)
    if value is None or not _is_finite_number(value):
        raise ValveInputError("plan_invalid", _type_message(key, "a finite number"), key)
    return float(value)


def _required_dwell(request: Mapping[str, Any]) -> int:
    """Return request["dwell_s"] as an int; must be a finite number > 0 and integer-valued."""
    value = request.get("dwell_s")
    if (
        value is None
        or not _is_finite_number(value)
        or float(value) <= 0
        or float(value) != int(float(value))
    ):
        raise ValveInputError(
            "plan_invalid", "dwell_s must be a positive integer-valued number of seconds", "dwell_s"
        )
    return int(float(value))


def _optional_number(request: Mapping[str, Any], key: str, default: float) -> float:
    """Return request[key] as a finite float, or default when the key is missing."""
    if key not in request:
        return default
    value = request[key]
    if not _is_finite_number(value):
        raise ValveInputError("plan_invalid", _type_message(key, "a finite number"), key)
    return float(value)


def _optional_band(request: Mapping[str, Any], key: str) -> float | None:
    """Return request[key] as a positive float, None when missing or explicitly None."""
    if key not in request or request[key] is None:
        return None
    value = request[key]
    if not _is_finite_number(value) or float(value) <= 0:
        raise ValveInputError("plan_invalid", f"{key} must be a positive number or null", key)
    return float(value)


def _optional_positive_list(
    request: Mapping[str, Any], key: str, default: tuple[float, ...]
) -> tuple[float, ...]:
    """Return request[key] as a tuple of positive finite floats, or default when missing."""
    if key not in request:
        return default
    values = request[key]
    if not isinstance(values, (list, tuple)) or not values:
        raise ValveInputError("plan_invalid", f"{key} must be a non-empty list of numbers", key)
    result: list[float] = []
    for i, value in enumerate(values):
        if not _is_finite_number(value) or float(value) <= 0:
            raise ValveInputError(
                "plan_invalid", f"{key}[{i}] must be a positive finite number", key
            )
        result.append(float(value))
    return tuple(result)


def _optional_positive_int_list(
    request: Mapping[str, Any], key: str, default: tuple[int, ...]
) -> tuple[int, ...]:
    """Return request[key] as a tuple of positive integers, or default when missing."""
    if key not in request:
        return default
    values = request[key]
    if not isinstance(values, (list, tuple)) or not values:
        raise ValveInputError("plan_invalid", f"{key} must be a non-empty list of integers", key)
    result: list[int] = []
    for i, value in enumerate(values):
        if (
            not _is_finite_number(value)
            or float(value) != int(float(value))
            or int(float(value)) < 1
        ):
            raise ValveInputError("plan_invalid", f"{key}[{i}] must be a positive integer", key)
        result.append(int(float(value)))
    return tuple(result)


def _is_finite_number(value: Any) -> bool:
    """True when value is an int or float (not bool) that is not NaN or infinite."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return bool(np.isfinite(float(value)))


def _type_message(key: str, expected: str) -> str:
    """Human-readable type error message for a request field."""
    return f"{key} must be {expected}"


def plan_payload(plan: StrokePlan) -> dict[str, Any]:
    """Render a StrokePlan as a JSON-ready payload.

    Returns:
        A dict with the plan parameters, the full step list and the operator procedure.
    """
    return {
        "op_start": plan.op_start,
        "dwell_s": plan.dwell_s,
        "op_low": plan.op_low,
        "op_high": plan.op_high,
        "pv_band": plan.pv_band,
        "step_sizes": list(plan.step_sizes),
        "steps_per_leg": list(plan.steps_per_leg),
        "n_steps": len(plan.steps),
        # Total time includes the initial set_start dwell and every step dwell.
        "total_s": plan.dwell_s * (len(plan.steps) + 1),
        "steps": [
            {
                "index": step.index,
                "op_target": _json_float(step.op_target),
                "direction": step.direction,
                "size": _json_float(step.size),
                "after_reversal": step.after_reversal,
            }
            for step in plan.steps
        ],
        "procedure": procedure_steps(plan),
    }


def result_payload(result: StrokeResult) -> dict[str, Any]:
    """Render a StrokeResult as a JSON-ready payload with all numeric fields sanitised.

    NaN and infinite floats become None, so the payload is always JSON-serialisable.
    """
    return {
        "deadband": _json_float(result.deadband),
        "deadband_bracket": (
            None
            if result.deadband_bracket is None
            else [_json_float(v) for v in result.deadband_bracket]
        ),
        "deadband_lower_bound": _json_float(result.deadband_lower_bound),
        "resolution_le": _json_float(result.resolution_le),
        "gain": _json_float(result.gain),
        "sigma_pv": _json_float(result.sigma_pv),
        "pv_left_band": bool(result.pv_left_band),
        "reason_code": reason_code(result.reason),
        "reason": result.reason,
        "moves": [
            {
                "start_index": int(move.start_index),
                "op_change": _json_float(move.op_change),
                "pv_change": _json_float(move.pv_change),
                "moved": bool(move.moved),
                "size": _json_float(move.size),
                "after_reversal": bool(move.after_reversal),
            }
            for move in result.moves
        ],
    }


def _json_float(value: Any) -> float | None:
    """Convert a number (possibly NaN/inf) to a JSON-safe float, or None."""
    if value is None:
        return None
    float_value = float(value)
    if not np.isfinite(float_value):
        return None
    return float_value


def analyse_window(
    t_s: np.ndarray,
    op: np.ndarray,
    pv: np.ndarray,
    plan: StrokePlan,
    window: tuple[float | None, float | None] = (None, None),
) -> dict[str, Any]:
    """Analyse one time window of a stroke test record and return result plus record series.

    Args:
        t_s: time array in seconds (relative to the record start).
        op: output array in % of span.
        pv: PV array in PV units.
        plan: the StrokePlan the operator executed.
        window: (start_s, end_s) in seconds relative to t_s[0]; None means open on that side.

    Returns:
        A dict with keys "result" (result_payload) and "record" (n_samples, start_s, end_s,
        and decimated series of the analysed window).

    Raises:
        ValveInputError: with code record_mismatch, window_invalid, record_too_short,
            record_not_finite, no_op_changes, or record_invalid.
    """
    if not (len(t_s) == len(op) == len(pv)):
        raise ValveInputError(
            "record_mismatch",
            f"t_s, op and pv must have the same length, got {len(t_s)}, {len(op)}, {len(pv)}",
        )
    start_s, end_s = _window_bounds(t_s, window)
    indices = _window_indices(t_s, start_s, end_s)
    if len(indices) < MIN_RECORD_SAMPLES:
        raise ValveInputError(
            "record_too_short",
            f"window contains {len(indices)} samples; at least {MIN_RECORD_SAMPLES} are required",
        )

    t_window, op_window, pv_window = t_s[indices], op[indices], pv[indices]
    if not (
        np.all(np.isfinite(t_window))
        and np.all(np.isfinite(op_window))
        and np.all(np.isfinite(pv_window))
    ):
        raise ValveInputError("record_not_finite", "record contains NaN or infinite values")

    try:
        result = analyze_stroke_test(t_window, op_window, pv_window, plan)
    except ValueError as error:
        if str(error) == "no OP changes detected in the record":
            raise ValveInputError("no_op_changes", str(error)) from error
        raise ValveInputError("record_invalid", str(error)) from error

    return {
        "result": result_payload(result),
        "record": _record_payload(t_s, t_window, op_window, pv_window),
    }


def _window_bounds(
    t_s: np.ndarray, window: tuple[float | None, float | None]
) -> tuple[float, float]:
    """Resolve open window bounds to absolute seconds relative to t_s[0]."""
    start_s, end_s = window
    resolved_start = 0.0 if start_s is None else float(start_s)
    resolved_end = float(t_s[-1] - t_s[0]) if end_s is None else float(end_s)
    if resolved_start >= resolved_end:
        raise ValveInputError(
            "window_invalid",
            f"window start ({resolved_start}) must be less than end ({resolved_end})",
            "window",
        )
    return resolved_start, resolved_end


def _window_indices(t_s: np.ndarray, start_s: float, end_s: float) -> np.ndarray:
    """Boolean index array selecting samples inside [start_s, end_s] (relative seconds)."""
    time_rel = t_s - t_s[0]
    return np.flatnonzero((time_rel >= start_s) & (time_rel <= end_s))


def _record_payload(
    t_s: np.ndarray, t_window: np.ndarray, op_window: np.ndarray, pv_window: np.ndarray
) -> dict[str, Any]:
    """Decimated record series of the analysed window, times relative to the dataset start."""
    decimated = _decimate(t_window, op_window, pv_window)
    return {
        "n_samples": int(len(t_window)),
        "start_s": round(float(t_window[0] - t_s[0]), 3),
        "end_s": round(float(t_window[-1] - t_s[0]), 3),
        "series": {
            "t_s": [round(float(v), 3) for v in decimated[0]],
            "op": [_json_float(v) for v in decimated[1]],
            "pv": [_json_float(v) for v in decimated[2]],
        },
    }


def _decimate(
    t_s: np.ndarray, op: np.ndarray, pv: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decimate series to at most MAX_RECORD_POINTS by a constant stride."""
    n = len(t_s)
    if n <= MAX_RECORD_POINTS:
        return t_s, op, pv
    # Constant stride keeps the series evenly spaced in index, so the browser sees a faithful
    # shape of the full record without sending every sample.
    stride = int(np.ceil(n / MAX_RECORD_POINTS))
    indices = np.arange(0, n, stride)
    return t_s[indices], op[indices], pv[indices]


def parse_csv_record(
    text: str, columns: Mapping[str, str] | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse CSV text into (t_s, op, pv) arrays; time becomes seconds since the first row.

    Supports header or headerless files, ";" "\t" or "," delimiters, decimal comma for
    non-comma delimiters, and ISO-8601 datetimes. Rows with unparseable values are skipped.

    Args:
        text: raw CSV content (UTF-8, possibly with BOM).
        columns: optional mapping {"t": header_name, "op": header_name, "pv": header_name}
            (case-insensitive) to select columns by header; otherwise auto-detect by common
            names, else fall back to positions 0, 1, 2.

    Returns:
        (t_s, op, pv) numpy arrays.

    Raises:
        ValveInputError: with code csv_too_large, csv_columns_missing, csv_no_numeric_rows,
            or csv_time_not_increasing.
    """
    if len(text) > MAX_CSV_CHARS:
        raise ValveInputError(
            "csv_too_large", f"CSV text is {len(text)} characters; the maximum is {MAX_CSV_CHARS}"
        )
    text = text.lstrip("\ufeff")
    delimiter = _sniff_delimiter(text)
    reader = _reader(text, delimiter)

    rows: list[list[str]] = list(reader)
    if not rows:
        raise ValveInputError("csv_no_numeric_rows", "CSV contains no rows")

    header, data_rows = _split_header(rows, delimiter)
    column_indices = _resolve_columns(
        header, len(data_rows[0]) if data_rows else len(rows[0]), columns
    )
    t_seconds, op_values, pv_values = _parse_rows(data_rows, delimiter, column_indices)

    if len(t_seconds) < MIN_RECORD_SAMPLES:
        raise ValveInputError(
            "csv_no_numeric_rows",
            f"only {len(t_seconds)} usable rows; at least {MIN_RECORD_SAMPLES} are required",
        )
    if not np.all(np.diff(t_seconds) > 0):
        raise ValveInputError("csv_time_not_increasing", "time values must be strictly increasing")
    # Convert absolute timestamps (epoch seconds or ISO datetimes) to seconds since the first row.
    t_seconds = [value - t_seconds[0] for value in t_seconds]
    return (
        np.asarray(t_seconds, dtype=float),
        np.asarray(op_values, dtype=float),
        np.asarray(pv_values, dtype=float),
    )


def _sniff_delimiter(text: str) -> str:
    """Pick the delimiter with the most occurrences in the first non-empty line."""
    first_line = next((line for line in text.splitlines() if line), "")
    counts = {delim: first_line.count(delim) for delim in CSV_DELIMITERS}
    max_count = max(counts.values())
    if max_count == 0:
        return CSV_DELIMITERS[0]  # no clear delimiter; default to ";" (most common in EU CSVs)
    # On ties, the first delimiter in CSV_DELIMITERS wins (defined preference order).
    return next(delim for delim in CSV_DELIMITERS if counts[delim] == max_count)


def _reader(text: str, delimiter: str) -> Iterator[list[str]]:
    """A csv.reader over the text with the chosen delimiter."""
    return csv.reader(io.StringIO(text), delimiter=delimiter)


def _split_header(
    rows: list[list[str]], delimiter: str
) -> tuple[list[str] | None, list[list[str]]]:
    """Split rows into (header, data_rows); the first row is a header if not all numeric."""
    if not rows:
        return None, rows
    first_row = rows[0]
    has_header = any(not _is_number(cell, delimiter) for cell in first_row)
    if has_header:
        return first_row, rows[1:]
    return None, rows


def _resolve_columns(
    header: list[str] | None,
    row_width: int,
    columns: Mapping[str, str] | None,
) -> tuple[int, int, int]:
    """Return (t_index, op_index, pv_index) based on header names or positions.

    Raises ValveInputError("csv_columns_missing") when no usable columns are found.
    """
    if columns is not None:
        t_name, op_name, pv_name = columns.get("t"), columns.get("op"), columns.get("pv")
        if any(name is None for name in (t_name, op_name, pv_name)):
            raise ValveInputError(
                "csv_columns_missing", "columns must have t, op and pv keys", "columns"
            )
        indices = _find_header_indices(header, row_width, t_name, op_name, pv_name)
        if indices is None:
            raise ValveInputError(
                "csv_columns_missing",
                f"named columns {t_name}, {op_name}, {pv_name} not found in header {header}",
                "columns",
            )
        return indices

    if header is not None:
        # Auto-detect by common header names.
        t_candidates = ("t", "time", "t_s", "seconds")
        op_candidates = ("op", "out", "output", "mv")
        pv_candidates = ("pv",)
        indices = _find_header_candidates(
            header, row_width, t_candidates, op_candidates, pv_candidates
        )
        if indices is not None:
            return indices

    # Fallback to positions 0, 1, 2.
    if row_width >= 3:
        return 0, 1, 2
    raise ValveInputError(
        "csv_columns_missing",
        f"could not determine t, op, pv columns from header {header} or positions; "
        f"provide columns mapping or use at least 3 columns",
        "columns",
    )


def _find_header_indices(
    header: list[str] | None,
    row_width: int,
    t_name: str | None,
    op_name: str | None,
    pv_name: str | None,
) -> tuple[int, int, int] | None:
    """Find exact (case-insensitive) header names, or None."""
    if header is None or t_name is None or op_name is None or pv_name is None:
        return None
    lowered = [cell.strip().lower() for cell in header]
    try:
        t_idx = lowered.index(t_name.lower())
        op_idx = lowered.index(op_name.lower())
        pv_idx = lowered.index(pv_name.lower())
    except ValueError:
        return None
    return t_idx, op_idx, pv_idx


def _find_header_candidates(
    header: list[str],
    row_width: int,
    t_candidates: tuple[str, ...],
    op_candidates: tuple[str, ...],
    pv_candidates: tuple[str, ...],
) -> tuple[int, int, int] | None:
    """Find the first header cell matching each candidate group (case-insensitive), or None."""
    lowered = [cell.strip().lower() for cell in header]

    def find_first(candidates: tuple[str, ...]) -> int | None:
        for i, cell in enumerate(lowered):
            if cell in candidates:
                return i
        return None

    t_idx = find_first(t_candidates)
    op_idx = find_first(op_candidates)
    pv_idx = find_first(pv_candidates)
    if t_idx is None or op_idx is None or pv_idx is None:
        return None
    return t_idx, op_idx, pv_idx


def _parse_rows(
    rows: list[list[str]], delimiter: str, column_indices: tuple[int, int, int]
) -> tuple[list[float], list[float], list[float]]:
    """Parse data rows into (t_seconds, op_values, pv_values); skip rows with errors."""
    t_seconds: list[float] = []
    op_values: list[float] = []
    pv_values: list[float] = []
    t_idx, op_idx, pv_idx = column_indices

    for row in rows:
        if len(row) <= max(t_idx, op_idx, pv_idx):
            continue
        t_raw, op_raw, pv_raw = row[t_idx], row[op_idx], row[pv_idx]
        t_value = _parse_time(t_raw)
        op_value = _parse_number(op_raw, delimiter)
        pv_value = _parse_number(pv_raw, delimiter)
        if t_value is None or op_value is None or pv_value is None:
            continue
        t_seconds.append(t_value)
        op_values.append(op_value)
        pv_values.append(pv_value)
    return t_seconds, op_values, pv_values


def _parse_number(value: str, delimiter: str) -> float | None:
    """Parse a numeric cell to float or None; a decimal comma is allowed unless delimiter is ","."""
    cleaned = value.strip()
    if not cleaned:
        return None
    if delimiter != ",":
        cleaned = cleaned.replace(",", ".")
    try:
        number = float(cleaned)
    except ValueError:
        return None
    if not np.isfinite(number):
        return None
    return number


def _parse_time(value: str) -> float | None:
    """Parse a time cell as numeric seconds or ISO-8601 datetime; returns seconds or None."""
    cleaned = value.strip()
    if not cleaned:
        return None
    # Numeric seconds (possibly with decimal comma when delimiter is not comma).
    for candidate in (cleaned, cleaned.replace(",", ".")):
        try:
            number = float(candidate)
            if np.isfinite(number):
                return number
        except ValueError:
            pass
    # ISO-8601 datetime; a trailing Z is UTC and Python replaces it with +00:00.
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(cleaned).timestamp()
    except ValueError:
        return None


def _is_number(cell: str, delimiter: str) -> bool:
    """True when the cell parses as a finite number."""
    return _parse_number(cell, delimiter) is not None
