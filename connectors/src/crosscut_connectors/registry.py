"""Connector registry and driver factory (Phase 1, #43).

Instantiates the appropriate Connector adapter based on driver name ("opcua", "sql", "csv")
declared in the site catalogue sources block.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from crosscut_connectors.base import Connector
from crosscut_connectors.csv_connector import CsvConnector
from crosscut_connectors.opcua_connector import OpcUaConnector
from crosscut_connectors.piwebapi_connector import PiWebApiConnector
from crosscut_connectors.sql_connector import SqlConnector

PROFILE_KEYS = ("profile", "profile_path")


def create_connector(
    driver: str,
    endpoint: str,
    options: Mapping[str, Any] | None = None,
) -> Connector:
    """Factory creating a concrete Connector adapter for the specified driver."""
    normalized = driver.lower().strip()
    if normalized == "csv":
        return CsvConnector(endpoint, options)
    if normalized == "sql":
        return SqlConnector(endpoint, options)
    if normalized in {"pi", "piwebapi"}:
        return PiWebApiConnector(endpoint, options)
    if normalized == "opcua":
        return OpcUaConnector(endpoint, options)
    raise ValueError(f"unknown connector driver: {driver!r}")


def connector_from_source(source_def: Mapping[str, Any]) -> Connector:
    """Instantiate a connector from a site catalogue source specification.

    A source-level ``profile`` or ``profile_path`` is copied into the driver options,
    where every adapter reads its settings; explicit options win if both are present.
    """
    driver = str(source_def["driver"])
    endpoint = str(source_def.get("endpoint", ""))
    options = dict(source_def.get("options") or {})
    for field in ("base_url", "data_server", "web_id", "auth"):
        if field in source_def:
            options[field] = source_def[field]
    for key in PROFILE_KEYS:
        if key in source_def and key not in options:
            options[key] = source_def[key]
    return create_connector(driver, endpoint, options)
