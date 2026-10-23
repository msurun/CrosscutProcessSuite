"""HTTP routes of the whole PI wide-file import: upload, preview, import.

Wraps crosscut_loops.plant_import and crosscut_loops.plant_import_write, the same code as the
command line. Raw bodies are streamed into ``<data root>/_uploads/<id>``; only POST /intake/plant/
import writes a dataset folder. Nothing here reaches a plant.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from crosscut_loops.plant_import import preview_plant
from crosscut_loops.plant_import_time import TimeZoneSpec
from crosscut_loops.plant_import_write import VALID_SCOPES, import_plant
from crosscut_loops.step_test_io import Note, decode_bytes
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

MAX_UPLOAD_BYTES = 300_000_000
UPLOAD_CHUNK_BYTES = 1_000_000
UPLOADS_FOLDER = "_uploads"
UPLOAD_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DATASET_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

Role = Literal["data", "dictionary"]


class TimeZoneBody(BaseModel):
    """How to read the naive local timestamps: 'utc', an IANA name or an hour offset."""

    kind: Literal["utc", "iana", "offset"] = "utc"
    value: str | float | None = None


class PreviewBody(BaseModel):
    """An uploaded data file, an optional dictionary and the time zone of the file."""

    data_upload: str
    dictionary_upload: str | None = None
    timezone: TimeZoneBody = Field(default_factory=TimeZoneBody)


class ImportBody(PreviewBody):
    """A preview body plus the dataset to create and which tags to keep."""

    dataset_id: str = Field(pattern=DATASET_ID_PATTERN)
    scope: Literal["loops", "process"] = "process"


def _unprocessable(message: object) -> HTTPException:
    """A 422 with a friendly message."""
    return HTTPException(status_code=422, detail=message)


def _uploads_dir(root: Path) -> Path:
    """The folder of raw uploads; its name starts with '_' so it is never a dataset."""
    folder = root / UPLOADS_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _check_upload_id(upload_id: str) -> str:
    """The upload id when it is 32 hex characters, else 422 (no path escapes)."""
    if not UPLOAD_ID_PATTERN.match(upload_id):
        raise _unprocessable(f"invalid upload id {upload_id!r}")
    return upload_id


def _check_dataset_id(root: Path, dataset_id: str) -> Path:
    """The free dataset folder under ``root`` (422 when invalid, 409 when non-empty)."""
    if dataset_id.startswith("_"):
        raise _unprocessable("invalid dataset id")
    out_dir = (root / dataset_id).resolve()
    if out_dir.parent != root.resolve():
        raise _unprocessable("invalid dataset id")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise HTTPException(status_code=409, detail=f"dataset '{dataset_id}' already exists")
    return out_dir


def _timezone_spec(body: TimeZoneBody) -> TimeZoneSpec:
    """The TimeZoneSpec of the request body; a missing value is reported as 422."""
    if body.kind == "utc":
        return TimeZoneSpec("utc", None)
    if body.value is None:
        raise _unprocessable(f"timezone kind '{body.kind}' needs a value")
    return TimeZoneSpec(body.kind, body.value)


def _note_dicts(notes: list[Note]) -> list[dict[str, Any]]:
    """Coded notes as JSON objects: code, English text and params."""
    return [asdict(note) for note in notes]


def _complete_loop_dicts(loops: list[Any]) -> list[dict[str, Any]]:
    """JSON-safe dictionaries of the complete detected loops."""
    return [asdict(loop) for loop in loops if loop.complete]


class _PlantImport:
    """Handlers of the plant import routes; ``root`` is the data root."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _upload_path(self, upload_id: str) -> Path:
        """The stored file of an upload id (404 when it was deleted or never made)."""
        path = _uploads_dir(self.root) / f"{_check_upload_id(upload_id)}.csv"
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"unknown upload '{upload_id}'")
        return path

    def _dictionary_text(self, upload_id: str | None) -> str | None:
        """The dictionary CSV text of an upload, or None when no dictionary was given."""
        if upload_id is None:
            return None
        return decode_bytes(self._upload_path(upload_id).read_bytes())

    async def upload(self, request: Request, role: Role) -> dict[str, Any]:
        """Stream a raw body to a new upload file; 413 above the size cap."""
        if role not in ("data", "dictionary"):
            raise _unprocessable(f"unknown role {role!r}; use 'data' or 'dictionary'")
        upload_id = uuid.uuid4().hex
        path = _uploads_dir(self.root) / f"{upload_id}.csv"
        try:
            size = await _stream_to_file(request, path)
        except _TooLarge as error:
            path.unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail="the file is larger than 300 MB") from error
        return {"upload_id": upload_id, "bytes": size}

    def delete_upload(self, upload_id: str) -> Response:
        """Delete an upload file; 204 also when it was already gone."""
        _check_upload_id(upload_id)
        (_uploads_dir(self.root) / f"{upload_id}.csv").unlink(missing_ok=True)
        return Response(status_code=204)

    def preview(self, body: PreviewBody) -> dict[str, Any]:
        """Read the data file once and describe it (422 on a bad file or dictionary)."""
        try:
            return preview_plant(
                self._upload_path(body.data_upload),
                self._dictionary_text(body.dictionary_upload),
                _timezone_spec(body.timezone),
            )
        except ValueError as error:
            raise _unprocessable(str(error)) from error

    def run_import(self, body: ImportBody) -> JSONResponse:
        """Write the dataset of the two uploads, delete them and report the result."""
        data_path = self._upload_path(body.data_upload)
        dictionary_text = self._dictionary_text(body.dictionary_upload)
        out_dir = _check_dataset_id(self.root, body.dataset_id)
        result = self._write(data_path, dictionary_text, out_dir, body)
        self._drop_uploads(body)
        return JSONResponse(status_code=201, content=_import_payload(body.dataset_id, result))

    def _write(self, data_path: Path, dictionary_text: str | None, out_dir: Path,
               body: ImportBody) -> Any:
        """Run import_plant, mapping its errors onto 409 and 422."""
        if body.scope not in VALID_SCOPES:
            raise _unprocessable(f"unknown scope {body.scope!r}")
        try:
            return import_plant(
                data_path, dictionary_text, out_dir, _timezone_spec(body.timezone), body.scope
            )
        except FileExistsError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (ValueError, OSError) as error:
            raise _unprocessable(f"could not import the file: {error}") from error

    def _drop_uploads(self, body: ImportBody) -> None:
        """Remove the two upload files after a successful import."""
        for upload_id in (body.data_upload, body.dictionary_upload):
            if upload_id is not None:
                (_uploads_dir(self.root) / f"{upload_id}.csv").unlink(missing_ok=True)


