"""HTTP routes of the loop template library: built-in templates plus site overrides.

Built-in templates are packaged data under ``crosscut_loops/loop_templates``. A site saves an
edited copy under ``<data root>/_loop_templates/<key>.json``, which then shadows the built-in
template of the same key. Nothing here reaches a plant.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any

from crosscut_loops.loop_templates import (
    LoopTemplateError,
    load_loop_templates,
    validate_loop_template,
)
from fastapi import APIRouter, Body, HTTPException

CUSTOM_DIR = "_loop_templates"
ORIGIN_BUILTIN = "builtin"
ORIGIN_SITE = "site"


def _read_document(path: Path) -> Any:
    """Read one JSON file, naming the file in every failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise LoopTemplateError(f"Invalid loop template file {path}: {error}") from error


def _write_document(path: Path, document: dict[str, Any]) -> None:
    """Write a template atomically so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(temp_name, path)


class _LoopTemplateEndpoints:
    """Template handlers bound to the project data root."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def list_templates(self) -> dict[str, Any]:
        """Return every template, with its origin, sorted by key."""
        merged = self._merged()
        return {
            "templates": [
                self._with_origin(merged[key][0], merged[key][1]) for key in sorted(merged)
            ]
        }

    def get_template(self, key: str) -> dict[str, Any]:
        """Return one template, 404 when neither the site nor the library has it."""
        merged = self._merged()
        if key not in merged:
            raise HTTPException(status_code=404, detail=f"unknown loop template: {key}")
        record, origin = merged[key]
        return self._with_origin(record, origin)

    def put_template(self, key: str, document: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        """Validate and save a site copy of a template, 422 when it breaks the contract."""
        try:
            record = validate_loop_template(document)
        except LoopTemplateError as error:
            raise HTTPException(status_code=422, detail=[str(error)]) from error
        if record["key"] != key:
            raise HTTPException(
                status_code=422,
                detail=[f"key: {record['key']!r} does not match the route key {key!r}"],
            )
        _write_document(self._custom_path(key), record)
        return self._with_origin(record, ORIGIN_SITE)

    def _merged(self) -> dict[str, tuple[dict[str, Any], str]]:
        """Built-in templates first, then site copies that shadow the same key."""
        merged = {
            key: (record, ORIGIN_BUILTIN) for key, record in load_loop_templates().items()
        }
        for key, record in self._custom_records().items():
            merged[key] = (record, ORIGIN_SITE)
        return merged

    def _custom_records(self) -> dict[str, dict[str, Any]]:
        """Read and validate every site template; 422 lists the first invalid file."""
        folder = self.root / CUSTOM_DIR
        if not folder.is_dir():
            return {}
        records: dict[str, dict[str, Any]] = {}
        for path in sorted(folder.glob("*.json")):
            try:
                record = validate_loop_template(_read_document(path))
            except LoopTemplateError as error:
                raise HTTPException(status_code=422, detail=[str(error)]) from error
            if record["key"] != path.stem:
                raise HTTPException(
                    status_code=422,
                    detail=[f"{path.name}: key {record['key']!r} does not match the file name"],
                )
            records[record["key"]] = record
        return records

    def _custom_path(self, key: str) -> Path:
        """File of one site template; the schema pattern keeps the key a plain name."""
        return self.root / CUSTOM_DIR / f"{key}.json"

    @staticmethod
    def _with_origin(record: dict[str, Any], origin: str) -> dict[str, Any]:
        """The template plus where it comes from, for the editor."""
        return {**record, "origin": origin}


def build_loop_template_router(root: Path) -> APIRouter:
    """Routes for GET /loop-templates, GET /loop-templates/{key} and PUT of one template."""
    endpoints = _LoopTemplateEndpoints(root)
    router = APIRouter()
    router.add_api_route("/loop-templates", endpoints.list_templates, methods=["GET"])
    router.add_api_route("/loop-templates/{key}", endpoints.get_template, methods=["GET"])
    router.add_api_route("/loop-templates/{key}", endpoints.put_template, methods=["PUT"])
    return router
