# connectors/src/crosscut_connectors/opcua_import.py
"""Import a dataset by polling OPC UA nodes over a fixed number of samples.

The importer connects to an OPC UA server, reads a value from every configured
node at a fixed period, and writes the collected samples as a dataset. A node
that returns a bad status code, raises, or yields a non-numeric value becomes a
NaN value with BAD quality; every other numeric value keeps its own quality of
GOOD. The importer never writes to the server.

The importer writes the dataset to the specified output directory and returns an
OpcUaImportReport that summarizes the import operation.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from asyncua import Client, ua
from crosscut_sim.core import BAD, GOOD
from crosscut_sim.dataset import write_dataset

from crosscut_connectors.csv_import import _sanitize_tag_name

CONNECT_TIMEOUT_S = 5.0
NS_PER_S = 1_000_000_000


@dataclass(frozen=True)
class OpcUaImportReport:
    """Summary of the import operation.

    Attributes
    ----------
    n_rows: int
        Number of samples in the dataset.
    n_tags: int
        Number of tags in the dataset.
    n_bad_values: int
        Number of samples whose value is NaN (bad quality).
    """

    n_rows: int
    n_tags: int
    n_bad_values: int


def import_opcua(
    endpoint: str,
    nodes: Mapping[str, str],
    out_dir: Path,
    *,
    dataset_id: str,
    period_s: float = 1.0,
    n_samples: int = 10,
) -> OpcUaImportReport:
    """Poll the given OPC UA nodes and write the samples as a dataset.

    Parameters
    ----------
    endpoint: str
        OPC UA endpoint URL of the server to connect to.
    nodes: Mapping[str, str]
        Mapping of output tag name to OPC UA node id string.
    out_dir: Path
        Destination directory for the created dataset.
    dataset_id: str
        Identifier used inside the dataset metadata.
    period_s: float
        Delay in seconds between two samples; must be strictly positive.
    n_samples: int
        Number of samples to take; must be at least one.

    Returns
    -------
    OpcUaImportReport
        Summary of the import operation.

    Raises
    ------
    ValueError
        If ``nodes`` is empty, or ``n_samples`` is not positive, or ``period_s``
        is not strictly positive.
    ConnectionError
        If the endpoint cannot be reached, or the connection times out.
    """
    _validate_arguments(nodes, n_samples, period_s)
    tag_ids = [_sanitize_tag_name(tag) for tag in nodes]
    unique_tag_ids = _check_identifier_uniqueness(nodes, tag_ids)
    node_ids = [nodes[tag] for tag in nodes]

    ts_ns, values, qualities = asyncio.run(
        _collect_samples(endpoint, node_ids, period_s, n_samples)
    )

    write_dataset(
        out_dir,
        ts_ns,
        unique_tag_ids,
        values,
        qualities,
        dataset_id=dataset_id,
        source={"kind": "opcua", "endpoint": endpoint},
        start_utc=_start_iso(ts_ns),
        tags_document=_tags_document(unique_tag_ids, node_ids),
    )

    return _make_report(values, len(unique_tag_ids))


def _validate_arguments(nodes: Mapping[str, str], n_samples: int, period_s: float) -> None:
    """Reject arguments that would make the import meaningless or fail later."""
    if not nodes:
        raise ValueError("nodes must contain at least one tag")
    if n_samples < 1:
        raise ValueError("n_samples must be at least 1")
    if period_s <= 0:
        raise ValueError("period_s must be strictly positive")


def _check_identifier_uniqueness(
    nodes: Mapping[str, str], tag_ids: list[str]
) -> list[str]:
    """Return unique tag identifiers, rejecting collisions after sanitisation."""
    if len(set(tag_ids)) != len(tag_ids):
        raise ValueError("duplicate tag identifiers after sanitisation")
    return tag_ids


async def _collect_samples(
    endpoint: str,
    node_ids: list[str],
    period_s: float,
    n_samples: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Connect, take ``n_samples`` samples at ``period_s`` apart, then disconnect."""
    ts_ns: list[int] = []
    rows: list[list[float]] = []
    column_qualities: list[list[int]] = [[] for _ in node_ids]

    client = Client(url=endpoint, timeout=CONNECT_TIMEOUT_S)
    try:
        await _connect(client)
        for sample_index in range(n_samples):
            await _sleep_before_next_sample(sample_index, period_s)
            ts_ns.append(time.time_ns())
            sample = await _sample_all(client, node_ids)
            rows.append([value for value, _ in sample])
            for column, (_, quality) in zip(column_qualities, sample, strict=True):
                column.append(quality)
    finally:
        await _disconnect(client)

    return (
        np.array(ts_ns, dtype=np.int64),
        np.array(rows, dtype=np.float64).T,
        np.array(column_qualities, dtype=np.uint8).T,
    )


