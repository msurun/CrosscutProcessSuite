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
    """Resolve a dataset id to its directory; ids that are not plain names are 'not found'."""
    candidate = (data_root / dataset_id).resolve()
    is_plain_name = candidate.parent == data_root.resolve()
    if not is_plain_name or not (candidate / "dataset.json").is_file():
        raise HTTPException(status_code=404, detail="dataset not found")
    return candidate


def _summary(document: dict[str, Any]) -> dict[str, Any]:
    n_tags = len(document["tags"])
    return {
        "id": document["dataset_id"],
        "source": document["source"],
        "time_range": document["time_range"],
        "n_tags": n_tags,
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
    mask = np.ones(len(ts), dtype=bool)
    if start is not None:
        mask &= ts >= start
    if end is not None:
        mask &= ts <= end
    return ts[mask], values[mask]


def create_app(data_root: Path) -> FastAPI:
    """Create the API for the datasets stored in the sub-directories of ``data_root``."""
    root = Path(data_root)
    app = FastAPI(title="Crosscut data API")
    cache: dict[str, WideTable] = {}  # datasets are immutable once written

    def load_wide(dataset_id: str) -> WideTable:
        """Return the cached wide table for a dataset, loading and caching it on first use."""
        if dataset_id not in cache:
            ts, values = to_wide(read_dataset(_dataset_dir(root, dataset_id)))
            cache[dataset_id] = (ts.astype(np.int64), values)
        return cache[dataset_id]

    def tags_of(dataset_dir: Path) -> list[dict[str, Any]]:
        """Return the tag documents stored next to a dataset."""
        tag_document = _read_json(dataset_dir / "tags.json")
        return _tags_from_document(tag_document)

    def _tags_from_document(tag_document: dict[str, Any]) -> list[dict[str, Any]]:
        """Return the "tags" list of a parsed tag document, asserting its type.

        Raises:
            TypeError: if the document has no "tags" list, which means the file
                on disk does not follow the tag document format.
        """
        tags = tag_document["tags"]
        if not isinstance(tags, list):
            raise TypeError(
                f"Expected the tag document to hold a list under 'tags', got {type(tags).__name__}"
            )
        return tags

    def find_loop(dataset_dir: Path, loop_name: str) -> Any:
        """Return the loop named ``loop_name``, or raise a 404 if the dataset has no such loop."""
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
        return (ts - ts[0]) / NS_PER_SECOND, values

    def build_series(
        dataset_id: str,
        tag: list[str],
        start: int | None,
        end: int | None,
        max_points: int,
    ) -> list[dict[str, Any]]:
        """Return the downsampled envelopes of every requested tag."""
        timestamps, values = load_wide(dataset_id)
        _reject_unknown_tags(tag, values)
        series = []
        for tag_id in tag:
            window_timestamps, window_values = _window(timestamps, values[tag_id], start, end)
            envelope = downsample_minmax(window_timestamps, window_values, max_points)
            series.append(_envelope_document(tag_id, envelope))
        return series

    def _reject_unknown_tags(tag: list[str], values: dict[str, Any]) -> None:
        """Raise a 404 naming the first requested tag that the dataset does not contain."""
        unknown = [tag_id for tag_id in tag if tag_id not in values]
        if unknown:
            raise HTTPException(status_code=404, detail=f"unknown tag: {unknown[0]}")

    def _envelope_document(tag_id: str, envelope: Any) -> dict[str, Any]:
        """Return the JSON document describing one tag's downsampled envelope."""
        return {
            "tag": tag_id,
            "downsampled": envelope.downsampled,
            "t": envelope.t.tolist(),
            "min": _json_floats(envelope.min),
            "max": _json_floats(envelope.max),
            "mean": _json_floats(envelope.mean),
        }

    app.include_router(build_fuzzy_router(root, load_wide))

    _register_health_route(app)

    @app.get("/datasets")
    def list_datasets() -> list[dict[str, Any]]:
        """Return a summary of every dataset found on disk, sorted by dataset id."""
        documents = [_read_json(path) for path in root.glob("*/dataset.json")]
        summaries = (_summary(document) for document in documents)
        return sorted(summaries, key=lambda summary: str(summary["id"]))

    @app.get("/datasets/{dataset_id}/tags")
    def get_tags(dataset_id: str) -> list[dict[str, Any]]:
        """Return the tag documents of a dataset."""
        return tags_of(_dataset_dir(root, dataset_id))

    @dataclass(frozen=True)
    class SeriesRequest:
        """Parameters describing which series to fetch and how to downsample them."""

        dataset_id: str
        tag: list[str]
        start: int | None
        end: int | None
        max_points: int

    @app.get("/datasets/{dataset_id}/series")
    def get_series(
        dataset_id: str,
        tag: Annotated[list[str], Query(min_length=1)],
        start: int | None = None,
        end: int | None = None,
        max_points: Annotated[int, Query(ge=2, le=MAX_POINTS_LIMIT)] = DEFAULT_MAX_POINTS,
    ) -> dict[str, Any]:
        """Return the requested tags, downsampled for display."""
        request = SeriesRequest(dataset_id, tag, start, end, max_points)
        return {
            "dataset_id": request.dataset_id,
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
        """Estimate what a lower PV variability is worth, from the user's assumptions."""
        dataset_dir = _dataset_dir(root, dataset_id)
        loop = find_loop(dataset_dir, loop_name)
        t_s, values = load_seconds(dataset_id)
        try:
            return benefit_payload(loop, t_s, values, request.to_request())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return app


def _register_health_route(app: FastAPI) -> None:
    """Register the liveness probe on ``app``."""

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report that the service is up."""
        return {"status": "ok"}
