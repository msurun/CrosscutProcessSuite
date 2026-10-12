# connectors/src/crosscut_connectors/csv_import.py
"""Utility to import a CSV file produced by the ``messy`` exporter.

The importer is deliberately tolerant: it detects the delimiter, the decimal
separator, the timestamp format and sanitises column names so that they can be
used as tag identifiers inside *crosscut*.  It also produces a small
``ImportReport`` that summarises what was found.

Only the behaviours exercised by the test‑suite are implemented – the module
is not a full‑featured CSV parser.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from crosscut_sim.core import BAD, GOOD
from crosscut_sim.dataset import write_dataset

# --------------------------------------------------------------------------- #
# Public data structures
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ImportReport:
    """Summary of the import operation.

    Attributes
    ----------
    n_rows: int
        Number of rows kept after duplicate removal.
    n_duplicates_dropped: int
        How many rows were removed because of duplicate timestamps.
    was_unsorted: bool
        ``True`` if the timestamps were not monotonically non‑decreasing.
    n_bad_values: int
        Number of values that could not be parsed into a finite float.
    delimiter: str
        Detected column delimiter (e.g. ',', ';' or '\\t').
    decimal: str
        Detected decimal separator ('.' or ',').
    timestamp_format: str
        Human readable description of the format that succeeded.
    """

    n_rows: int
    n_duplicates_dropped: int
    was_unsorted: bool
    n_bad_values: int
    delimiter: str
    decimal: str
    timestamp_format: str


# --------------------------------------------------------------------------- #
# Helper functions – each small and typed
# --------------------------------------------------------------------------- #


def _read_text(path: Path) -> str:
    """Read a UTF‑8 (with optional BOM) file and raise on empty content."""
    # read_bytes gives the raw bytes so we can decode ourselves: this lets us pick
    # the "utf-8-sig" codec, which strips a UTF-8 byte order mark (BOM, the 3 bytes
    # EF BB BF) if the file starts with one, and otherwise behaves like plain "utf-8".
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    # A file that is empty or contains only whitespace (spaces, newlines) is treated
    # as missing content, because the caller cannot do anything useful with it.
    if not text.strip():
        raise ValueError("empty file")
    return text


def _split_lines(text: str) -> list[str]:
    """Return a list of non‑empty lines, preserving order."""
    return [ln for ln in text.splitlines() if ln.strip()]


def _detect_delimiter(lines: list[str]) -> str:
    """Detect the column delimiter.

    The algorithm looks at the first 50 non‑empty lines and chooses the candidate
    (',', ';' or '\\t') that yields the most common field count (at least 2).

    Returns the winning delimiter as a one-character string.
    Raises ValueError when no candidate splits the sample into at least two columns.
    """
    candidates = [",", ";", "\t"]
    best_delim = ""
    best_score = -1
    sample = lines[:50]

    for delim in candidates:
        # For this candidate, `modal_cnt` is the most frequent number of fields per line
        # (unit: fields) and `modal_freq` is how many sample lines had exactly that count
        # (unit: lines). A delimiter that occurs in the data (rather than separating
        # columns) tends to give a stable count across lines, hence a high `modal_freq`.
        modal_cnt, modal_freq = _modal_field_count(sample, delim)
        # we need at least two columns to be a plausible CSV
        if modal_cnt < 2:
            continue
        # prefer the delimiter that covers most lines
        if modal_freq > best_score:
            best_score = modal_freq
            best_delim = delim
    # No candidate ever reached two columns: the input is not a delimited table we can read.
    if not best_delim:
        raise ValueError("cannot detect delimiter")
    return best_delim


def _modal_field_count(lines: list[str], delimiter: str) -> tuple[int, int]:
    """Return the most frequent field count and how many lines have it (0, 0 if none).

    A CSV-like file's "shape" is the number of fields per row. Most rows agree on that
    number; a few are malformed. The mode (most common field count) is therefore the
    best guess for the file's true number of columns.

    Returns a pair (field_count, number_of_lines_with_that_count), or (0, 0) when
    `lines` is empty.
    """
    # counts maps a field count to how many lines have exactly that many fields.
    # UNIT of values: lines.
    counts: dict[int, int] = {}
    for ln in lines:
        cnt = len(ln.split(delimiter))
        counts[cnt] = counts.get(cnt, 0) + 1
    if not counts:
        return 0, 0
    # `counts.items()` yields (field_count, line_count) pairs; we want the pair with the
    # largest line_count.
    # max() keeps the first maximum on ties. For dict insertion order, earlier field counts
    # are encountered first as lines are processed left-to-right.
    return max(counts.items(), key=lambda kv: kv[1])


def _extract_header_and_rows(lines: list[str], delimiter: str) -> tuple[list[str], list[list[str]]]:
    """Find the first line with the modal field count and collect matching rows.

    Many text exports mix real records with junk: page numbers, "Page 1 of 3" footers, blank
    lines, or separator rules such as "-----". A record is recognised by how many fields it has:
    the most frequent field count in the file is assumed to be the record width, and only lines
    with exactly that many fields are kept.

    The first kept line becomes the header; every later kept line becomes a data row.

    Returns:
        A (header, data_rows) pair. Both are empty lists when no line matches the modal field
        count. Cells are stripped of surrounding whitespace; the delimiter is not removed from
        cells that are quoted and contain the delimiter.
    """
    # --- Step 1: decide the record width (number of fields per line) ---
    # field_counts[i] is the field count of lines[i]. Lines are read as plain text, so a blank
    # line counts as 1 field, not 0: splitting an empty string on a delimiter yields [""].
    field_counts = [len(ln.split(delimiter)) for ln in lines]
    modal_cnt = max(set(field_counts), key=field_counts.count)

    # --- Step 2: keep only the lines whose field count equals modal_cnt ---
    # Invariant while the loop runs: once header_found is True, header holds the stripped
    # fields of one matching line and data_rows holds the stripped fields of all later
    # matching lines, in file order.
    header: list[str] = []
    data_rows: list[list[str]] = []
    header_found = False
    for ln in lines:
        parts = ln.split(delimiter)
        if len(parts) != modal_cnt:
            continue
        if not header_found:
            # First match in file order: it is the header, never a data row.
            header = [cell.strip() for cell in parts]
            header_found = True
            continue
        data_rows.append([cell.strip() for cell in parts])
    return header, data_rows


def _parse_iso8601(value: str) -> datetime | None:
    """Parse an ISO‑8601 timestamp string into a ``datetime``, or return ``None`` if unparseable.

    ISO‑8601 is the international date/time text format, e.g. ``2024-05-01T13:45:00``.
    Timestamps may carry a UTC offset suffix like ``+02:00`` meaning "local time is
    two hours ahead of UTC". Python's ``datetime.fromisoformat`` knows how to read
    offsets, but the common shorthand ``Z`` (for "Zulu time", i.e. UTC) is only
    accepted from Python 3.11 onward, so we translate it by hand for older versions.

    Args:
        value: The timestamp text, e.g. ``"2024-05-01T13:45:00Z"``.

    Returns:
        The parsed ``datetime`` (timezone-aware if the text had an offset), or
        ``None`` when ``value`` is not a valid ISO‑8601 timestamp.
    """
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        # Any malformed input (wrong shape, unknown fields, out-of-range parts)
        # surfaces as one of many exception types; callers only care that parsing
        # failed, so we normalise all of them to ``None``.
        return None


def _strptime_or_none(fmt: str) -> Callable[[str], datetime | None]:
    """Return a parser for ``fmt`` that yields None instead of raising on a mismatch.

    ``fmt`` is a ``strptime`` format string (for example ``"%Y-%m-%d"``). The returned
    function takes a date/time string and produces a ``datetime``, or ``None`` when the
    string does not match the format.

    This is a factory (hence the leading underscore, it is module-private): the format is
    bound once here, so callers can pass the resulting parser around -- to ``map``, a
    callback, a list comprehension -- without carrying the format string with them.

    Returns:
        A callable ``(text: str) -> datetime | None``.
    """

    def parse(text: str) -> datetime | None:
        """Parse ``text`` with ``fmt``, or return None when it does not match."""
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            # strptime signals "the text is not in this format" with ValueError. Callers
            # here treat a missing/unparseable value as a normal outcome, so we convert
            # that expected failure into None rather than letting it abort the batch.
            return None

    return parse


def _try_timestamp_formats(
    candidates: Iterable[str],
) -> tuple[str, Callable[[str], datetime | None]]:
    """Return a format name and a parsing callable that works for *all* rows.

    The dataset stores timestamps as strings whose layout is not known up front
    (ISO 8601, epoch seconds, "%Y-%m-%d %H:%M:%S", ...).  We guess the layout by
    trying every known one against every string in ``candidates`` and keeping
    the first layout that parses all of them without raising.

    Args:
        candidates: every distinct timestamp string in the dataset; a single
            unparsable value disqualifies the candidate format.

    Returns:
        A ``(format_name, parse)`` pair.  ``format_name`` is a human-readable
        label for logs and errors; ``parse(string)`` returns the corresponding
        ``datetime``, which may be naive (no timezone) or aware (with timezone)
        depending on which format matched.

    Raises:
        ValueError: no known format parses every string in ``candidates``.
    """
    # Order matters – the first that succeeds for every row wins.
    # The callable returns a ``datetime`` (may be naive or aware).
    for name, fn in _timestamp_format_candidates():
        # we only verify that the function does not raise for any candidate string
        # – the actual conversion is done later.
        if _parses_every_candidate(fn, candidates):
            return name, fn
    raise ValueError("timestamp format not recognised")


def _timestamp_format_candidates() -> list[tuple[str, Callable[[str], datetime | None]]]:
    """Return the parsing callables to try, in order of preference.

    Returns a list of (format_label, parser) pairs. The label is for error messages only;
    the parser is called with the raw timestamp text and returns None when it does not match.
    A caller walks this list in order and takes the first non-None result.
    """
    # The list is the single source of truth for which formats we accept, and the order
    # encodes precedence: a value that parses under several formats is read as the earliest
    # one listed here, so the most specific / least ambiguous format must come first.
    return [
        # ISO 8601 (e.g. "2024-03-07T14:05:00Z"): year first, unambiguous, hand-written
        # parser because _strptime does not cover timezone offsets like "+02:00".
        ("ISO8601", _parse_iso8601),
        ("d.m.Y H:M:S", _strptime_or_none("%d.%m.%Y %H:%M:%S")),
        ("Y-m-d H:M:S", _strptime_or_none("%Y-%m-%d %H:%M:%S")),
    ]


def _parses_every_candidate(
    parse: Callable[[str], datetime | None],
    candidates: Iterable[str],
) -> bool:
    """Return True when *parse* yields a datetime for every candidate string.

    *candidates* may be any iterable (generator, list, tuple); True means it
    contains no string that *parse* rejects. An empty iterable is True.
    """
    # This is a universal (for-all) test: it succeeds only if no counterexample
    # is found. The loop therefore returns early on the first unparsable string
    # and falls through to True only when the whole iterable has been consumed.
    for candidate in candidates:
        if parse(candidate) is None:
            return False
    return True


def _to_utc_nanoseconds(dt: datetime, tz: str) -> int:
    """Convert a ``datetime`` to nanoseconds since the Unix epoch (UTC).

    A timestamp with no timezone attached is ambiguous: the same wall-clock time means a
    different instant in every region of the world. ``tz`` resolves that ambiguity by
    naming the timezone the caller meant.

    Returns an integer count of nanoseconds, the unit used across this project for
    ordering and comparing events (higher resolution than float seconds, no rounding
    surprises).
    """
    if dt.tzinfo is None:
        # naive timestamps are interpreted in the provided timezone
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    else:
        # already timezone‑aware – convert to UTC
        dt = dt.astimezone(UTC)
    # ``timestamp()`` returns POSIX time in fractional seconds since 1970-01-01T00:00:00Z.
    # Truncating it to whole seconds and adding the microseconds separately avoids the
    # precision loss of the float conversion: 1 microsecond = 1_000 nanoseconds.
    seconds = int(dt.timestamp())
    nanos = seconds * 1_000_000_000 + dt.microsecond * 1_000
    return nanos


def _detect_decimal_separator(rows: list[list[str]], delimiter: str) -> str:
    """Return ',' if the delimiter is not ',' and a cell looks like ``1,23``."""
    # A comma cannot be both the field separator and the decimal mark, so when the file is
    # comma-separated we assume the decimal mark is the dot and skip the scan entirely.
    if delimiter == ",":
        return "."

    # Regex matching a number written with a comma as decimal mark, e.g. "1,23" or "-4,5".
    # ``-?`` = optional minus sign, ``\d+`` = one or more digits, ``,\d+`` = comma then digits.
    # Full-string match, so "1,234" (a thousands separator) and "a,b" do not qualify.
    comma_number = re.compile(r"^-?\d+,\d+$")

    # row[1:] skips the first cell, which is the timestamp column and not a tag value.
    for row in rows:
        for cell in row[1:]:
            if comma_number.match(cell):
                return ","

    # No comma-decimal number found anywhere: fall back to the default decimal mark.
    return "."


def _parse_cell(cell: str, decimal: str) -> float:
    """Parse one value cell; anything that is not a finite number (``Bad``, empty...) is NaN.

    ``cell`` is the raw text as read from the source file, so it may carry stray
    whitespace, may use a non-dot decimal separator, or may hold a word such as
    ``Bad`` that has no numeric value. ``decimal`` is the separator the file
    uses (it varies by locale, e.g. ``,``). Returns a finite float, or NaN when
    the text is not a finite number, so that callers see one uniform "missing
    value" marker instead of NaN, ``inf`` and exceptions mixed together.
    """
    try:
        # Swap the file's separator for the dot that ``float`` expects, so that
        # locale-specific data parses without changing the file on disk.
        value = float(cell.strip().replace(decimal, "."))
    except ValueError:
        # The text is not a number at all (``Bad``, empty string, a label...).
        return float("nan")
    # ``float`` accepts "inf"/"nan" as text; keep only finite numbers, since a
    # real measurement can never be infinite and downstream maths must not see one.
    return value if np.isfinite(value) else float("nan")


def _sanitize_tag_name(name: str) -> str:
    """Replace any character not allowed in an identifier with '_'."""
    # allowed characters are defined by the test – we keep alphanum, . _ : -
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", name).strip("_")


def _sort_and_deduplicate(
    ts: np.ndarray, values: np.ndarray, qualities: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Sort rows by time (stable) and keep the LAST row of every run of equal timestamps.

    A re-exported or re-sent record is assumed to supersede the earlier one.

    This is a time-series cleanup step: each observation is a
    (timestamp, value, quality) triple, and a sensor may report the same
    timestamp more than once when data is replayed or re-sent.

    Parameters
    ----------
    ts : np.ndarray
        Timestamps, one per observation (same unit as the caller uses,
        e.g. seconds since epoch). Not necessarily sorted.
    values : np.ndarray
        Measured value for each observation, aligned with ``ts`` by index.
    qualities : np.ndarray
        Quality flag per observation, aligned with ``ts`` by index.

    Returns
    -------
    tuple of (np.ndarray, np.ndarray, np.ndarray, int)
        The three arrays sorted by ascending time, containing only one
        row per distinct timestamp, plus the number of rows dropped as
        duplicates. All returned arrays stay aligned by index.
    """
    order = np.argsort(ts, kind="stable")
    ts, values, qualities = ts[order], values[order], qualities[order]

    is_last_of_run = np.append(ts[1:] != ts[:-1], True)

    dropped = int(len(ts) - is_last_of_run.sum())
    return ts[is_last_of_run], values[is_last_of_run], qualities[is_last_of_run], dropped


