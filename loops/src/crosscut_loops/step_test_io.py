"""Read a historian CSV of a step test (wide or long layout) into aligned PV, OUT, SP, MODE.

Wide layout: one column per signal. Long layout: (timestamp, tag, value[, quality]) rows, one
row per sample of one tag; tags are aligned by holding the last value (a historian only stores
changes). Delimiter, decimal mark and time format are detected unless given. Pure reading.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

COMMON_DELIMITERS = (",", ";", "\t")
COMMA_NUMBER = re.compile(r"^\s*-?\d+,\d+\s*$")
TIME_FORMATS = ("%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S")
TIME_NAMES = ("timestamp", "time", "datetime", "date", "t")
TAG_NAMES = ("tag", "tagname", "name", "point", "signal")
VALUE_NAMES = ("value", "val", "v")
QUALITY_NAMES = ("quality", "status", "q")
MANUAL_WORDS = {"man", "manual", "m", "hand", "h"}
EPOCH_MIN_S = 1.0e9  # numeric times above this are Unix seconds, below it relative seconds
RELATIVE_ANCHOR = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class ReadOptions:
    """Which columns / tags to read and how to parse them ('auto' detects)."""

    time_col: str | None = None
    pv_col: str | None = None
    out_col: str | None = None
    sp_col: str | None = None
    mode_col: str | None = None
    time_format: str = "auto"  # auto | iso | seconds
    decimal: str = "auto"  # auto | comma | dot
    delimiter: str = "auto"
    tag_pv: str | None = None
    tag_out: str | None = None
    tag_sp: str | None = None
    tag_mode: str | None = None
    tag_col: str | None = None
    value_col: str | None = None
    quality_col: str | None = None
    manual_value: float = 0.0  # numeric MODE value that means manual


@dataclass(frozen=True)
class Record:
    """Aligned signals; t_s is Unix seconds when ``absolute`` else seconds from an unknown start."""

    t_s: np.ndarray
    pv: np.ndarray
    out: np.ndarray
    sp: np.ndarray | None
    mode: np.ndarray | None
    absolute: bool
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def origin_utc(self) -> datetime:
        """UTC start of the record (an anchor date when the times were relative)."""
        base = float(self.t_s[0]) if self.absolute else RELATIVE_ANCHOR.timestamp()
        return datetime.fromtimestamp(base, tz=UTC)


def detect_delimiter(text: str) -> str:
    """The delimiter that splits most of the first lines into the same (>= 2) field count."""
    lines = [ln for ln in text.splitlines()[:50] if ln.strip()]
    best, best_score = ",", -1
    for delim in COMMON_DELIMITERS:
        counts = [len(ln.split(delim)) for ln in lines]
        modal = max(set(counts), key=counts.count) if counts else 0
        score = counts.count(modal) if modal >= 2 else -1
        if score > best_score:
            best, best_score = delim, score
    if best_score < 0:
        raise ValueError("cannot detect the delimiter: the file has no table with 2+ columns")
    return best


def decode_bytes(raw: bytes) -> str:
    """Text of a CSV file: UTF-8 (BOM allowed), else Latin-1."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def table_from_text(text: str, delimiter: str) -> tuple[list[str], list[list[str]], str]:
    """Header, data rows of the modal width, and the delimiter used (detected when 'auto')."""
    text = text.lstrip("﻿")
    if not text.strip():
        raise ValueError("empty file")
    delim = detect_delimiter(text) if delimiter == "auto" else delimiter
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    widths = [len(r) for r in rows]
    modal = max(set(widths), key=widths.count)
    kept = [[c.strip() for c in r] for r in rows if len(r) == modal]
    return kept[0], kept[1:], delim


def find_column(header: list[str], wanted: str | None, names: tuple[str, ...], what: str) -> int:
    """Index of the column ``wanted`` (exact, case-insensitive, unique substring) or guessed."""
    low = [h.lower() for h in header]
    if wanted is None:
        guess = [i for i, h in enumerate(low) if h in names]
        if len(guess) == 1:
            return guess[0]
        raise ValueError(f"{what} column not given and not guessable; columns: {header}")
    for hits in ([i for i, h in enumerate(header) if h == wanted],
                 [i for i, h in enumerate(low) if h == wanted.lower()],
                 [i for i, h in enumerate(low) if wanted.lower() in h]):  # fmt: skip
        if len(hits) == 1:
            return hits[0]
    raise ValueError(f"{what} column '{wanted}' not found (or ambiguous); columns: {header}")


