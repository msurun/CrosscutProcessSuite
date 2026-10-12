"""Read-only HTTP API over Crosscut datasets (the backend of the trend viewer)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from crosscut_loops.benefit_payload import BenefitRequest, benefit_payload
from crosscut_loops.overview import LoopTags, analyze_dataset, discover_loops
from crosscut_loops.project_loops import loops_from_project
from crosscut_loops.tuning_payload import TuningRequest, tuning_payload
from crosscut_sim.dataset import read_dataset, to_wide
from fastapi import Depends, FastAPI, HTTPException, Query

from crosscut_api.downsample import downsample_minmax
from crosscut_api.fuzzy_routes import build_fuzzy_router

DEFAULT_MAX_POINTS = 2000
MAX_POINTS_LIMIT = 100_000
NS_PER_SECOND = 1e9
PROJECT_FILE = "project.json"  # explicit loop definitions placed next to a dataset
WideTable = tuple[np.ndarray, dict[str, np.ndarray]]


def _read_json(path: Path) -> dict[str, Any]:
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

    A document is a downloaded dataset manifest: it holds one entry per
    physical tag (a sensor channel, e.g. "temperature_bearing_1"), plus
    dataset-level metadata. The "row_count" field is the total number of
    rows in the file, counted across ALL tags at once, so dividing it by
    the tag count recovers the number of rows each single tag occupies.
    """
    # "tags" is the list of sensor channel names in this dataset; its length
    # is the dataset width (number of channels).
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
    return [None if math.isnan(x) else x for x in values.tolist()]


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

    # Timestamps are whatever unit the caller used (seconds, epochs, ...); this
    # function only compares them against the bounds, it does not convert them.
    return ts[mask], values[mask]


