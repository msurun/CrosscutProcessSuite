"""Generate messy CSV files for testing.

The messy CSV files are generated to test the robustness of the CSV import functionality.
The module provides a function to generate CSV files with different styles of messiness.
"""

from __future__ import annotations

import datetime
import zoneinfo
from collections.abc import Callable

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
    """Render a float for display in a CSV-like text file.

    The caller decides the convention: `decimal_comma` selects the locale used by
    most of Europe (where the decimal mark is a comma), while the default is the
    dot used in English-speaking locales.

    Returns the number as text, or "" when `value` is NaN. An empty string is used
    on purpose: NaN means "no value", and writing "nan" would be read back as text
    rather than as a missing number.
    """
    # NaN is the only value for which `value == value` is False, so this check
    # reliably identifies missing measurements (no "nan" text is written).
    if np.isnan(value):
        return ""

    # repr() gives the shortest text that round-trips back to the exact same
    # float. str() would do the same, so either is safe here; we use repr() only
    # to make the intent explicit.
    formatted = repr(float(value))

    # No thousands separators are used, so the only dot in a decimal number is
    # its decimal mark; replacing that dot with a comma applies the locale change.
    if decimal_comma:
        formatted = formatted.replace(".", ",")
    return formatted


def _get_bad_value(index: int) -> str:
    """Get a bad value based on the index."""
    bad_values = ["Bad", "I/O Timeout", "#N/A"]
    return bad_values[index % len(bad_values)]


def _render_plain(ts_ns: np.ndarray, columns: dict[str, np.ndarray]) -> bytes:
    """Render plain CSV with comma delimiter and ISO-8601 UTC timestamps.

    This is the human-readable output format (as opposed to a binary/compressed
    one): one text line per sample, a header line naming the timestamp and each
    signal column, and every row starting with that sample's timestamp.

    The rows are assembled by positional index rather than by joining arrays
    column-wise, so every column array is assumed to be the same length as
    ``ts_ns`` (a "ragged" input is silently truncated to the shortest array).

    Args:
        ts_ns: Sample timestamps, in nanoseconds since the Unix epoch (UTC).
        columns: Signal name -> values, one value per timestamp. Insertion
            order is preserved; the header and every row follow it.

    Returns:
        The CSV text encoded as UTF-8, ready to be written to disk.
    """
    # The header reuses the dict's own key order so header names and value
    # positions can never drift apart.
    header = "timestamp," + ",".join(columns.keys()) + "\n"
    # Build the full output as a list of lines and join once: repeatedly
    # appending to a string with += would be O(n^2) for this growing buffer.
    lines = [header]
    for i in range(len(ts_ns)):
        # Epoch nanoseconds -> ISO-8601 UTC string ending in 'Z' (microsecond precision).
        timestamp = _format_timestamp_iso_utc(ts_ns[i])
        values = [timestamp]
        for col in columns.values():
            # False asks _format_float to keep the dot as decimal separator (plain style).
            values.append(_format_float(col[i], False))
        lines.append(",".join(values) + "\n")
    return "".join(lines).encode("utf-8")


def _render_semicolon_comma(
    ts_ns: np.ndarray, columns: dict[str, np.ndarray], local_tz: str
) -> bytes:
    """Render CSV with semicolon delimiter, decimal comma, and local time timestamps.

    This is the "European" CSV dialect: ';' separates fields (so that the decimal comma
    ',' inside a number can never be mistaken for a column boundary), and floats are
    written with a comma decimal separator, e.g. ``3,5`` instead of ``3.5``.

    Args:
        ts_ns: Timestamps in nanoseconds since the Unix epoch (UNIX time, int64).
        columns: Column name -> one value per row; every array must be as long as ts_ns.
        local_tz: IANA time zone name (e.g. "Europe/Paris") used to convert timestamps.

    Returns:
        The whole file as UTF-8 encoded bytes, ready to be written to disk.
    """
    # Header row: first field is the timestamp column, then one field per data column.
    header = "timestamp;" + ";".join(columns.keys()) + "\n"
    # Build the full output as a list of lines and join once: repeated str
    # concatenation with += would be O(n^2).
    lines = [header]
    # One loop iteration builds one row of the CSV, in the order the columns were given.
    for i in range(len(ts_ns)):
        timestamp = _format_timestamp_semicolon_comma(ts_ns[i], local_tz)
        values = [timestamp]
        for col in columns.values():
            # True asks _format_float to use a comma as decimal separator (this dialect).
            values.append(_format_float(col[i], True))
        lines.append(";".join(values) + "\n")
    return "".join(lines).encode("utf-8")


