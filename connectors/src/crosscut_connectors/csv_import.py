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
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
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
    """
    candidates = [",", ";", "\t"]
    best_delim = ""
    best_score = -1
    sample = lines[:50]

    for delim in candidates:
        modal_cnt, modal_freq = _modal_field_count(sample, delim)
        # we need at least two columns to be a plausible CSV
        if modal_cnt < 2:
            continue
        # prefer the delimiter that covers most lines
        if modal_freq > best_score:
            best_score = modal_freq
            best_delim = delim
    if not best_delim:
        raise ValueError("cannot detect delimiter")
    return best_delim


def _modal_field_count(lines: list[str], delimiter: str) -> tuple[int, int]:
    """Return the most frequent field count and how many lines have it (0, 0 if none)."""
    counts: dict[int, int] = {}
    for ln in lines:
        cnt = len(ln.split(delimiter))
        counts[cnt] = counts.get(cnt, 0) + 1
    if not counts:
        return 0, 0
    return max(counts.items(), key=lambda kv: kv[1])


def _extract_header_and_rows(lines: list[str], delimiter: str) -> tuple[list[str], list[list[str]]]:
    """Find the first line with the modal field count and collect matching rows."""
    # compute modal field count for the chosen delimiter
    field_counts = [len(ln.split(delimiter)) for ln in lines]
    modal_cnt = max(set(field_counts), key=field_counts.count)

    header: list[str] = []
    data_rows: list[list[str]] = []
    header_found = False
    for ln in lines:
        parts = ln.split(delimiter)
        if len(parts) != modal_cnt:
            continue
        if not header_found:
            header = [cell.strip() for cell in parts]
            header_found = True
            continue
        data_rows.append([cell.strip() for cell in parts])
    return header, data_rows


def _parse_iso8601(value: str) -> datetime | None:
    """Parse ISO‑8601 timestamps, accepting a trailing ``Z``."""
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _strptime_or_none(fmt: str) -> Callable[[str], datetime | None]:
    """Return a parser for ``fmt`` that yields None instead of raising on a mismatch."""

    def parse(text: str) -> datetime | None:
        """Parse ``text`` with ``fmt``, or return None when it does not match."""
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            return None

    return parse


def _try_timestamp_formats(
    candidates: Iterable[str],
) -> tuple[str, Callable[[str], datetime | None]]:
    """Return a format name and a parsing callable that works for *all* rows."""
    # Order matters – the first that succeeds for every row wins.
    # The callable returns a ``datetime`` (may be naive or aware).
    for name, fn in _timestamp_format_candidates():
        # we only verify that the function does not raise for any candidate string
        # – the actual conversion is done later.
        if _parses_every_candidate(fn, candidates):
            return name, fn
    raise ValueError("timestamp format not recognised")


def _timestamp_format_candidates() -> list[tuple[str, Callable[[str], datetime | None]]]:
    """Return the parsing callables to try, in order of preference."""
    return [
        ("ISO8601", _parse_iso8601),
        ("d.m.Y H:M:S", _strptime_or_none("%d.%m.%Y %H:%M:%S")),
        ("Y-m-d H:M:S", _strptime_or_none("%Y-%m-%d %H:%M:%S")),
    ]


def _parses_every_candidate(
    parse: Callable[[str], datetime | None],
    candidates: Iterable[str],
) -> bool:
    """Return True when *parse* yields a datetime for every candidate string."""
    for candidate in candidates:
        if parse(candidate) is None:
            return False
    return True


def _to_utc_nanoseconds(dt: datetime, tz: str) -> int:
    """Convert a ``datetime`` to nanoseconds since the Unix epoch (UTC)."""
    if dt.tzinfo is None:
        # naive timestamps are interpreted in the provided timezone
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    else:
        # already timezone‑aware – convert to UTC
        dt = dt.astimezone(UTC)
    seconds = int(dt.timestamp())
    nanos = seconds * 1_000_000_000 + dt.microsecond * 1_000
    return nanos


def _detect_decimal_separator(rows: list[list[str]], delimiter: str) -> str:
    """Return ',' if the delimiter is not ',' and a cell looks like ``1,23``."""
    if delimiter == ",":
        return "."
    comma_number = re.compile(r"^-?\d+,\d+$")
    for row in rows:
        for cell in row[1:]:
            if comma_number.match(cell):
                return ","
    return "."


def _parse_cell(cell: str, decimal: str) -> float:
    """Parse one value cell; anything that is not a finite number (``Bad``, empty...) is NaN."""
    try:
        value = float(cell.strip().replace(decimal, "."))
    except ValueError:
        return float("nan")
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
    """
    text = _read_text(path)
    lines = _split_lines(text)

    delimiter = _detect_delimiter(lines)
    header, data_rows = _extract_header_and_rows(lines, delimiter)

    if not header:
        raise ValueError("timestamp column not found")

    # --------------------------------------------------------------------- #
    # Timestamp handling
    # --------------------------------------------------------------------- #
    raw_ts = [row[0] for row in data_rows]
    ts_format_name, ts_parser = _try_timestamp_formats(raw_ts)

    ts_ns = np.empty(len(raw_ts), dtype=np.int64)
    for i, txt in enumerate(raw_ts):
        dt = ts_parser(txt)
        if dt is None:
            raise ValueError("timestamp parsing failed")
        ts_ns[i] = _to_utc_nanoseconds(dt, tz)

    # --------------------------------------------------------------------- #
    # Value handling
    # --------------------------------------------------------------------- #
    decimal = _detect_decimal_separator(data_rows, delimiter)
    n_tags = len(header) - 1
    values = np.empty((len(data_rows), n_tags), dtype=np.float64)
    qualities = np.empty((len(data_rows), n_tags), dtype=np.uint8)

    bad_count = 0
    for i, row in enumerate(data_rows):
        for j, cell in enumerate(row[1:]):
            val = _parse_cell(cell, decimal)
            bad = np.isnan(val)
            qualities[i, j] = BAD if bad else GOOD
            bad_count += int(bad)
            values[i, j] = val

    # --------------------------------------------------------------------- #
    # Duplicate & ordering handling
    # --------------------------------------------------------------------- #
    unsorted = bool(np.any(ts_ns[1:] < ts_ns[:-1]))
    ts_ns, values, qualities, dup_dropped = _sort_and_deduplicate(ts_ns, values, qualities)
    n_rows = ts_ns.shape[0]

    # --------------------------------------------------------------------- #
    # Tag sanitisation
    # --------------------------------------------------------------------- #
    original_tag_names = header[1:]
    sanitized = [_sanitize_tag_name(name) for name in original_tag_names]
    if len(set(sanitized)) != len(sanitized):
        raise ValueError("duplicate tag identifiers after sanitisation")
    tag_ids = sanitized

    # --------------------------------------------------------------------- #
    # Write dataset
    # --------------------------------------------------------------------- #
    start_iso = datetime.fromtimestamp(int(ts_ns[0]) // 1_000_000_000, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
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

    return ImportReport(
        n_rows=n_rows,
        n_duplicates_dropped=dup_dropped,
        was_unsorted=unsorted,
        n_bad_values=bad_count,
        delimiter=delimiter,
        decimal=decimal,
        timestamp_format=ts_format_name,
    )
