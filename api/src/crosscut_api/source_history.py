"""History on demand from a catalogue source, cached as an internal dataset (issue #201).

``GET /sources/{id}/history`` reads the window through the source's connector once and writes it
as a normal dataset folder ``<root>/hist-<key>``, so every dataset endpoint (trends, loops,
anomaly, ...) works on plant history without a manual import. The key hashes source, tags and
window, so the same request is served from the cache; the oldest caches are evicted first.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from crosscut_connectors.base import CAP_HISTORY, CAP_METADATA, ConnectorError
from crosscut_connectors.history_table import HistoryTable, history_table
from crosscut_connectors.registry import connector_from_source
from crosscut_sim.dataset import DatasetInfo, Samples, write_dataset
from fastapi import APIRouter, HTTPException, Query

from crosscut_api.connector_routes import _find_source

Doc = dict[str, Any]
# A connector read: the wide sample table and the unit of each tag.
Read = tuple[HistoryTable, dict[str, str]]
CACHE_PREFIX = "hist-"
# Most cached history datasets kept per data root; the oldest (by creation) go first.
MAX_CACHED = 50
# Longest window one request may read, in days; larger reads belong to a batch import.
MAX_WINDOW_DAYS = 400


def _parse_utc(text: str, name: str) -> datetime:
    """An ISO-8601 time as an aware UTC datetime (naive = UTC); 422 when unreadable."""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"{name}: not an ISO-8601 time") from error
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _iso(moment: datetime) -> str:
    """A UTC datetime as ``YYYY-MM-DDTHH:MM:SSZ``, the form connectors and datasets use."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def cache_key(source_id: str, tags: list[str], window: Doc) -> str:
    """Stable 16-hex key of a request: same source, tag set and window -> same cache folder."""
    payload = json.dumps([source_id, sorted(set(tags)), window], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _window(start: str, end: str, period_s: float | None) -> Doc:
    """The validated window: start before end, at most MAX_WINDOW_DAYS long."""
    begin, finish = _parse_utc(start, "start"), _parse_utc(end, "end")
    if finish <= begin:
        raise HTTPException(status_code=422, detail="end must be after start")
    if (finish - begin).days > MAX_WINDOW_DAYS:
        raise HTTPException(status_code=422, detail=f"window longer than {MAX_WINDOW_DAYS} days")
    return {"start_utc": _iso(begin), "end_utc": _iso(finish), "period_s": period_s}


def _units(connector: Any, tags: list[str]) -> dict[str, str]:
    """Engineering units from the connector's metadata when it offers any, else empty."""
    if CAP_METADATA not in connector.capabilities():
        return {}
    try:
        return {m.id: m.unit or "" for m in connector.metadata(tags)}
    except ConnectorError:
        return {}  # units are a convenience; a metadata failure must not block the history


def _tags_document(source: Doc, tags: list[str], units: dict[str, str]) -> Doc:
    """``tags.json`` of the cache: one float tag per requested tag, read from this source."""
    driver = str(source.get("driver", "source"))
    entries = [
        {"id": tag, "name": tag, "description": "", "unit": units.get(tag, ""), "type": "float",
         "role": "other", "source": {"driver": driver, "address": tag}}
        for tag in tags
    ]
    return {"schema_version": "0.1.0", "tags": entries}


def _read(source: Doc, tags: list[str], window: Doc) -> Read:
    """Read the window through the connector; 400 without history support, 502 on failures."""
    try:
        connector = connector_from_source(source)
        if CAP_HISTORY not in connector.capabilities():
            raise HTTPException(status_code=400, detail="source does not offer history")
        raw = connector.history(tags, window["start_utc"], window["end_utc"], window["period_s"])
        return history_table(raw, tags), _units(connector, tags)
    except ConnectorError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ValueError as error:  # "no samples" or a layout the normaliser does not know
        raise HTTPException(status_code=404, detail=str(error)) from error


def _write(folder: Path, source: Doc, read: Read, window: Doc) -> Doc:
    """Write the read as a dataset folder; the source block records where it came from."""
    table, units = read
    samples = Samples(table.ts_ns, table.tag_ids, table.values, table.qualities)
    first = datetime.fromtimestamp(int(table.ts_ns[0]) // 10**9, tz=UTC)
    block = {"kind": "history", "source_id": str(source["id"]), "window": window}
    tags_doc = _tags_document(source, table.tag_ids, units)
    info = DatasetInfo(folder.name, block, _iso(first), tags_doc)
    return write_dataset(folder, samples, info)


def evict(root: Path, keep: int = MAX_CACHED) -> list[str]:
    """Delete the oldest history caches beyond ``keep``; returns the removed dataset ids."""
    caches = sorted(root.glob(f"{CACHE_PREFIX}*/dataset.json"), key=lambda p: p.stat().st_mtime)
    removed = [path.parent for path in caches[: max(len(caches) - keep, 0)]]
    for folder in removed:
        shutil.rmtree(folder, ignore_errors=True)
    return [folder.name for folder in removed]


def _summary(doc: Doc, cached: bool) -> Doc:
    """What the caller needs to use the cache through the dataset endpoints."""
    return {"dataset_id": doc["dataset_id"], "cached": cached,
            "time_range": doc["time_range"], "tags": doc["tags"]}


class _Endpoints:
    """Handler of ``GET /sources/{source_id}/history``."""

    def __init__(self, root: Path) -> None:
        """Bind the data root that holds the site catalogue and the caches."""
        self.root = root

    def history(
        self,
        source_id: str,
        tag: Annotated[list[str], Query(min_length=1, max_length=200)],
        start: str,
        end: str,
        period_s: Annotated[float | None, Query(gt=0)] = None,
    ) -> Doc:
        """Read (or reuse) the history of ``tag`` in [start, end) and return its dataset id."""
        source = _find_source(self.root, source_id)
        window = _window(start, end, period_s)
        folder = self.root / f"{CACHE_PREFIX}{cache_key(source_id, tag, window)}"
        if (folder / "dataset.json").is_file():
            return _summary(json.loads((folder / "dataset.json").read_text("utf-8")), cached=True)
        doc = _write(folder, source, _read(source, list(dict.fromkeys(tag)), window), window)
        evict(self.root)
        return _summary(doc, cached=False)


def build_source_history_router(root: Path) -> APIRouter:
    """Route that turns a source history window into a cached dataset."""
    router = APIRouter()
    router.add_api_route("/sources/{source_id}/history", _Endpoints(root).history, methods=["GET"])
    return router