def _render_tab_local(ts_ns: np.ndarray, columns: dict[str, np.ndarray], local_tz: str) -> bytes:
    """Render CSV with tab delimiter and local time timestamps.

    Each row is one sample in time: the timestamp followed by the column values.
    All arrays are positionally aligned, so row ``i`` pairs ``ts_ns[i]`` with
    ``columns[name][i]`` for every column name.

    Columns are assumed to hold floats; timestamps are nanosecond UTC and are
    converted to ``local_tz`` for readability.

    Returns the whole CSV document as UTF-8 encoded bytes (a bytes object, not
    a str, so callers can write it straight to a file or socket).
    """
    # Tab-separated header: a fixed "timestamp" label first, then the column
    # names in their dict insertion order. The trailing "\n" ends the header row.
    header = "timestamp\t" + "\t".join(columns.keys()) + "\n"
    # Build the full output as a list of lines and join once: repeated
    # string concatenation with += would be O(n^2).
    lines = [header]
    # One iteration per sample. Every column array has the same length as
    # ts_ns (invariant guaranteed by the caller).
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
    """Render plain CSV with missing values replaced by bad values.

    Used as the fallback when a file must be written in a plain-CSV format
    that cannot represent "no data" natively. Every NaN is instead replaced
    by a distinct placeholder string taken from the cyclical sequence
    ``_get_bad_value``, so each missing cell is individually traceable.

    Args:
        ts_ns: 1-D array of timestamps, as integers, in NANOSECONDS since
            the Unix epoch (not seconds -- the ``_ns`` suffix says so).
        columns: ordered mapping of column name to its value array. All
            arrays share the same length as ``ts_ns`` and hold float64;
            NaN marks a missing measurement. Dict insertion order defines
            the column order in the output, so it matters.

    Returns:
        The complete CSV document encoded as UTF-8 bytes, including a
        trailing newline after every row.

    Side effects:
        Calls ``_get_bad_value(bad_count)``, which is stateful: it returns
        successive placeholders as its counter advances. ``bad_count`` is
        therefore a single stream of indices spanning all columns and rows,
        not a per-column counter.
    """
    header = "timestamp," + ",".join(columns.keys()) + "\n"
    lines = [header]
    # Running index handed to _get_bad_value; counts every NaN emitted so far
    # across the whole file, so no two missing cells share a placeholder.
    bad_count = 0
    for i in range(len(ts_ns)):
        timestamp = _format_timestamp_iso_utc(ts_ns[i])
        values = [timestamp]
        for col in columns.values():
            # np.isnan is the only reliable NaN test because NaN != NaN is
            # always True; a direct equality comparison would never fire.
            if np.isnan(col[i]):
                values.append(_get_bad_value(bad_count))
                bad_count += 1
            else:
                # False selects the default float formatting; decimal commas are
                # not used in this style.
                values.append(_format_float(col[i], False))
        lines.append(",".join(values) + "\n")
    return "".join(lines).encode("utf-8")