def create_app(data_root: Path) -> FastAPI:
    """Create the API for the datasets stored in the sub-directories of ``data_root``."""
    root = Path(data_root)
    app = FastAPI(title="Crosscut data API")
    # Dataset id -> (int64 epoch-nanosecond timestamps, tag values). Datasets never
    # change after they are written, so caching a loaded dataset for the life of the
    # process is safe; nothing ever invalidates this dict.
    cache: dict[str, WideTable] = {}  # datasets are immutable once written

    def load_wide(dataset_id: str) -> WideTable:
        """Return the cached wide table for a dataset, loading and caching it on first use.

        Reads the dataset once from disk and keeps it in ``cache``; later calls with
        the same id never touch the disk again.
        """
        if dataset_id not in cache:
            # ``to_wide`` converts the on-disk series into one column per tag plus a
            # shared time axis. The timestamps are cast to int64 nanoseconds because
            # integer arithmetic keeps them exact and cheap to subtract or bucket.
            ts, values = to_wide(read_dataset(_dataset_dir(root, dataset_id)))
            cache[dataset_id] = (ts.astype(np.int64), values)
        return cache[dataset_id]

    def tags_of(dataset_dir: Path) -> list[dict[str, Any]]:
        """Return the tag documents stored next to a dataset.

        Reads ``tags.json`` from the dataset folder and returns its "tags" list.
        """
        tag_document = _read_json(dataset_dir / "tags.json")
        return _tags_from_document(tag_document)

    def _tags_from_document(tag_document: dict[str, Any]) -> list[dict[str, Any]]:
        """Return the "tags" list of a parsed tag document, asserting its type.

        A tag document is the JSON file that stores the metadata of every tag in a
        dataset: it maps the key "tags" to a list of tag dictionaries (each with
        attributes such as its name and the nodes it applies to). This helper
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

    def find_loop(dataset_dir: Path, loop_name: str) -> Any:
        """Return the loop named ``loop_name``, or raise a 404 if the dataset has no such loop.

        In this domain a dataset is a folder on disk that may contain several *loops*; a loop is a
        named, closed circuit of graph nodes (think of a road or a pipeline the nodes describe).
        Callers refer to a loop by its user-facing name, which is not its position in the folder.

        Returns:
            The loop object whose ``name`` equals ``loop_name``.

        Raises:
            HTTPException: with status 404 when no loop in the dataset carries that name. The API
                surfaces this status to the client, so a missing name is reported as "not found"
                rather than as a server error.
        """
        # ``_loops_of`` builds the whole list of loops for the dataset (reading its tags is a
        # prerequisite, hence the two arguments). ``next(...)`` walks that iterable and stops at the
        # first loop whose name matches; ``None`` is the sentinel returned when the generator is
        # exhausted without a match, which we distinguish below from a real loop object.
        loop = next(
            (
                one
                for one in _loops_of(dataset_dir, tags_of(dataset_dir))
                if one.name == loop_name
            ),
            None,
        )
        if loop is None:
            raise HTTPException(status_code=404, detail=f"unknown loop: {loop_name}")
        return loop

    def load_seconds(dataset_id: str) -> tuple[np.ndarray, dict[str, Any]]:
        """Return the dataset's series and its timestamps as seconds since the first sample."""
        ts, values = load_wide(dataset_id)
        # The stored timestamps are int64 nanoseconds since the epoch. Subtracting the
        # first sample makes the axis start at 0 (seconds elapsed, a float), which is
        # what the plotting clients expect.
        return (ts - ts[0]) / NS_PER_SECOND, values

    def build_series(
        dataset_id: str,
        tag: list[str],
        start: int | None,
        end: int | None,
        max_points: int,
    ) -> list[dict[str, Any]]:
        """Return the downsampled envelopes of every requested tag.

        One JSON document per requested tag, in the same order as ``tag``.
        """
        timestamps, values = load_wide(dataset_id)
        _reject_unknown_tags(tag, values)
        # Process each tag independently: crop it to the requested time window, then
        # reduce it to at most ``max_points`` buckets.
        series = []
        for tag_id in tag:
            window_timestamps, window_values = _window(timestamps, values[tag_id], start, end)
            envelope = downsample_minmax(window_timestamps, window_values, max_points)
            series.append(_envelope_document(tag_id, envelope))
        return series

    def _reject_unknown_tags(tag: list[str], values: dict[str, Any]) -> None:
        """Raise a 404 naming the first requested tag that the dataset does not contain."""
        # ``values`` has one column per available tag, so membership in it is the
        # check. Reporting the first unknown tag (not all of them) keeps the message
        # short and matches the "fail fast on the first problem" style of the API.
        unknown = [tag_id for tag_id in tag if tag_id not in values]
        if unknown:
            raise HTTPException(status_code=404, detail=f"unknown tag: {unknown[0]}")

    def _envelope_document(tag_id: str, envelope: Any) -> dict[str, Any]:
        """Return the JSON document describing one tag's downsampled envelope.

        The "envelope" of a signal is its min/max/mean band: for every time bucket
        we keep the lowest, highest and average sample value, so a caller can draw
        the signal's outer shape without shipping every raw sample over the wire.

        Takes the tag identifier and an envelope object exposing five attributes:
        ``downsampled`` (whether the envelope was reduced at all, bool), ``t``
        (bucket start times, seconds since epoch), ``min``/``max``/``mean``
        (per-bucket values, one entry per entry of ``t``; NaN where a bucket had
        no samples).

        Returns a JSON-serialisable dict. Keys are one letter long because this
        document is repeated for every tag and size matters on the wire:
        ``t``, ``min``, ``max``, ``mean``.
        """
        return {
            "tag": tag_id,
            # Whether the server reduced the resolution; false means the buckets
            # are the original samples.
            "downsampled": envelope.downsampled,
            # The time axis is a NumPy array, which json cannot serialise; tolist()
            # turns it into plain Python floats.
            "t": envelope.t.tolist(),
            # NaN is not valid JSON, so these arrays go through a sanitising
            # helper that replaces each NaN with None (JSON null).
            "min": _json_floats(envelope.min),
            "max": _json_floats(envelope.max),
            "mean": _json_floats(envelope.mean),
        }

    # The fuzzy-matching endpoints need the same loaded tables, so they share the
    # cached loader instead of reading the dataset again.
    app.include_router(build_fuzzy_router(root, load_wide))

    _register_health_route(app)

    @app.get("/datasets")
    def list_datasets() -> list[dict[str, Any]]:
        """Return a summary of every dataset found on disk, sorted by dataset id."""
        # Every dataset lives in its own sub-directory of ``root`` and carries a
        # ``dataset.json`` with its metadata; the glob finds those files only.
        documents = [_read_json(path) for path in root.glob("*/dataset.json")]
        summaries = (_summary(document) for document in documents)
        # Sorted by string id so paging and diffing clients see a stable order.
        return sorted(summaries, key=lambda summary: str(summary["id"]))

    @app.get("/datasets/{dataset_id}/tags")
    def get_tags(dataset_id: str) -> list[dict[str, Any]]:
        """Return the tag documents of a dataset."""
        return tags_of(_dataset_dir(root, dataset_id))

    @dataclass(frozen=True)
    class SeriesRequest:
        """Parameters describing which series to fetch and how to downsample them."""

        dataset_id: str
        # May hold the same tag twice; each entry produces one series in the response.
        tag: list[str]
        # Epoch-second bounds (inclusive start, exclusive end); None means unbounded.
        start: int | None
        end: int | None
        # Upper bound on returned points per tag; the client picks it, the server clamps it.
        max_points: int

    @app.get("/datasets/{dataset_id}/series")
    def get_series(
        dataset_id: str,
        tag: Annotated[list[str], Query(min_length=1)],
        start: int | None = None,
        end: int | None = None,
        max_points: Annotated[int, Query(ge=2, le=MAX_POINTS_LIMIT)] = DEFAULT_MAX_POINTS,
    ) -> dict[str, Any]:
        """Return the requested tags, downsampled for display.

        Time-series data can hold millions of samples per tag, far more than a browser
        can plot. `max_points` caps how many samples come back, so callers receive a
        lighter set of points that still shows the shape of the curve.

        `tag` may repeat, so several series are requested in one call. `start` and
        `end` are optional epoch-second bounds; `None` means "no bound on that side".
        """
        # Validate and normalise the raw query parameters first. SeriesRequest is a
        # dataclass whose __post_init__ rejects bad input (unknown tag, start after
        # end, ...) and fills the missing bounds with the dataset's own first and
        # last timestamps, so every field is concrete from here on.
        request = SeriesRequest(dataset_id, tag, start, end, max_points)
        return {
            # Echo the resolved dataset id so the caller can match the answer to the
            # request even if the id needed normalising.
            "dataset_id": request.dataset_id,
            # Downsample to at most request.max_points samples per tag (a plain
            # stride/thinning pass, so extremes may be dropped) and return them as a
            # mapping of tag name -> list of {timestamp, value} points.
            "series": build_series(
                request.dataset_id,
                request.tag,
                request.start,
                request.end,
                request.max_points,
            ),
        }

    @app.get("/datasets/{dataset_id}/loops")
    def get_loops(dataset_id: str) -> dict[str, Any]:
        """Analyse every control loop of the dataset (health, findings, key numbers)."""
        dataset_dir = _dataset_dir(root, dataset_id)
        t_s, values = load_seconds(dataset_id)
        loops = analyze_dataset(t_s, values, _loops_of(dataset_dir, tags_of(dataset_dir)))
        return {"dataset_id": dataset_id, "loops": loops}

    @app.get("/datasets/{dataset_id}/loops/{loop_name}/tuning")
    def get_tuning(
        dataset_id: str,
        loop_name: str,
        start_s: float | None = None,
        end_s: float | None = None,
        robustness: Annotated[float, Query(ge=0.0, le=1.0)] = 0.5,
    ) -> dict[str, Any]:
        """Identify the loop on a data window and propose PI settings (read-only)."""
        dataset_dir = _dataset_dir(root, dataset_id)
        loop = find_loop(dataset_dir, loop_name)
        t_s, values = load_seconds(dataset_id)
        row = analyze_dataset(t_s, values, [loop])[0]
        suspected = any(finding["code"] == "stiction" for finding in row["findings"])
        request = TuningRequest(start_s, end_s, robustness, suspected)
        return tuning_payload(loop, t_s, values, request)

    @app.get("/datasets/{dataset_id}/loops/{loop_name}/benefit")
    def get_benefit(
        dataset_id: str,
        loop_name: str,
        request: Annotated[BenefitQuery, Depends()],
    ) -> dict[str, Any]:
        """Estimate what a lower PV variability is worth, from the user's assumptions.

        `request` is a query-string model, so FastAPI builds it from the URL parameters and
        this handler never sees them as separate arguments. Returns the JSON payload built by
        `benefit_payload`. Raises 422 when the user's assumptions are not usable.

        "Benefit" is the money saved by damping the PV power fluctuations with a battery,
        valued with the tariffs the user gave in the query string.
        """
        # Folders are laid out as one directory per dataset, the loop stored inside it.
        dataset_dir = _dataset_dir(root, dataset_id)
        loop = find_loop(dataset_dir, loop_name)
        # The measured series: `t_s` is the time axis in seconds, `values` the PV power in
        # watts at each of those instants, both sorted by time.
        t_s, values = load_seconds(dataset_id)
        try:
            # The calculation is pure and raises ValueError on bad assumptions (unknown
            # tariff name, missing loop points); the HTTP layer turns that into a 422.
            return benefit_payload(loop, t_s, values, request.to_request())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return app


def _register_health_route(app: FastAPI) -> None:
    """Register the liveness probe on ``app``.

    A liveness probe is the endpoint an orchestrator (Kubernetes, a load balancer,
    a monitoring system) polls to decide whether this process is still alive and
    able to serve traffic. If the endpoint stops answering, the orchestrator
    restarts or removes the instance. Because the probe must stay cheap and must
    never fail for reasons unrelated to the process itself, it deliberately
    checks nothing external (no database, no downstream service) and only
    confirms that the HTTP stack is responding.

    The route is added by decorating a nested function, so the endpoint is
    defined and registered in a single place and cannot be forgotten.
    """

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report that the service is up.

        Returns the literal payload ``{"status": "ok"}``. A successful HTTP
        status paired with this body is the contract the probe expects; callers
        should treat any other response as the service being unhealthy.
        """
        return {"status": "ok"}
