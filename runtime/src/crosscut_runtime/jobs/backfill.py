"""Fill a live job's rolling window from the source's history on start and after a gap (#203).

A live job otherwise waits ``window_s`` seconds of live reads before its first KPI. When the
connector offers history (PI Web API, SQL historians), the missing part of the window is read
once and added like live samples; OPC UA sources without HistoryRead keep the live-only path.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from crosscut_connectors.base import CAP_HISTORY, ConnectorError
from crosscut_connectors.history_table import HistoryTable, history_table

GOOD_QUALITY = 0
NS_PER_S = 1e9
# A gap is a stretch without samples longer than this many sample periods (and at least 60 s).
GAP_PERIODS = 3
MIN_GAP_S = 60.0


@dataclass(frozen=True)
class BackfillPlan:
    """What to read: the tags and the UTC window [start_s, end_s) in epoch seconds."""

    tags: list[str]
    start_s: float
    end_s: float
    period_s: float


def _iso(epoch_s: float) -> str:
    """Epoch seconds as the ISO UTC text connectors accept."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_s))


def has_history(connector: Any) -> bool:
    """True when the connector says it can read history (connectors without capabilities can't)."""
    capabilities = getattr(connector, "capabilities", None)
    return callable(capabilities) and CAP_HISTORY in capabilities()


def plan(latest_s: float | None, now_s: float, window_s: float, period_s: float) -> float | None:
    """Start of the history read, or None when the window is fresh enough.

    The window needs filling when it is empty or its newest sample is older than the gap limit
    ``max(GAP_PERIODS * period_s, MIN_GAP_S)``; the read starts at that sample (or at the window
    edge ``now - window_s`` if later), so nothing older than the window is fetched.
    """
    edge = now_s - window_s
    if latest_s is not None and now_s - latest_s <= max(GAP_PERIODS * period_s, MIN_GAP_S):
        return None
    return edge if latest_s is None else max(latest_s, edge)


def good_samples(table: HistoryTable) -> Iterable[tuple[str, float, float]]:
    """(tag, epoch seconds, value) of every GOOD, finite cell of the table."""
    for row, ts_ns in enumerate(table.ts_ns):
        for col, tag in enumerate(table.tag_ids):
            value = float(table.values[row, col])
            if table.qualities[row, col] == GOOD_QUALITY and math.isfinite(value):
                yield tag, int(ts_ns) / NS_PER_S, value


def read(connector: Any, todo: BackfillPlan) -> HistoryTable:
    """Read the planned window; ConnectorError or ValueError when the source cannot answer."""
    raw = connector.history(todo.tags, _iso(todo.start_s), _iso(todo.end_s), todo.period_s)
    return history_table(raw, todo.tags)


# Receives each accepted history sample: (tag, epoch seconds, value in tag units).
AddSample = Callable[[str, float, float], None]


def backfill(connector: Any, todo: BackfillPlan, add: AddSample) -> dict[str, Any]:
    """Run one backfill: add every good sample through ``add``; never raises on source errors.

    Returns ``{"at": end_s, "samples": n, "error": None | text}`` for the job's state.
    """
    try:
        table = read(connector, todo)
    except (ConnectorError, ValueError) as error:
        return {"at": todo.end_s, "samples": 0, "error": str(error)}
    count = 0
    for tag, ts, value in good_samples(table):
        add(tag, ts, value)
        count += 1
    return {"at": todo.end_s, "samples": count, "error": None}