def _parse_iso(text: str) -> float:
    """Unix seconds of one timestamp text (ISO 8601 or a common local layout; naive = UTC)."""
    value = text.strip()
    parsed = None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        for fmt in TIME_FORMATS:
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(f"cannot read timestamp '{text}'")
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp()


def _is_number(text: str, decimal: str) -> bool:
    """True when the text is a plain number in the given decimal convention."""
    try:
        float(text.strip().replace(decimal, "."))
    except ValueError:
        return False
    return True


def parse_times(cells: list[str], time_format: str, decimal: str) -> tuple[np.ndarray, bool, str]:
    """Times in seconds, whether they are absolute (Unix) and a description of the reading."""
    numeric = time_format == "seconds" or (
        time_format == "auto" and all(_is_number(c, decimal) for c in cells[:20])
    )
    if numeric:
        t = np.array([float(c.replace(decimal, ".")) for c in cells])
        absolute = bool(t[0] >= EPOCH_MIN_S)
        return t, absolute, "seconds (" + ("Unix epoch" if absolute else "relative") + ")"
    return np.array([_parse_iso(c) for c in cells]), True, "timestamps (naive times read as UTC)"


def parse_number(cell: str, decimal: str) -> float:
    """A finite float, or NaN for anything else (empty, 'Bad', 'Shutdown')."""
    try:
        value = float(cell.strip().replace(decimal, "."))
    except ValueError:
        return float("nan")
    return value if np.isfinite(value) else float("nan")


def parse_mode(cell: str, decimal: str, manual_value: float) -> float:
    """0.0 for manual, 1.0 for anything else known, NaN for unreadable; text MAN/MANUAL = 0."""
    word = cell.strip().lower()
    if word in MANUAL_WORDS:
        return 0.0
    number = parse_number(cell, decimal)
    if np.isnan(number):
        return 1.0 if word else float("nan")
    return 0.0 if number == manual_value else 1.0


def detect_decimal(mode: str, delimiter: str, cells: list[str]) -> str:
    """'.' or ',' from the option or, when auto, from the cells (not the delimiter)."""
    if mode in ("comma", "dot"):
        return "," if mode == "comma" else "."
    if delimiter != "," and any(COMMA_NUMBER.match(c) for c in cells):
        return ","
    return "."


def _sorted_unique(t: np.ndarray, columns: list[np.ndarray]) -> tuple[np.ndarray, list[np.ndarray]]:
    """Sort by time and keep the last row of equal timestamps."""
    order = np.argsort(t, kind="stable")
    t = t[order]
    keep = np.append(t[1:] != t[:-1], True)
    return t[keep], [c[order][keep] for c in columns]


def _converter(kind: str, decimal: str, o: ReadOptions) -> Callable[[str], float]:
    """Cell parser for a signal kind: MODE cells map to 0 (manual) / 1, others to numbers."""
    if kind == "mode":
        return lambda cell: parse_mode(cell, decimal, o.manual_value)
    return lambda cell: parse_number(cell, decimal)


def _wide(header: list[str], rows: list[list[str]], o: ReadOptions, delim: str) -> Record:
    """Record from a wide table (one column per signal)."""
    i_t = find_column(header, o.time_col, TIME_NAMES, "time")
    index: dict[str, int | None] = {
        "pv": find_column(header, o.pv_col, ("pv",), "PV"),
        "out": find_column(header, o.out_col, ("out", "op", "mv"), "OUT"),
        "sp": find_column(header, o.sp_col, (), "SP") if o.sp_col else None,
        "mode": find_column(header, o.mode_col, (), "MODE") if o.mode_col else None,
    }
    used = {k: i for k, i in index.items() if i is not None}
    decimal = detect_decimal(o.decimal, delim, [r[i] for r in rows for i in used.values()])
    t, absolute, how = parse_times([r[i_t] for r in rows], o.time_format, decimal)
    cols = [np.array([_converter(k, decimal, o)(r[i]) for r in rows]) for k, i in used.items()]
    t, arrays = _sorted_unique(t, cols)
    got = dict(zip(used, arrays, strict=True))
    note = f"layout wide, time {how}, decimal '{decimal}', delimiter {delim!r}"
    return Record(t, got["pv"], got["out"], got.get("sp"), got.get("mode"), absolute, (note,))