# --------------------------------------------------------------------------- #
# Main public function
# --------------------------------------------------------------------------- #


def import_csv(
    path: Path,
    out_dir: Path,
    *,
    dataset_id: str,
    tz: str = "UTC",
) -> ImportReport:
    """Import a CSV file exported by :func:`render_messy_csv`.

    The function writes a dataset to ``out_dir`` and returns an :class:`ImportReport`
    describing the import.

    A "tag" is one measured signal (one CSV column); a "sample" is one timestamped
    row of values for all tags. The import normalises messy input into the dataset
    on-disk format: a monotonically increasing UTC nanosecond index, a dense
    ``float64`` value matrix and a parallel ``uint8`` quality matrix.

    Parameters
    ----------
    path:
        Path to the CSV file.
    out_dir:
        Destination directory for the created dataset.
    dataset_id:
        Identifier used inside the dataset metadata.
    tz:
        Timezone name (e.g. ``"Europe/Warsaw"``) used for naive timestamps.

    Returns
    -------
    ImportReport
        Summary of the operation.

    Raises
    ------
    ValueError
        If no header is present, a timestamp cannot be parsed, or two columns
        collide once their names are sanitised.
    """
    text = _read_text(path)
    lines = _split_lines(text)

    # The renderer may quote cells, so the one-character delimiter must be inferred
    # from the raw lines before we can slice rows into columns.
    delimiter = _detect_delimiter(lines)
    header, data_rows = _extract_header_and_rows(lines, delimiter)

    if not header:
        raise ValueError("timestamp column not found")

    # --------------------------------------------------------------------- #
    # Timestamp handling
    # --------------------------------------------------------------------- #
    # Column 0 is always the time column; every other column is a tag value.
    # Timestamps are stored as int64 nanoseconds since the Unix epoch in UTC
    # ("ns" is the unit). int64 covers ~292 years around 1970, which is plenty
    # and matches the resolution the on-disk format expects.
    raw_ts = [row[0] for row in data_rows]
    ts_format_name, ts_parser = _try_timestamp_formats(raw_ts)

    # ts_parser returns a naive datetime or None; naive datetimes are interpreted
    # in the caller's tz and converted to UTC before being expressed in ns.
    ts_ns = np.empty(len(raw_ts), dtype=np.int64)
    for i, txt in enumerate(raw_ts):
        dt = ts_parser(txt)
        if dt is None:
            raise ValueError("timestamp parsing failed")
        ts_ns[i] = _to_utc_nanoseconds(dt, tz)

    # --------------------------------------------------------------------- #
    # Value handling
    # --------------------------------------------------------------------- #
    # Decimal comma ("1,5") and decimal point ("1.5") both appear in the wild;
    # detecting it here lets _parse_cell interpret each numeric cell correctly.
    decimal = _detect_decimal_separator(data_rows, delimiter)
    # The header is [timestamp, tag_0, tag_1, ...], so the number of tags is
    # header length minus the timestamp column.
    n_tags = len(header) - 1
    # Dense matrices: every row has one value and one quality flag per tag, even
    # when the source cell was empty or unparsable (such cells become NaN + BAD).
    values = np.empty((len(data_rows), n_tags), dtype=np.float64)
    qualities = np.empty((len(data_rows), n_tags), dtype=np.uint8)

    # bad_count tracks the number of BAD cells so ImportReport can surface it.
    bad_count = 0
    for i, row in enumerate(data_rows):
        # row[0] is the timestamp we already consumed; row[1:] are the tag values.
        for j, cell in enumerate(row[1:]):
            val = _parse_cell(cell, decimal)
            # pd.isna-style: NaN is the sentinel for "could not parse this cell".
            bad = np.isnan(val)
            qualities[i, j] = BAD if bad else GOOD
            bad_count += int(bad)
            values[i, j] = val

    # --------------------------------------------------------------------- #
    # Duplicate & ordering handling
    # --------------------------------------------------------------------- #
    # A true at any position means the source file had at least one timestamp
    # earlier than the one before it (e.g. a DST fall-back or an editor sort).
    # Recorded so the caller can tell whether the input was already ordered.
    unsorted = bool(np.any(ts_ns[1:] < ts_ns[:-1]))
    # Keep only the last value per identical timestamp and ensure strictly
    # increasing order (a requirement of the dataset's time index).
    ts_ns, values, qualities, dup_dropped = _sort_and_deduplicate(ts_ns, values, qualities)
    n_rows = ts_ns.shape[0]

    # --------------------------------------------------------------------- #
    # Tag sanitisation
    # --------------------------------------------------------------------- #
    # Tag ids must be safe to use as keys/paths; the original human-readable
    # names are preserved separately in the tags document written below.
    original_tag_names = header[1:]
    sanitized = [_sanitize_tag_name(name) for name in original_tag_names]
    # Two distinct source names could sanitise to the same id; refuse rather
    # than silently merge two different physical signals.
    if len(set(sanitized)) != len(sanitized):
        raise ValueError("duplicate tag identifiers after sanitisation")
    tag_ids = sanitized

    # --------------------------------------------------------------------- #
    # Write dataset
    # --------------------------------------------------------------------- #
    # The dataset records a start time (ISO 8601, UTC, second resolution) so
    # readers can align the sample index with wall-clock time. // truncates the
    # nanosecond int to whole seconds; fromtimestamp expects seconds.
    start_iso = datetime.fromtimestamp(int(ts_ns[0]) // 1_000_000_000, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    # Sidecar document describing the tag schema: the same sanitised ids used in
    # the value matrix, plus the original display names and empty placeholders
    # for metadata the CSV has no way to provide.
    tags_doc = {
        "schema_version": "0.1.0",
        "tags": [
            {
                "id": tag_id,
                "name": orig,
                "description": "",
                "unit": "",
                "type": "float",
                "role": "other",
                "source": {"driver": "csv", "address": orig},
            }
            for tag_id, orig in zip(tag_ids, original_tag_names, strict=True)
        ],
    }

    # Persist the three parallel arrays plus the two metadata documents.
    write_dataset(
        out_dir,
        ts_ns,
        tag_ids,
        values,
        qualities,
        dataset_id=dataset_id,
        source={"kind": "file"},
        start_utc=start_iso,
        tags_document=tags_doc,
    )

    # ImportReport is the caller-facing summary; each field is one of the
    # observations made above, so the caller does not have to re-inspect the
    # dataset to know whether the input was messy.
    return ImportReport(
        n_rows=n_rows,
        n_duplicates_dropped=dup_dropped,
        was_unsorted=unsorted,
        n_bad_values=bad_count,
        delimiter=delimiter,
        decimal=decimal,
        timestamp_format=ts_format_name,
    )
