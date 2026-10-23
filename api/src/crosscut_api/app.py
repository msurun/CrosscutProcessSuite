"""HTTP API over Crosscut datasets (the backend of the trend viewer).

Datasets and loops are read-only. A client can write only configuration kept under the data
root: a fuzzy rule base (see fuzzy_routes) and the per-loop knowledge in a dataset's
project.json (see _KnowledgeEndpoints), and intake_routes creates one new dataset folder from
an uploaded step-test CSV. The valve stroke test (valve_routes) only reads a
record. Nothing here writes to a plant.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from crosscut_loops.benefit_payload import BenefitRequest, benefit_payload
from crosscut_loops.overview import LoopTags, analyze_dataset, discover_loops
from crosscut_loops.project_edit import (
    KnowledgeError,
    apply_knowledge,
    loop_knowledge,
    project_from_loops,
    tag_range_defaults,
    write_project_atomic,
)
from crosscut_loops.project_loops import loops_from_project
from crosscut_loops.tuning_payload import tuning_payload
from crosscut_loops.tuning_types import TuningRequest
from crosscut_sim.dataset import read_dataset, to_wide
from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Query

from crosscut_api.anomaly_routes import build_anomaly_router
from crosscut_api.downsample import Envelope, downsample_minmax
from crosscut_api.fuzzy_routes import build_fuzzy_router
from crosscut_api.intake_routes import build_intake_router
from crosscut_api.softsensor_routes import build_softsensor_router
from crosscut_api.supervisor_routes import build_supervisor_router
from crosscut_api.valve_routes import LoopRecordLoader, build_valve_router

DEFAULT_MAX_POINTS = 2000
MAX_POINTS_LIMIT = 100_000
NS_PER_SECOND = 1e9
PROJECT_FILE = "project.json"  # explicit loop definitions placed next to a dataset
WideTable = tuple[np.ndarray, dict[str, np.ndarray]]


def _read_json(path: Path) -> dict[str, Any]:
    """Parse one UTF-8 JSON file into a dict."""
    with path.open(encoding="utf-8") as handle:
        document: dict[str, Any] = json.load(handle)
    return document


def _dataset_dir(data_root: Path, dataset_id: str) -> Path:
    """Resolve a dataset id to its directory.

    Each dataset lives in its own directory under `data_root` and carries a `dataset.json`
    manifest; a directory without that file is not a dataset.

    Returns the absolute path of the dataset directory.

    Raises:
        HTTPException: 404 if the id is not a plain name (would escape `data_root` via
            `..` or be absolute) or if no dataset directory holds a `dataset.json`.
    """
    # `Path.resolve()` collapses `.` and `..` and makes the path absolute, so a hostile id
    # such as "../../etc" would land somewhere outside `data_root`. Checking the parent of
    # the resolved path (not the raw id) is a path-traversal guard: it fails whenever the
    # id points anywhere but directly inside `data_root`.
    candidate = (data_root / dataset_id).resolve()
    is_plain_name = candidate.parent == data_root.resolve()
    if not is_plain_name or not (candidate / "dataset.json").is_file():
        raise HTTPException(status_code=404, detail="dataset not found")
    return candidate


def _summary(document: dict[str, Any]) -> dict[str, Any]:
    """Return the compact summary card for a dataset document.

    A document is the ``dataset.json`` manifest of a dataset: the list of tag ids plus
    dataset-level metadata. The data file is in long layout (one row per tag and instant),
    so "row_count" counts the rows of ALL tags together and dividing it by the tag count
    gives the number of samples of each single tag.
    """
    # "tags" is the list of tag ids in this dataset; its length is the number of channels.
    n_tags = len(document["tags"])
    return {
        "id": document["dataset_id"],
        "source": document["source"],
        "time_range": document["time_range"],
        "n_tags": n_tags,
        # Rows per tag (unit: samples). "row_count" is the file total, so we
        # divide by the width to get the per-channel length. The guard avoids
        # ZeroDivisionError for a dataset that has no tags at all; such a
        # dataset has zero samples by definition rather than an undefined count.
        "n_samples": document["row_count"] // n_tags if n_tags else 0,
    }


def _json_floats(values: np.ndarray) -> list[float | None]:
    """Convert to a JSON-safe list: NaN has no JSON representation, so it becomes null."""
    return [None if math.isnan(item) else item for item in values.tolist()]


@dataclass
class BenefitQuery:
    """Query parameters of the benefit endpoint; every one is optional."""

    limit: float | None = None
    side: Literal["upper", "lower"] = "upper"
    value_per_unit_h: Annotated[float, Query(ge=0.0)] = 0.0
    margin_sigmas: Annotated[float, Query(ge=0.0)] = 2.0
    std_reduction: Annotated[float, Query(ge=0.0, lt=1.0)] = 0.5
    start_s: float | None = None
    end_s: float | None = None
    std_before: Annotated[float | None, Query(gt=0.0)] = None
    std_after: Annotated[float | None, Query(ge=0.0)] = None

    def to_request(self) -> BenefitRequest:
        """The same values as the library's request object."""
        return BenefitRequest(**vars(self))


