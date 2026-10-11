"""Generate messy CSV files for testing.

The messy CSV files are generated to test the robustness of the CSV import functionality.
The module provides a function to generate CSV files with different styles of messiness.
"""

from __future__ import annotations

import datetime
import zoneinfo

import numpy as np

STYLES: tuple[str, ...] = (
    "plain",
    "semicolon_comma",
    "tab_local",
    "bom_preamble",
    "text_bad",
    "duplicates_unsorted",
)


def _format_timestamp_iso_utc(ts_ns: int) -> str:
    """Format timestamp in nanoseconds as ISO-8601 UTC string."""
    dt = datetime.datetime.fromtimestamp(ts_ns / 1e9, tz=datetime.UTC)
    return dt.isoformat().replace("+00:00", "Z")


def _format_timestamp_local(ts_ns: int, local_tz: str) -> str:
    """Format timestamp in nanoseconds as local time string."""
    dt = datetime.datetime.fromtimestamp(ts_ns / 1e9, tz=datetime.UTC)
    local_dt = dt.astimezone(zoneinfo.ZoneInfo(local_tz))
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def _format_timestamp_semicolon_comma(ts_ns: int, local_tz: str) -> str:
    """Format timestamp in nanoseconds as local time string with dd.mm.yyyy format."""
    dt = datetime.datetime.fromtimestamp(ts_ns / 1e9, tz=datetime.UTC)
    local_dt = dt.astimezone(zoneinfo.ZoneInfo(local_tz))
    return local_dt.strftime("%d.%m.%Y %H:%M:%S")


def _format_float(value: float, decimal_comma: bool) -> str:
    """Format float value with or without decimal comma."""
    if np.isnan(value):
        return ""
    formatted = repr(float(value))
    if decimal_comma:
        formatted = formatted.replace(".", ",")
    return formatted


def _get_bad_value(index: int) -> str:
    """Get a bad value based on the index."""
    bad_values = ["Bad", "I/O Timeout", "#N/A"]
    return bad_values[index % len(bad_values)]


def _render_plain(ts_ns: np.ndarray, columns: dict[str, np.ndarray]) -> bytes:
    """Render plain CSV with comma delimiter and ISO-8601 UTC timestamps."""
    header = "timestamp," + ",".join(columns.keys()) + "\n"
    lines = [header]
    for i in range(len(ts_ns)):
        timestamp = _format_timestamp_iso_utc(ts_ns[i])
        values = [timestamp]
        for col in columns.values():
            values.append(_format_float(col[i], False))
        lines.append(",".join(values) + "\n")
    return "".join(lines).encode("utf-8")


def _render_semicolon_comma(
    ts_ns: np.ndarray, columns: dict[str, np.ndarray], local_tz: str
) -> bytes:
    """Render CSV with semicolon delimiter, decimal comma, and local time timestamps."""
    header = "timestamp;" + ";".join(columns.keys()) + "\n"
    lines = [header]
    for i in range(len(ts_ns)):
        timestamp = _format_timestamp_semicolon_comma(ts_ns[i], local_tz)
        values = [timestamp]
        for col in columns.values():
            values.append(_format_float(col[i], True))
        lines.append(";".join(values) + "\n")
    return "".join(lines).encode("utf-8")


def _render_tab_local(ts_ns: np.ndarray, columns: dict[str, np.ndarray], local_tz: str) -> bytes:
    """Render CSV with tab delimiter and local time timestamps."""
    header = "timestamp\t" + "\t".join(columns.keys()) + "\n"
    lines = [header]
    for i in range(len(ts_ns)):
        timestamp = _format_timestamp_local(ts_ns[i], local_tz)
        values = [timestamp]
        for col in columns.values():
            values.append(_format_float(col[i], False))
        lines.append("\t".join(values) + "\n")
    return "".join(lines).encode("utf-8")


def _render_bom_preamble(ts_ns: np.ndarray, columns: dict[str, np.ndarray]) -> bytes:
    """Render plain CSV with UTF-8 BOM and three junk lines before the header."""
    bom = b"\xef\xbb\xbf"
    junk_lines = ["Historian export\n", "Server: HIST01, node 2\n", "\n"]
    csv_content = _render_plain(ts_ns, columns)
    return bom + "".join(junk_lines).encode("utf-8") + csv_content


def _render_text_bad(ts_ns: np.ndarray, columns: dict[str, np.ndarray]) -> bytes:
    """Render plain CSV with missing values replaced by bad values."""
    header = "timestamp," + ",".join(columns.keys()) + "\n"
    lines = [header]
    bad_count = 0
    for i in range(len(ts_ns)):
        timestamp = _format_timestamp_iso_utc(ts_ns[i])
        values = [timestamp]
        for col in columns.values():
            if np.isnan(col[i]):
                values.append(_get_bad_value(bad_count))
                bad_count += 1
            else:
                values.append(_format_float(col[i], False))
        lines.append(",".join(values) + "\n")
    return "".join(lines).encode("utf-8")


def _render_duplicates_unsorted(ts_ns: np.ndarray, columns: dict[str, np.ndarray]) -> bytes:
    """Render plain CSV with rows 10..14 duplicated and shuffled."""
    header = "timestamp," + ",".join(columns.keys()) + "\n"
    lines = [header]
    for i in range(len(ts_ns)):
        timestamp = _format_timestamp_iso_utc(ts_ns[i])
        values = [timestamp]
        for col in columns.values():
            values.append(_format_float(col[i], False))
        lines.append(",".join(values) + "\n")
        if 10 <= i <= 14:
            lines.append(",".join(values) + "\n")
    shuffled_indices = np.random.default_rng(0).permutation(len(lines) - 1)
    shuffled_lines = [lines[0]] + [lines[i + 1] for i in shuffled_indices]
    return "".join(shuffled_lines).encode("utf-8")


def render_messy_csv(
    ts_ns: np.ndarray,
    columns: dict[str, np.ndarray],
    style: str,
    *,
    local_tz: str = "Europe/Warsaw",
) -> bytes:
    """Generate a messy CSV file with the specified style.

    Args:
        ts_ns: Array of timestamps in nanoseconds.
        columns: Dictionary mapping column names to arrays of values.
        style: Style of the messy CSV.
        local_tz: Local time zone for timestamp formatting.

    Returns:
        Bytes of the generated CSV file.

    Raises:
        ValueError: If the style is unknown.
    """
    if style == "plain":
        return _render_plain(ts_ns, columns)
    elif style == "semicolon_comma":
        return _render_semicolon_comma(ts_ns, columns, local_tz)
    elif style == "tab_local":
        return _render_tab_local(ts_ns, columns, local_tz)
    elif style == "bom_preamble":
        return _render_bom_preamble(ts_ns, columns)
    elif style == "text_bad":
        return _render_text_bad(ts_ns, columns)
    elif style == "duplicates_unsorted":
        return _render_duplicates_unsorted(ts_ns, columns)
    else:
        raise ValueError(f"Unknown style: {style}")
