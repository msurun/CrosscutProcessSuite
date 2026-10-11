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
        if dataset_id not in cache:
            ts, values = to_wide(read_dataset(_dataset_dir(root, dataset_id)))
            cache[dataset_id] = (ts.astype(np.int64), values)
        return cache[dataset_id]

    app.include_router(build_fuzzy_router(root, load_wide))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/datasets")
    def list_datasets() -> list[dict[str, Any]]:
        documents = [_read_json(path) for path in root.glob("*/dataset.json")]
        return sorted((_summary(d) for d in documents), key=lambda s: str(s["id"]))

    @app.get("/datasets/{dataset_id}/tags")
    def get_tags(dataset_id: str) -> list[dict[str, Any]]:
        tags: list[dict[str, Any]] = _read_json(_dataset_dir(root, dataset_id) / "tags.json")[
            "tags"
        ]
        return tags

    @app.get("/datasets/{dataset_id}/series")
    def get_series(
        dataset_id: str,
        tag: Annotated[list[str], Query(min_length=1)],
        start: int | None = None,
        end: int | None = None,
        max_points: Annotated[int, Query(ge=2, le=MAX_POINTS_LIMIT)] = DEFAULT_MAX_POINTS,
    ) -> dict[str, Any]:
        ts, values = load_wide(dataset_id)
        unknown = [t for t in tag if t not in values]
        if unknown:
            raise HTTPException(status_code=404, detail=f"unknown tag: {unknown[0]}")
        series = []
        for tag_id in tag:
            t_win, v_win = _window(ts, values[tag_id], start, end)
            env = downsample_minmax(t_win, v_win, max_points)
            series.append(
                {
                    "tag": tag_id,
                    "downsampled": env.downsampled,
                    "t": env.t.tolist(),
                    "min": _json_floats(env.min),
                    "max": _json_floats(env.max),
                    "mean": _json_floats(env.mean),
                }
            )
        return {"dataset_id": dataset_id, "series": series}

    @app.get("/datasets/{dataset_id}/loops")
    def get_loops(dataset_id: str) -> dict[str, Any]:
        """Analyse every control loop of the dataset (health, findings, key numbers)."""
        dataset_dir = _dataset_dir(root, dataset_id)
        tags = _read_json(dataset_dir / "tags.json")["tags"]
        ts, values = load_wide(dataset_id)
        t_s = (ts - ts[0]) / NS_PER_SECOND
        loops = analyze_dataset(t_s, values, _loops_of(dataset_dir, tags))
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
        tags = _read_json(dataset_dir / "tags.json")["tags"]
        ts, values = load_wide(dataset_id)
        t_s = (ts - ts[0]) / NS_PER_SECOND
        loop = next((one for one in _loops_of(dataset_dir, tags) if one.name == loop_name), None)
        if loop is None:
            raise HTTPException(status_code=404, detail=f"unknown loop: {loop_name}")
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
        tags = _read_json(dataset_dir / "tags.json")["tags"]
        ts, values = load_wide(dataset_id)
        t_s = (ts - ts[0]) / NS_PER_SECOND
        loop = next((one for one in _loops_of(dataset_dir, tags) if one.name == loop_name), None)
        if loop is None:
            raise HTTPException(status_code=404, detail=f"unknown loop: {loop_name}")
        try:
            return benefit_payload(loop, t_s, values, request.to_request())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return app
