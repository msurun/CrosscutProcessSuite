"""HTTP routes of the fuzzy module: list, load and save rule bases, what-if inference, replay.

Rule bases are configuration kept in ``<data root>/_fuzzy``; nothing here writes to a plant.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import numpy as np
from crosscut_fuzzy.library import list_systems, load_document, save_document
from crosscut_fuzzy.model import FuzzyModelError, FuzzySystem, system_from_dict
from crosscut_fuzzy.payload import infer_payload, replay_payload
from crosscut_fuzzy.versions import diff_documents, list_versions, load_version, save_version
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

USER_DIR_NAME = "_fuzzy"
DEFAULT_REPLAY_POINTS = 1500
WideTable = tuple[np.ndarray, dict[str, np.ndarray]]


class InferRequest(BaseModel):
    """A rule base (possibly unsaved, as edited on screen) and one set of input values."""

    document: dict[str, Any]
    inputs: dict[str, float]


class DiffRequest(BaseModel):
    """Two rule base documents to compare."""

    old: dict[str, Any]
    new: dict[str, Any]


class ReplayRequest(BaseModel):
    """A rule base and the part of a dataset to replay it on (seconds from the first sample)."""

    document: dict[str, Any]
    start_s: float | None = None
    end_s: float | None = None
    max_points: Annotated[int, Field(ge=2, le=5000)] = DEFAULT_REPLAY_POINTS


def build_fuzzy_router(root: Path, load_wide: Callable[[str], WideTable]) -> APIRouter:
    """Routes for the rule bases stored under ``root`` and for replay on ``root``'s datasets.

    A *fuzzy rule base* is a saved set of human-readable IF/THEN rules that map
    input variables to output variables through fuzzy sets ("cold", "warm").
    ``root`` is the data directory of the project; the user's own rule bases
    live in the ``USER_DIR_NAME`` sub-directory of it.

    Args:
        root: Base directory holding both the bundled examples and the user's files.
        load_wide: Callback that reads a dataset by name into a wide table
            (one row per timestamp, one column per signal). Not used here yet;
            it is kept in the signature for the replay routes that share this router.

    Returns:
        An ``APIRouter`` with the ``/fuzzy`` endpoints already registered.
    """
    router = APIRouter()
    # Directory where the user's own rule bases are read from and written to.
    user_dir = root / USER_DIR_NAME

    @router.get("/fuzzy")
    def get_systems() -> list[dict[str, str]]:
        """Bundled examples and the user's saved systems."""
        # Each entry is a small dict of strings, typically {"id": ..., "name": ...}.
        return list_systems(user_dir)

    @router.get("/fuzzy/{system_id}")
    def get_system(system_id: str) -> dict[str, Any]:
        """Return one fuzzy rule-base document as JSON.

        The document is identified by ``system_id``, the name of the rule base
        (for example ``"temperature_control"``). It is read from ``user_dir``,
        the directory that holds the user's saved rule bases.

        Returns:
            The parsed rule-base document, ready to be serialised as JSON.

        Raises:
            HTTPException: 404 when no document with that name exists in
                ``user_dir``; 422 when the file exists but does not describe a
                valid fuzzy model.
        """
        try:
            return load_document(system_id, user_dir)
        # A missing file means the caller asked for a rule base that was never
        # saved. That is a client mistake, so answer "404 Not Found" with the
        # requested name so the caller sees exactly what could not be found.
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=f"unknown system: {system_id}") from error
        # The file exists but its contents are not a usable fuzzy model (for
        # example a malformed rule or an unknown membership-function type).
        # The request was well formed, so the failure is semantic: "422
        # Unprocessable Entity", carrying the validation message from the loader.
        except FuzzyModelError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.put("/fuzzy/{system_id}")
    def put_system(system_id: str, document: dict[str, Any]) -> dict[str, Any]:
        """Validate and save a rule base as the user's system (configuration only).

        The document is validated before it is written: `save_document` raises
        `FuzzyModelError` when the rule base is malformed, so a bad document never
        reaches disk and the previous file for this `system_id` is left untouched.
        On success the same document is also appended to the version history, so
        every accepted configuration is recoverable.

        Returns the saved document unchanged, which lets the caller echo back the
        authoritative server-side state. Raises `HTTPException` with status 422
        (Unprocessable Entity) if validation fails.
        """
        try:
            save_document(system_id, document, user_dir)
            # History entry timestamped in UTC; `save_version` appends rather than
            # overwrites, so earlier versions of the same system_id stay readable.
            save_version(system_id, document, user_dir, now=datetime.now(UTC))
        except FuzzyModelError as error:
            # Translate the domain error into an HTTP status the client can act on,
            # preserving the original exception via `from` for the traceback.
            raise HTTPException(status_code=422, detail=str(error)) from error
        return document

    @router.get("/fuzzy/{system_id}/versions")
    def get_versions(system_id: str) -> list[str]:
        """Version ids of the saved snapshots, newest first."""
        # Version ids are opaque strings; their order (newest first) is decided
        # by `list_versions`, so the client can index `[0]` for the latest one.
        try:
            return list_versions(system_id, user_dir)
        except FuzzyModelError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/fuzzy/{system_id}/versions/{version_id}")
    def get_version(system_id: str, version_id: str) -> dict[str, Any]:
        """One saved snapshot of a rule base."""
        try:
            return load_version(system_id, version_id, user_dir)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="unknown version") from error
        except FuzzyModelError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/fuzzy/diff")
    def post_diff(request: DiffRequest) -> list[dict[str, Any]]:
        """Structural differences between two rule base documents (codes, not prose)."""
        return diff_documents(request.old, request.new)

    @router.post("/fuzzy/infer")
    def post_infer(request: InferRequest) -> dict[str, Any]:
        """What-if: evaluate the given rule base on one set of input values.

        The request carries a full fuzzy document (variables, membership
        functions and rules) plus one dict of input values in the variable's own
        unit, so the caller can preview what the model would answer without
        saving it first. Returns the JSON-serialisable inference payload; raises
        HTTP 422 when the document is invalid or the inputs cannot be evaluated.
        """
        # A fuzzy control system is defined by three parts: fuzzy variables
        # (each with membership functions such as "cold", "warm"), a rule base
        # ("IF temperature IS cold THEN fan IS slow" style) and an inference
        # method that combines them. The document in the request holds all three,
        # so this endpoint can evaluate a model the caller has not persisted.
        # _system_or_422 validates the document and converts it into an executable
        # model; a malformed document is the caller's error, hence 422.
        system = _system_or_422(request.document)
        try:
            # infer_payload runs the inference and returns the result already
            # shaped as plain JSON types (crisp outputs, membership degrees, ...).
            return infer_payload(system, request.inputs)
        except FuzzyModelError as error:
            # A FuzzyModelError means the model itself rejected the inputs (for
            # example a value outside the variable's universe of discourse), so
            # it is again a client error, not a server failure.
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/datasets/{dataset_id}/fuzzy/replay")
    def post_replay(dataset_id: str, request: ReplayRequest) -> dict[str, Any]:
        """Replay the given rule base over recorded data (what it would have said).

        "Replay" means: take the fuzzy inference system supplied in the request body and run it
        over the historical samples of a stored dataset, without changing the stored data. The
        answer shows which output the rule base *would* have produced at each timestamp, so a
        user can audit a rule base against past measurements before deploying it.

        Returns a JSON-serialisable dictionary with the replayed time series.

        Raises HTTPException with status 422 if the request body does not define a usable fuzzy
        system, or if the replay itself fails on the data (e.g. a variable is missing a range).
        """
        # Build the inferable model from the JSON document in the body. Returns a ready-to-use
        # system, or raises 422 when the document is malformed or incomplete.
        system = _system_or_422(request.document)

        # Load the stored dataset in wide layout (one row per timestamp, one column per signal)
        # and reduce it to the replay window asked for in the request.
        # t_ns holds the timestamp of each remaining sample in NANOSECONDS since the Unix epoch;
        # columns maps a signal name to its array of sample values over that same window.
        t_ns, columns = _window(load_wide(dataset_id), request)

        try:
            # Run the rule base over the window. max_points caps how many samples are returned,
            # so the response stays small for long datasets; the payload carries the timestamps,
            # the inputs and the replayed outputs.
            return replay_payload(system, t_ns, columns, request.max_points)
        except FuzzyModelError as error:
            # Domain-level failure (bad ranges, unknown variable, ...). Surface it to the client
            # as a validation error instead of a generic 500, keeping the original as the cause.
            raise HTTPException(status_code=422, detail=str(error)) from error

    return router