def _loops_of(dataset_dir: Path, tags: list[dict[str, Any]]) -> list[LoopTags]:
    """Loops from the dataset's ``project.json`` when it exists, else found by naming convention."""
    project_path = dataset_dir / PROJECT_FILE
    if not project_path.exists():
        return discover_loops(tags)
    return loops_from_project(_read_json(project_path), tags)


def _window(
    ts: np.ndarray, values: np.ndarray, start: int | None, end: int | None
) -> tuple[np.ndarray, np.ndarray]:
    """Return the samples of a time series that fall inside a closed time window.

    A time series here is two parallel arrays of the same length: `ts[i]` is the
    timestamp of the sample whose measured value is `values[i]`. The window is
    inclusive on both ends, and `None` means "no bound on that side", so passing
    `None, None` returns everything.

    Returns a (timestamps, values) pair, still parallel and in the original order.
    """
    # Build the boolean selection array. This mask is the standard way to pick
    # samples from parallel arrays: whatever the mask keeps in `ts`, the same
    # positions are kept in `values`, so the pairing is never broken.
    mask = np.ones(len(ts), dtype=bool)

    # `&=` is a logical AND, not the bitwise trick it looks like: the mask keeps
    # a sample only if every bound that was supplied agrees. A bound left as
    # None adds no constraint, so the window stays open on that side.
    if start is not None:
        mask &= ts >= start
    if end is not None:
        mask &= ts <= end

    # Timestamps and bounds must already be in the same unit (the API passes UTC nanoseconds);
    # this function only compares them, it does not convert.
    return ts[mask], values[mask]