def _render_duplicates_unsorted(ts_ns: np.ndarray, columns: dict[str, np.ndarray]) -> bytes:
    """Render plain CSV with rows 10..14 duplicated and shuffled.

    Builds a small in-memory CSV file used as a test fixture: the rows are
    written in order, then every row whose 0-based index falls in 10..14 is
    written a second time, and finally the data rows are randomly reordered
    with a fixed seed so the output is unsorted but reproducible.

    Args:
        ts_ns: 1-D array of timestamps, in nanoseconds since the Unix epoch (ns).
        columns: Mapping of column name to 1-D array of float values; every
            array must have the same length as ``ts_ns``.

    Returns:
        The whole CSV file as UTF-8 encoded bytes.
    """
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
    # Generate a random permutation of the data-row positions.
    # Seeded with 0 so the output is byte-for-byte identical on every run.
    shuffled_indices = np.random.default_rng(0).permutation(len(lines) - 1)
    # The header (lines[0]) stays first; data rows follow in shuffled order.
    # Index i + 1 skips over the header in ``lines``.
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

    "Messy" means the output deliberately violates common CSV conventions
    (odd separators, shuffled rows, duplicated records, byte-order marks, ...)
    so that a parser can be tested against realistic, badly-behaved input.

    Args:
        ts_ns: Array of timestamps in nanoseconds (UNIX epoch, UTC).
        columns: Dictionary mapping column names to arrays of values. Every
            array has the same length as ``ts_ns``; row ``i`` is the ``i``-th
            element of each array.
        style: Style of the messy CSV, e.g. ``"plain"`` or ``"duplicates"``.
        local_tz: Local time zone used when an eye-readable timestamp is
            rendered; ignored by styles that keep raw epoch values.

    Returns:
        Bytes of the generated CSV file (UTF-8 unless the style adds another
        encoding on purpose).

    Raises:
        ValueError: If the style is unknown.
    """
    renderer = _select_renderer(style)

    # Plain, BOM-preamble and text-bad renderers never interpret a
    # timestamp, so they need only the numeric arrays.
    if (
        renderer is _render_plain
        or renderer is _render_bom_preamble
        or renderer is _render_text_bad
    ):
        return renderer(ts_ns, columns)

    # The duplicates_unsorted renderer writes formatted timestamps and
    # uses no time zone, so it also takes only the numeric arrays.
    if renderer is _render_duplicates_unsorted:
        return renderer(ts_ns, columns)

    return renderer(ts_ns, columns, local_tz)


def _select_renderer(style: str) -> Callable[..., bytes]:
    """Return the renderer function matching the style.

    A "renderer" is a function that turns some in-memory data into the exact
    bytes of one dialect of a delimited text file (CSV and its lookalikes:
    different delimiter, quoting, preamble or column order). The style name is
    the key that picks which dialect we are pretending to write.

    Available styles:
        plain                - standard comma-separated output.
        semicolon_comma      - semicolons between fields but commas inside them.
        tab_local            - tab-delimited, as spreadsheet "export local" does.
        bom_preamble         - byte-order-mark first, then the plain body.
        text_bad             - a deliberately malformed file (bad quoting).
        duplicates_unsorted  - header/rows not sorted, with repeated keys.

    Args:
        style: One of the style names listed above.

    Returns:
        The renderer function for that style, ready to be called.

    Raises:
        ValueError: If the style is unknown.
    """
    # Lookup table maps style names to renderers. It is local to this
    # function, so callers cannot alter it; unknown names raise KeyError.
    renderers: dict[str, Callable[..., bytes]] = {
        "plain": _render_plain,
        "semicolon_comma": _render_semicolon_comma,
        "tab_local": _render_tab_local,
        "bom_preamble": _render_bom_preamble,
        "text_bad": _render_text_bad,
        "duplicates_unsorted": _render_duplicates_unsorted,
    }
    try:
        return renderers[style]
    # Unknown style. Convert KeyError to ValueError with a clear message;
    # from None hides the internal dict lookup from the traceback.
    except KeyError:
        raise ValueError(f"Unknown style: {style}") from None