def _system_or_422(document: dict[str, Any]) -> FuzzySystem:
    """The system built from the document, or HTTP 422 with the reason."""
    try:
        return system_from_dict(document)
    except FuzzyModelError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _window(table: WideTable, request: ReplayRequest) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Slice a recording down to the time range the caller asked for.

    `table` is a "wide" table: one shared time axis plus one array per signal tag, so every
    column is aligned sample-by-sample with its timestamp. `request.start_s` and
    `request.end_s` are the requested bounds in seconds from the start of the recording
    (either may be None, meaning "no bound on that side").

    Returns the timestamps and columns that fall inside the window, with all arrays still
    aligned. Raises HTTPException(422) if the window is empty, because a replay with no
    samples is a client error rather than a bug in the server.
    """
    t_ns, columns = table
    # Rebase timestamps to start at zero: t_ns is absolute (UNIX nanoseconds), while the
    # request bounds are relative seconds-since-start, so they are only comparable here.
    seconds = (t_ns - t_ns[0]) / 1e9
    # Boolean mask over samples: start with everything kept, then drop what falls outside
    # each requested bound. `&=` keeps the mask the same length as `t_ns` (no copy/narrowing)
    # so it stays usable as an index for every column.
    keep = np.ones(len(t_ns), dtype=bool)
    if request.start_s is not None:
        keep &= seconds >= request.start_s
    if request.end_s is not None:
        keep &= seconds <= request.end_s
    if not keep.any():
        raise HTTPException(status_code=422, detail="no samples in the requested window")
    # Apply the same mask to the time axis and to each column, so all returned arrays keep
    # the row alignment of the original table.
    return t_ns[keep], {tag: values[keep] for tag, values in columns.items()}
