"""
Generic schema and config routes for the schema-driven form renderer (issue #45).
Provides the front door for loading schemas and validating/storing configuration
documents; nothing in this module reaches a plant.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any

from crosscut_connectors.site import validate_site
from fastapi import APIRouter, Body, HTTPException
from fastapi import Path as PathParam
from jsonschema import Draft202012Validator

AID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
Id = Annotated[str, PathParam(pattern=AID_PATTERN)]

_KINDS: dict[str, tuple[str, str | None]] = {
    "anomaly": ("_anomaly", None),
    "softsensor": ("_softsensor", None),
    "supervisor": ("_supervisor", None),
    "site": ("_site", "site.json"),
}


def schema_dir() -> Path:
    """Return the directory containing JSON Schema files, honoring an environment override."""
    env_override = os.environ.get("CROSSCUT_SCHEMAS_DIR")
    if env_override:
        return Path(env_override)
    return Path(__file__).resolve().parents[3] / "schemas"


def _config_path(root: Path, kind: str, config_id: str) -> Path:
    """Resolve the file path for a given kind and config id, enforcing fixed-name constraints."""
    folder, fixed = _KINDS[kind]
    if fixed is not None and config_id != fixed.removesuffix(".json"):
        raise HTTPException(status_code=404, detail=f"unknown {kind} config id: {config_id!r}")
    return root / folder / (fixed if fixed is not None else f"{config_id}.json")


def _where(path: Any) -> str:
    """Render a JSON pointer path for error messages, defaulting to the document root."""
    return ".".join(str(part) for part in path) or "root"


def _schema_problems(schema_name: str, document: dict[str, Any]) -> list[str]:
    """Validate a document against a named schema and return human-readable problems."""
    schema_path = schema_dir() / schema_name
    with open(schema_path, encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    return [f"{_where(error.absolute_path)}: {error.message}" for error in errors]


def _read(path: Path, kind: str, config_id: str) -> dict[str, Any]:
    """Load and parse a JSON config file, converting JSON errors to HTTP 422 responses."""
    try:
        with open(path, encoding="utf-8") as config_file:
            document: dict[str, Any] = json.load(config_file)
        return document
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=422,
            detail=[f"{kind} config is not valid JSON: {error}"],
        ) from error


def _write(path: Path, document: dict[str, Any]) -> None:
    """Write a JSON document atomically using a temporary file and replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(temp_name, path)


class _SchemaEndpoints:
    """Endpoint handlers for schema and config operations."""

    def __init__(self, root: Path) -> None:
        """Initialize with the root directory for config storage."""
        self._root = root

    def list_schemas(self) -> dict[str, list[str]]:
        """Return a sorted list of available schema names."""
        names = [
            path.stem.removesuffix(".schema")
            for path in schema_dir().glob("*.schema.json")
        ]
        return {"schemas": sorted(names)}

    def get_schema(self, name: str) -> dict[str, Any]:
        """Return the parsed JSON document for a given schema name."""
        schema_path = schema_dir() / f"{name}.schema.json"
        if not schema_path.is_file():
            raise HTTPException(status_code=404, detail=f"unknown schema: {name}")
        with open(schema_path, encoding="utf-8") as schema_file:
            document: dict[str, Any] = json.load(schema_file)
        return document

    def get_config(self, kind: str, config_id: Id) -> dict[str, Any]:
        """Return the config document for a given kind and id, or 404 if missing."""
        if kind not in _KINDS:
            raise HTTPException(status_code=404, detail=f"unknown config kind: {kind}")
        path = _config_path(self._root, kind, config_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"no {kind} config: {config_id}")
        return _read(path, kind, config_id)

    def put_config(
        self,
        kind: str,
        config_id: Id,
        document: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        """Validate and store a config document, returning the stored document."""
        if kind not in _KINDS:
            raise HTTPException(status_code=404, detail=f"unknown config kind: {kind}")
        problems = self._problems(kind, config_id, document)
        if problems:
            raise HTTPException(status_code=422, detail=problems)
        path = _config_path(self._root, kind, config_id)
        _write(path, document)
        return document

    def _problems(self, kind: str, config_id: str, document: dict[str, Any]) -> list[str]:
        """Return validation problems for a kind, config id, and document."""
        if kind == "site":
            return validate_site(document)
        schema_name = f"{kind}.schema.json"
        problems = _schema_problems(schema_name, document)
        if "id" in document and document["id"] != config_id:
            problems.append(f"id: {document['id']!r} does not match {config_id!r}")
        return problems


def build_schema_router(root: Path) -> APIRouter:
    """Create and return the APIRouter for schema and config endpoints."""
    endpoints = _SchemaEndpoints(root)
    router = APIRouter()
    router.add_api_route("/schemas", endpoints.list_schemas, methods=["GET"])
    router.add_api_route("/schemas/{name}", endpoints.get_schema, methods=["GET"])
    router.add_api_route("/config/{kind}/{config_id}", endpoints.get_config, methods=["GET"])
    router.add_api_route("/config/{kind}/{config_id}", endpoints.put_config, methods=["PUT"])
    return router