def _long_series(
    rows: list[list[str]], idx: tuple[int, int, int, int | None]
) -> dict[str, list[tuple[str, str]]]:
    """Group long rows by tag as (time text, value text); rows with quality 'bad*' are dropped."""
    i_t, i_tag, i_val, i_q = idx
    groups: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        if i_q is not None and r[i_q].strip().lower().startswith("bad"):
            continue
        groups.setdefault(r[i_tag], []).append((r[i_t], r[i_val]))
    return groups


def _hold_align(series: list[tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, list[np.ndarray]]:
    """Union time grid from the moment every series has a value; last value held."""
    grid = np.unique(np.concatenate([s[0] for s in series]))
    grid = grid[grid >= max(float(s[0][0]) for s in series)]
    return grid, [v[np.searchsorted(t, grid, side="right") - 1] for t, v in series]


def _tag_series(
    cells: list[tuple[str, str]], key: str, decimal: str, o: ReadOptions
) -> tuple[np.ndarray, np.ndarray, bool, str]:
    """(times, values, absolute, time description) of one tag's rows."""
    t, absolute, how = parse_times([c[0] for c in cells], o.time_format, decimal)
    conv = _converter(key, decimal, o)
    t, (values,) = _sorted_unique(t, [np.array([conv(c[1]) for c in cells])])
    return t, values, absolute, how


def _wanted_tags(o: ReadOptions, present: set[str]) -> list[tuple[str, str]]:
    """(signal kind, tag name) pairs asked for; raises if a tag is not in the file."""
    asked = (("pv", o.tag_pv), ("out", o.tag_out), ("sp", o.tag_sp), ("mode", o.tag_mode))
    wanted = [(k, n) for k, n in asked if n]
    missing = [n for _, n in wanted if n not in present]
    if missing:
        raise ValueError(f"tag(s) {missing} not found; tags in the file: {sorted(present)[:30]}")
    return wanted


def _long(header: list[str], rows: list[list[str]], o: ReadOptions, delim: str) -> Record:
    """Record from a long table (timestamp, tag, value[, quality])."""
    i_t = find_column(header, o.time_col, TIME_NAMES, "time")
    i_tag = find_column(header, o.tag_col, TAG_NAMES, "tag")
    i_val = find_column(header, o.value_col, VALUE_NAMES, "value")
    i_q = find_column(header, o.quality_col, QUALITY_NAMES, "quality") if o.quality_col else None
    decimal = detect_decimal(o.decimal, delim, [r[i_val] for r in rows])
    wanted = _wanted_tags(o, {r[i_tag] for r in rows})
    groups = _long_series(rows, (i_t, i_tag, i_val, i_q))
    empty = [n for _, n in wanted if not groups.get(n)]
    if empty:
        raise ValueError(f"tag(s) {empty} have no rows with usable quality")
    series = {k: _tag_series(groups[n], k, decimal, o) for k, n in wanted}
    grid, aligned = _hold_align([(s[0], s[1]) for s in series.values()])
    got = dict(zip(series, aligned, strict=True))
    absolute, how = next(iter(series.values()))[2:]
    note = (f"layout long (hold-last alignment of {len(wanted)} tags), time {how}, "
            f"decimal '{decimal}', delimiter {delim!r}")  # fmt: skip
    return Record(grid, got["pv"], got["out"], got.get("sp"), got.get("mode"), absolute, (note,))


def read_record(path: Path, options: ReadOptions) -> Record:
    """Read the CSV at ``path`` into a Record (see `read_record_text`)."""
    return read_record_text(decode_bytes(path.read_bytes()), options)


def read_record_text(text: str, options: ReadOptions) -> Record:
    """Read CSV text into a Record; long layout when --tag-pv and --tag-out are given.

    Raises ValueError with a readable message for unreadable files, unknown columns or tags.
    """
    header, rows, delim = table_from_text(text, options.delimiter)
    if not rows:
        raise ValueError("the file has a header but no data rows")
    if options.tag_pv or options.tag_out:
        if not (options.tag_pv and options.tag_out):
            raise ValueError("long layout needs both --tag-pv and --tag-out")
        return _long(header, rows, options, delim)
    long_like = {h.lower() for h in header} & set(TAG_NAMES) and {h.lower() for h in header} & set(
        VALUE_NAMES
    )
    if long_like and not options.pv_col:
        tag_i = find_column(header, options.tag_col, TAG_NAMES, "tag")
        raise ValueError(
            "this looks like a long (timestamp, tag, value) file: give --tag-pv and --tag-out; "
            f"tags in the file: {sorted({r[tag_i] for r in rows})[:30]}"
        )
    return _wide(header, rows, options, delim)