def _import_payload(dataset_id: str, result: Any) -> dict[str, Any]:
    """The JSON document of a finished import."""
    return {
        "dataset_id": dataset_id,
        "loops": _complete_loop_dicts(result.loops),
        "notes": _note_dicts(result.notes),
        "tags_written": result.tags_written,
        "tags_skipped": result.tags_skipped,
        "test_windows": result.windows,
    }


class _TooLarge(Exception):
    """The request body passed the upload size cap; the partial file must be removed."""


async def _stream_to_file(request: Request, path: Path) -> int:
    """Write the request body to ``path`` in chunks; return the byte count.

    Raises:
        _TooLarge: when more than MAX_UPLOAD_BYTES arrive; the caller removes the file.
    """
    written = 0
    with path.open("wb") as handle:
        async for chunk in request.stream():
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                raise _TooLarge()
            handle.write(chunk)
    return written


def build_plant_import_router(root: Path) -> APIRouter:
    """Routes /intake/plant/upload, /preview, /import; ``root`` is the data root."""
    handlers = _PlantImport(root)
    router = APIRouter()
    router.add_api_route("/intake/plant/upload", handlers.upload, methods=["POST"])
    router.add_api_route("/intake/plant/upload/{upload_id}", handlers.delete_upload,
                         methods=["DELETE"], status_code=204)  # fmt: skip
    router.add_api_route("/intake/plant/preview", handlers.preview, methods=["POST"])
    router.add_api_route("/intake/plant/import", handlers.run_import, methods=["POST"])
    return router
