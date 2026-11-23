"""Turn the history() answer of any read connector into one wide sample table (issue #201).

Connectors answer in their own layout; the API caches history as a dataset, which needs the wide
form of ``crosscut_sim.dataset.Samples``: one row per timestamp (int64 ns since the Unix epoch),
one column per tag, float64 values and uint8 qualities (0 good, 1 uncertain, 2 bad).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

from crosscut_connectors.csv_history import TIME_COLUMNS

BAD = 2
# One observation of one tag: (timestamp ns, value or NaN, quality 0/1/2).
Obs = tuple[int, float, int]


@dataclass(frozen=True)
class HistoryTable:
    """Wide history: ``values``/``qualities`` have shape (len(ts_ns), len(tag_ids)).

    A cell where the tag has no sample at that timestamp holds NaN with quality 2 (bad), so a
    gap is never mistaken for a real value.
    """

    ts_ns: np.ndarray
    tag_ids: list[str]
    values: np.ndarray
    qualities: np.ndarray


def to_ns(stamp: Any) -> int:
    """An ISO-8601 text or datetime as int64 ns since the epoch; no offset means UTC."""
    moment = stamp if isinstance(stamp, datetime) else datetime.fromisoformat(
        str(stamp).strip().replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    # Whole seconds times 1e9 plus microseconds times 1e3 keeps ns exact (no float rounding).
    return int(moment.timestamp()) * 10**9 + moment.microsecond * 1000


def _number(raw: Any) -> float:
    """A cell as float; None, empty text and unreadable text become NaN."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return math.nan
    try:
        return float(raw)
    except (TypeError, ValueError):
        return math.nan


def _quality(raw: Any, value: float) -> int:
    """The stated quality, else good for a number and bad for a missing value."""
    if raw not in (None, ""):
        return int(raw)
    return BAD if math.isnan(value) else 0


def _from_samples(samples: Iterable[Mapping[str, Any]]) -> list[Obs]:
    """Observations from ``{timestamp_utc, value, quality}`` dicts (PI and SQL profiles)."""
    out = []
    for sample in samples:
        value = _number(sample.get("value"))
        out.append((to_ns(sample["timestamp_utc"]), value, _quality(sample.get("quality"), value)))
    return out


def _pi(raw: Mapping[str, Any], tags: Sequence[str]) -> dict[str, list[Obs]]:
    """PI Web API: ``{tag: [sample, ...]}``."""
    return {tag: _from_samples(raw.get(tag) or []) for tag in tags}


def _sql_profile(rows: list[Mapping[str, Any]], tags: Sequence[str]) -> dict[str, list[Obs]]:
    """SQL historian profile: ``data`` is a list of samples, each naming its ``tag_id``."""
    return {tag: _from_samples(r for r in rows if r.get("tag_id") == tag) for tag in tags}


def _sql_table(raw: Mapping[str, Any], tags: Sequence[str]) -> dict[str, list[Obs]]:
    """SQL table: ``data`` rows are ``(timestamp, v0, v1, ...)`` in ``raw['tag_ids']`` order."""
    order = list(raw.get("tag_ids") or tags)
    out: dict[str, list[Obs]] = {}
    for tag in tags:
        col = order.index(tag) + 1 if tag in order else None
        obs = [(to_ns(r[0]), _number(r[col]), 0) for r in raw["data"]] if col else []
        out[tag] = [(t, v, BAD if math.isnan(v) else q) for t, v, q in obs]
    return out


def _csv_time(row: Mapping[str, str]) -> str:
    """The time column of a CSV row (the first of the known names present)."""
    for name in TIME_COLUMNS:
        if name in row:
            return name
    raise ValueError("unrecognised history layout")


def _csv_cell(row: Mapping[str, str], column: str) -> tuple[float, Any] | None:
    """Value and quality of ``column`` in a long row (tag/value) or a wide row (column)."""
    if "tag" in row and "value" in row:
        return (_number(row["value"]), row.get("quality")) if row["tag"] == column else None
    return (_number(row[column]), None) if column in row else None


def _csv(rows: list[Mapping[str, str]], tags: Sequence[str]) -> dict[str, list[Obs]]:
    """CSV folder: DictReader rows of strings; a tag id is ``file.csv/column``."""
    out: dict[str, list[Obs]] = {}
    for tag in tags:
        column = tag.split("/", 1)[-1]
        cells = ((row, _csv_cell(row, column)) for row in rows)
        out[tag] = [(to_ns(row[_csv_time(row)]), v, _quality(q, v)) for row, c in cells if c
                    for v, q in [c]]
    return out


def _observations(raw: Mapping[str, Any], tags: Sequence[str]) -> dict[str, list[Obs]]:
    """Pick the layout reader from the shape of the answer."""
    data = raw.get("data")
    if data is None:
        if any(isinstance(raw.get(tag), list) for tag in tags):
            return _pi(raw, tags)
        raise ValueError("unrecognised history layout")
    if not isinstance(data, list):
        raise ValueError("unrecognised history layout")
    first = data[0] if data else None
    if isinstance(first, Mapping):
        return _sql_profile(data, tags) if "tag_id" in first else _csv(data, tags)
    return _sql_table(raw, tags)


def _fill(columns: dict[str, list[Obs]], tags: Sequence[str], axis: np.ndarray) -> HistoryTable:
    """Place every observation in its row; later duplicates of a timestamp win."""
    row_of = {int(t): i for i, t in enumerate(axis)}
    values = np.full((len(axis), len(tags)), np.nan)
    qualities = np.full((len(axis), len(tags)), BAD, dtype=np.uint8)
    for j, tag in enumerate(tags):
        for t, v, q in columns[tag]:
            values[row_of[t], j], qualities[row_of[t], j] = v, q
    return HistoryTable(axis, list(tags), values, qualities)


def history_table(raw: Mapping[str, Any], tag_ids: Sequence[str]) -> HistoryTable:
    """The wide table of ``tag_ids`` from a connector's history answer.

    Raises:
        ValueError: "unrecognised history layout", or "no samples" when no tag has a sample.
    """
    tags = list(dict.fromkeys(tag_ids))
    columns = _observations(raw, tags)
    stamps = {t for obs in columns.values() for t, _, _ in obs}
    if not stamps:
        raise ValueError("no samples")
    return _fill(columns, tags, np.array(sorted(stamps), dtype=np.int64))