def _tags_from_document(tag_document: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the "tags" list of a parsed tag document, asserting its type.

    A tag document is the JSON file that stores the metadata of every tag in a
    dataset: it maps the key "tags" to a list of tag dictionaries (each with
    attributes such as its id, unit and role). This helper
    isolates the single place where that list is pulled out of the document,
    so the format is validated once and the rest of the code can trust it.

    Raises:
        TypeError: if the "tags" value is not a list, which means the file on
            disk does not follow the tag document format.
    """
    tags = tag_document["tags"]
    # Validate here and only here: downstream code assumes ``tags`` is a list
    # and would fail with a confusing error otherwise.
    if not isinstance(tags, list):
        raise TypeError(
            f"Expected the tag document to hold a list under 'tags', got {type(tags).__name__}"
        )
    return tags


class DatasetStore:
    """Loads datasets of one data root and caches them for the life of the process."""

    def __init__(self, root: Path) -> None:
        self.root = root
        # Dataset id -> (int64 epoch-nanosecond timestamps, tag values). Datasets never
        # change after they are written, so caching a loaded dataset is safe; nothing
        # ever invalidates this dict.
        self._cache: dict[str, WideTable] = {}

    def load_wide(self, dataset_id: str) -> WideTable:
        """Return the cached wide table for a dataset, loading and caching it on first use.

        Reads the dataset once from disk and keeps it in the cache; later calls with
        the same id never touch the disk again.
        """
        if dataset_id not in self._cache:
            # ``to_wide`` converts the on-disk series into one column per tag plus a
            # shared time axis. The timestamps are cast to int64 nanoseconds because
            # integer arithmetic keeps them exact and cheap to subtract or bucket.
            ts, values = to_wide(read_dataset(_dataset_dir(self.root, dataset_id)))
            self._cache[dataset_id] = (ts.astype(np.int64), values)
        return self._cache[dataset_id]

    def load_seconds(self, dataset_id: str) -> tuple[np.ndarray, dict[str, Any]]:
        """Return the dataset's series and its timestamps as seconds since the first sample."""
        ts, values = self.load_wide(dataset_id)
        # The stored timestamps are int64 nanoseconds since the epoch. Subtracting the
        # first sample makes the axis start at 0 (seconds elapsed, a float), which is
        # what the plotting clients expect.
        return (ts - ts[0]) / NS_PER_SECOND, values

    def load_quality(self, dataset_id: str) -> dict[str, np.ndarray]:
        """Return quality codes (0 good, 1 uncertain, 2 bad) per tag, aligned with the values."""
        table = read_dataset(_dataset_dir(self.root, dataset_id))
        tag_ids = list(dict.fromkeys(table["tag_id"].to_pylist()))
        codes = table["quality"].to_numpy().reshape(-1, len(tag_ids))
        return {tag: codes[:, j].copy() for j, tag in enumerate(tag_ids)}

    def tags_of(self, dataset_dir: Path) -> list[dict[str, Any]]:
        """Return the "tags" list stored in ``tags.json`` next to a dataset."""
        return _tags_from_document(_read_json(dataset_dir / "tags.json"))

    def loops_of(self, dataset_id: str) -> list[LoopTags]:
        """The control loops of a dataset (its project.json, else found by naming convention)."""
        dataset_dir = _dataset_dir(self.root, dataset_id)
        return _loops_of(dataset_dir, self.tags_of(dataset_dir))

    def find_loop(self, dataset_dir: Path, loop_name: str) -> Any:
        """Return the loop named ``loop_name``, or raise a 404 if the dataset has no such loop.

        A dataset is a folder on disk that may contain several control *loops*; a loop is the
        set of tags of one controller (pv, sp, out, mode). Callers refer to a loop by its name.

        Raises:
            HTTPException: 404 when no loop in the dataset carries that name, so a missing name
                is reported as "not found" rather than as a server error.
        """
        # ``next(...)`` stops at the first loop whose name matches; ``None`` is the sentinel
        # for "generator exhausted without a match".
        loops = _loops_of(dataset_dir, self.tags_of(dataset_dir))
        loop = next((one for one in loops if one.name == loop_name), None)
        if loop is None:
            raise HTTPException(status_code=404, detail=f"unknown loop: {loop_name}")
        return loop


@dataclass(frozen=True)
class SeriesQuery:
    """Which series to fetch (path + query string) and how to downsample them."""

    dataset_id: str
    # May hold the same tag twice; each entry produces one series in the response.
    tag: Annotated[list[str], Query(min_length=1)]
    # Bounds in UTC nanoseconds since the epoch, both inclusive; None means unbounded.
    start: int | None = None
    end: int | None = None
    # Upper bound on returned points per tag; the client picks it, the server clamps it.
    max_points: Annotated[int, Query(ge=2, le=MAX_POINTS_LIMIT)] = DEFAULT_MAX_POINTS


@dataclass(frozen=True)
class TuningQuery:
    """Which loop and data window to identify (path + query string) and how robust to tune."""

    dataset_id: str
    loop_name: str
    start_s: float | None = None
    end_s: float | None = None
    robustness: Annotated[float, Query(ge=0.0, le=1.0)] = 0.5
    max_swing: Annotated[float | None, Query(gt=0.0)] = None  # PV units; integrating loops only
    load_step_pct: Annotated[float | None, Query(gt=0.0)] = None  # % OUT; with max_swing


def _reject_unknown_tags(tag: list[str], values: dict[str, Any]) -> None:
    """Raise a 404 naming the first requested tag that the dataset does not contain."""
    # ``values`` has one column per available tag, so membership in it is the
    # check. Reporting the first unknown tag (not all of them) keeps the message
    # short and matches the "fail fast on the first problem" style of the API.
    unknown = [tag_id for tag_id in tag if tag_id not in values]
    if unknown:
        raise HTTPException(status_code=404, detail=f"unknown tag: {unknown[0]}")


def _envelope_document(tag_id: str, envelope: Envelope) -> dict[str, Any]:
    """Return the JSON document describing one tag's downsampled envelope.

    The "envelope" of a signal is its min/max/mean band: for every time bucket
    we keep the lowest, highest and average sample value, so a caller can draw
    the signal's outer shape without shipping every raw sample over the wire.

    Returns a JSON-serialisable dict with the keys ``tag``, ``downsampled``, ``t`` (timestamps
    as stored, UTC nanoseconds) and ``min``, ``max``, ``mean`` (same length as ``t``).
    """
    return {
        "tag": tag_id,
        # Whether the server reduced the resolution; false means the buckets
        # are the original samples.
        "downsampled": envelope.downsampled,
        # The time axis is a NumPy array, which json cannot serialise; tolist()
        # turns it into plain Python numbers.
        "t": envelope.timestamps.tolist(),
        # NaN is not valid JSON, so these arrays go through a sanitising
        # helper that replaces each NaN with None (JSON null).
        "min": _json_floats(envelope.min),
        "max": _json_floats(envelope.max),
        "mean": _json_floats(envelope.mean),
    }


def build_series(store: DatasetStore, query: SeriesQuery) -> list[dict[str, Any]]:
    """Return the downsampled envelopes of every requested tag, in the order of ``query.tag``."""
    timestamps, values = store.load_wide(query.dataset_id)
    _reject_unknown_tags(query.tag, values)
    # Process each tag independently: crop it to the requested time window, then
    # reduce it to at most ``max_points`` buckets.
    series = []
    for tag_id in query.tag:
        window_timestamps, window_values = _window(
            timestamps, values[tag_id], query.start, query.end
        )
        envelope = downsample_minmax(window_timestamps, window_values, query.max_points)
        series.append(_envelope_document(tag_id, envelope))
    return series


class _DatasetEndpoints:
    """Handlers of the dataset-level routes (listing, tags, series)."""

    def __init__(self, store: DatasetStore) -> None:
        self.store = store

    def list_datasets(self) -> list[dict[str, Any]]:
        """Return a summary of every dataset found on disk, sorted by dataset id."""
        # Every dataset lives in its own sub-directory of the root and carries a
        # ``dataset.json`` with its metadata; the glob finds those files only.
        documents = [_read_json(path) for path in self.store.root.glob("*/dataset.json")]
        summaries = (_summary(document) for document in documents)
        # Sorted by string id so paging and diffing clients see a stable order.
        return sorted(summaries, key=lambda summary: str(summary["id"]))

    def get_tags(self, dataset_id: str) -> list[dict[str, Any]]:
        """Return the tag documents of a dataset."""
        return self.store.tags_of(_dataset_dir(self.store.root, dataset_id))

    def get_series(self, query: Annotated[SeriesQuery, Depends()]) -> dict[str, Any]:
        """Return the requested tags, downsampled for display.

        Time-series data can hold millions of samples per tag, far more than a browser
        can plot. `max_points` caps how many samples come back, so callers receive a
        lighter set of points that still shows the shape of the curve.

        `tag` may repeat, so several series are requested in one call. `start` and
        `end` are optional bounds in UTC nanoseconds since the epoch (the unit of the stored
        timestamps), both inclusive; `None` means "no bound on that side".
        """
        return {
            # Echo the dataset id so the caller can match the answer to the request.
            "dataset_id": query.dataset_id,
            "series": build_series(self.store, query),
        }


class _LoopEndpoints:
    """Handlers of the per-loop routes (analysis, tuning, benefit)."""

    def __init__(self, store: DatasetStore) -> None:
        self.store = store

    def get_loops(self, dataset_id: str) -> dict[str, Any]:
        """Analyse every control loop of the dataset (health, findings, key numbers)."""
        dataset_dir = _dataset_dir(self.store.root, dataset_id)
        t_s, values = self.store.load_seconds(dataset_id)
        loops_of_dataset = _loops_of(dataset_dir, self.store.tags_of(dataset_dir))
        return {"dataset_id": dataset_id, "loops": analyze_dataset(t_s, values, loops_of_dataset)}

    def get_tuning(self, query: Annotated[TuningQuery, Depends()]) -> dict[str, Any]:
        """Identify the loop on a data window and propose PI settings (read-only)."""
        dataset_dir = _dataset_dir(self.store.root, query.dataset_id)
        loop = self.store.find_loop(dataset_dir, query.loop_name)
        t_s, values = self.store.load_seconds(query.dataset_id)
        row = analyze_dataset(t_s, values, [loop])[0]
        suspected = any(finding["code"] == "stiction" for finding in row["findings"])
        try:
            request = TuningRequest(
                query.start_s,
                query.end_s,
                query.robustness,
                suspected,
                query.max_swing,
                query.load_step_pct,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return tuning_payload(loop, t_s, values, request)

    def get_benefit(
        self,
        dataset_id: str,
        loop_name: str,
        request: Annotated[BenefitQuery, Depends()],
    ) -> dict[str, Any]:
        """Estimate what a lower PV variability is worth, from the user's assumptions.

        `request` is a query-string model, so FastAPI builds it from the URL parameters and
        this handler never sees them as separate arguments. Returns the JSON payload built by
        `benefit_payload`. Raises 422 when the user's assumptions are not usable.
        """
        # Check the dataset id first (404), then that the loop exists in it (404).
        dataset_dir = _dataset_dir(self.store.root, dataset_id)
        loop = self.store.find_loop(dataset_dir, loop_name)
        # The measured series: `t_s` is the time axis in seconds, `values` the signals,
        # both sorted by time.
        t_s, values = self.store.load_seconds(dataset_id)
        try:
            # The calculation is pure and raises ValueError on unusable assumptions (for example
            # an invalid side, std_reduction or margin_sigmas); the HTTP layer turns that into 422.
            return benefit_payload(loop, t_s, values, request.to_request())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error


def _loop_record_loader(store: DatasetStore) -> LoopRecordLoader:
    """A reader of one loop's OUT and PV (with the time axis in seconds) for the valve test."""

    def load(dataset_id: str, loop_name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        loop = store.find_loop(_dataset_dir(store.root, dataset_id), loop_name)
        t_s, values = store.load_seconds(dataset_id)
        op = np.asarray(values[loop.out], dtype=float)
        pv = np.asarray(values[loop.pv], dtype=float)
        return t_s, op, pv

    return load


class _KnowledgeEndpoints:
    """Handlers that read and edit the per-loop knowledge kept in a dataset's project.json."""

    def __init__(self, store: DatasetStore) -> None:
        self.store = store

    def get_knowledge(self, dataset_id: str, loop_name: str) -> dict[str, Any]:
        """The delay, ultimate period, amplitude limit and process kind of one loop."""
        dataset_dir = _dataset_dir(self.store.root, dataset_id)
        return self._document(dataset_dir, self._project_of(dataset_dir), loop_name)

    def put_knowledge(
        self, dataset_id: str, loop_name: str, update: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """Change some of a loop's knowledge; None clears a value. Writes project.json only."""
        dataset_dir = _dataset_dir(self.store.root, dataset_id)
        try:
            project = apply_knowledge(
                self._project_of(dataset_dir),
                loop_name,
                update,
                self.store.tags_of(dataset_dir),
            )
        except KnowledgeError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"No loop named {loop_name!r}") from error
        write_project_atomic(dataset_dir / PROJECT_FILE, project)
        return self._document(dataset_dir, project, loop_name)

    def _project_of(self, dataset_dir: Path) -> dict[str, Any]:
        """The dataset's project file, or one built from the loops found by naming convention."""
        path = dataset_dir / PROJECT_FILE
        if path.exists():
            return _read_json(path)
        return project_from_loops(discover_loops(self.store.tags_of(dataset_dir)))

    def _document(
        self, dataset_dir: Path, project: dict[str, Any], loop_name: str
    ) -> dict[str, Any]:
        """The knowledge of one loop plus which engineering ranges the tags already give."""
        loop = self.store.find_loop(dataset_dir, loop_name)
        try:
            knowledge = loop_knowledge(project, loop_name)
            defaults = tag_range_defaults(project, loop_name, self.store.tags_of(dataset_dir))
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"No loop named {loop_name!r}") from error
        return {
            "loop": loop_name,
            "knowledge": knowledge,
            **defaults,
            "saved": (dataset_dir / PROJECT_FILE).exists(),
            "ranges": {
                "pv": _range_or_none(loop.eng_min, loop.eng_max),
                "out": _range_or_none(loop.out_low, loop.out_high),
            },
        }


def _range_or_none(low: float | None, high: float | None) -> list[float] | None:
    """[low, high] when both ends are configured, otherwise None."""
    return None if low is None or high is None else [low, high]


def _dataset_router(store: DatasetStore) -> APIRouter:
    """Routes listing datasets and serving their tags and downsampled series."""
    endpoints = _DatasetEndpoints(store)
    router = APIRouter()
    router.add_api_route("/datasets", endpoints.list_datasets, methods=["GET"])
    router.add_api_route("/datasets/{dataset_id}/tags", endpoints.get_tags, methods=["GET"])
    router.add_api_route("/datasets/{dataset_id}/series", endpoints.get_series, methods=["GET"])
    return router


def _loop_router(store: DatasetStore) -> APIRouter:
    """Routes analysing the control loops of a dataset."""
    endpoints = _LoopEndpoints(store)
    router = APIRouter()
    router.add_api_route("/datasets/{dataset_id}/loops", endpoints.get_loops, methods=["GET"])
    router.add_api_route(
        "/datasets/{dataset_id}/loops/{loop_name}/tuning", endpoints.get_tuning, methods=["GET"]
    )
    router.add_api_route(
        "/datasets/{dataset_id}/loops/{loop_name}/benefit", endpoints.get_benefit, methods=["GET"]
    )
    knowledge = _KnowledgeEndpoints(store)
    path = "/datasets/{dataset_id}/loops/{loop_name}/knowledge"
    router.add_api_route(path, knowledge.get_knowledge, methods=["GET"])
    router.add_api_route(path, knowledge.put_knowledge, methods=["PUT"])
    router.include_router(build_valve_router(_loop_record_loader(store)))
    return router


def create_app(data_root: Path) -> FastAPI:
    """Create the API for the datasets stored in the sub-directories of ``data_root``."""
    store = DatasetStore(Path(data_root))
    app = FastAPI(title="Crosscut data API")
    # The fuzzy rule-base endpoints (replay, backtest) need the same loaded tables, so they
    # share the cached loader instead of reading the dataset again.
    app.include_router(build_fuzzy_router(store.root, store.load_wide))
    app.include_router(build_supervisor_router(store.root, store.load_seconds, store.loops_of))
    app.include_router(build_anomaly_router(store.root, store.load_seconds, store.load_quality))
    app.include_router(build_softsensor_router(store.root, store.load_seconds, store.load_quality))
    app.include_router(build_intake_router(store.root, store.loops_of))
    _register_health_route(app)
    app.include_router(_dataset_router(store))
    app.include_router(_loop_router(store))
    return app


def _register_health_route(app: FastAPI) -> None:
    """Register the liveness probe on ``app``.

    A liveness probe is the endpoint an orchestrator (Kubernetes, a load balancer,
    a monitoring system) polls to decide whether this process is still alive and
    able to serve traffic. Because the probe must stay cheap and must never fail
    for reasons unrelated to the process itself, it deliberately checks nothing
    external (no database, no downstream service) and only confirms that the HTTP
    stack is responding.
    """

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report that the service is up.

        Returns the literal payload ``{"status": "ok"}``. A successful HTTP
        status paired with this body is the contract the probe expects; callers
        should treat any other response as the service being unhealthy.
        """
        return {"status": "ok"}