async def _connect(client: Client) -> None:
    """Connect to the server, turning any low-level failure into a ConnectionError."""
    try:
        await client.connect()
    except (TimeoutError, OSError, ua.UaError, ua.UaStatusCodeError) as error:
        raise ConnectionError(f"could not connect to {client.server_url}: {error}") from error


async def _disconnect(client: Client) -> None:
    """Close the connection, ignoring failures since the dataset is already collected."""
    try:
        await client.disconnect()
    except (OSError, ua.UaError):
        pass


async def _sleep_before_next_sample(sample_index: int, period_s: float) -> None:
    """Wait `period_s` between samples; the first sample is taken immediately."""
    if sample_index > 0:
        await asyncio.sleep(period_s)


async def _sample_all(client: Client, node_ids: list[str]) -> list[tuple[float, int]]:
    """Read every node once and return (value, quality) per node, in input order."""
    return [await _read_one(client, node_id) for node_id in node_ids]


async def _read_one(client: Client, node_id: str) -> tuple[float, int]:
    """Read one node, returning a float value with GOOD, or NaN with BAD on any problem."""
    try:
        data_value = await client.get_node(node_id).read_data_value()
    except (OSError, ua.UaError, ua.UaStatusCodeError):
        return float("nan"), BAD
    if not _is_status_good(data_value.StatusCode):
        return float("nan"), BAD
    if data_value.Value is None:
        return float("nan"), BAD
    try:
        value = float(data_value.Value.Value)
    except (AttributeError, TypeError, ValueError):
        return float("nan"), BAD
    if not np.isfinite(value):
        return float("nan"), BAD
    return value, GOOD


def _is_status_good(status_code: Any) -> bool:
    """Return True when an OPC UA StatusCode represents success.

    Newer python-opcua versions call the helper ``is_good``; older versions expose
    only ``value == 0``. Try both so the reader works across versions.
    """
    is_good = getattr(status_code, "is_good", None)
    if callable(is_good):
        return bool(is_good())
    return bool(getattr(status_code, "value", status_code) == 0)


def _start_iso(ts_ns: np.ndarray) -> str:
    """Return the first timestamp as an ISO-8601 string with a trailing Z, whole seconds."""
    return datetime.fromtimestamp(int(ts_ns[0]) // NS_PER_S, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _tags_document(tag_ids: list[str], node_ids: list[str]) -> dict[str, Any]:
    """Build the tags.json document: one float tag per identifier, sourced from OPC UA."""
    return {
        "schema_version": "0.1.0",
        "tags": [
            {
                "id": tag_id,
                "name": tag_id,
                "description": "",
                "unit": "",
                "type": "float",
                "role": "other",
                "source": {"driver": "opcua", "address": node_id},
            }
            for tag_id, node_id in zip(tag_ids, node_ids, strict=True)
        ],
    }


def _make_report(values: np.ndarray, n_tags: int) -> OpcUaImportReport:
    """Summarise the sampled grid as an OpcUaImportReport."""
    return OpcUaImportReport(
        n_rows=values.shape[1],
        n_tags=n_tags,
        n_bad_values=int(np.isnan(values).sum()),
    )
