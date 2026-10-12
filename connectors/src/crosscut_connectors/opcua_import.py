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

    OPC UA (Open Platform Communications Unified Architecture) is the industrial
    protocol used by PLCs and sensors to expose their values. Each value lives at
    a "node id" such as ``ns=2;s=Temperature``, and clients read nodes on demand:
    there is no push, so this client simply reads all nodes once per period.

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
    # Fail fast on bad parameters, before touching the network or the file system.
    _validate_arguments(nodes, n_samples, period_s)

    # Tag names come from an external config and may contain characters that are
    # illegal in column names, so each one is normalised into a "tag id".
    # ``tag_ids`` is aligned with ``nodes``: same order, same length.
    tag_ids = [_sanitize_tag_name(tag) for tag in nodes]

    # Two distinct tags may normalise to the same id, which would silently merge
    # two different signals into one column. The helper rejects that and returns
    # the list of ids with duplicates removed, still in first-seen order.
    unique_tag_ids = _check_identifier_uniqueness(nodes, tag_ids)

    # Node id strings, in the same order as ``unique_tag_ids``; that shared order
    # is the invariant that lets the collected columns be matched to the tags.
    node_ids = [nodes[tag] for tag in nodes]

    # One event loop runs the whole acquisition: connect, then read every node
    # ``n_samples`` times, sleeping ``period_s`` between rounds.
    # ``ts_ns`` are UTC epoch timestamps in nanoseconds (int64), shape (n_samples,);
    # ``values`` is shape (n_samples, n_tags); ``qualities`` is the same shape and
    # holds the OPC UA StatusCode of each read (0 = Good, non-zero = bad value).
    ts_ns, values, qualities = asyncio.run(
        _collect_samples(endpoint, node_ids, period_s, n_samples)
    )

    # Persist everything in one call so the dataset is written atomically.
    # ``start_utc`` is the ISO-8601 UTC time of the first sample; ``tags_document``
    # records, for each tag id, which OPC UA node id it was read from.
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
    """Reject arguments that would make the import meaningless or fail later.

    Called before any file or network access so the caller gets an early, clear
    error instead of a confusing failure deep inside the import.

    Args:
        nodes: Mapping of tag name -> node identifier. The tag is the column
            name used in the output; the value is the source path or address.
        n_samples: Number of samples to read per tag. Unit: samples (a count).
        period_s: Sampling interval between two consecutive samples. Unit: seconds.

    Raises:
        ValueError: If `nodes` is empty, if `n_samples` is below 1, or if
            `period_s` is zero or negative.
    """
    # An empty mapping would produce a file with no columns: the import has
    # nothing to do, so treat it as a caller mistake rather than a valid run.
    if not nodes:
        raise ValueError("nodes must contain at least one tag")
    # A count of samples is meaningless below 1; reading zero samples would
    # yield an empty frame that later aggregation steps cannot handle.
    if n_samples < 1:
        raise ValueError("n_samples must be at least 1")
    # period_s is the time step of the series, used to compute durations and
    # rates; zero would divide by zero there, a negative value would reverse time.
    if period_s <= 0:
        raise ValueError("period_s must be strictly positive")


def _check_identifier_uniqueness(
    nodes: Mapping[str, str], tag_ids: list[str]
) -> list[str]:
    """Validate that sanitised tag identifiers are unique.

    A "tag identifier" is the sanitised (cleaned up) form of a node name: sanitisation
    may map two distinct node names onto the same identifier, e.g. by lowercasing them
    or replacing spaces with underscores. `nodes` maps each original node name to its
    tag identifier; it is passed in for context and inspection but is not read here.

    Returns `tag_ids` unchanged when every identifier is distinct.

    Raises:
        ValueError: if two or more identifiers collide after sanitisation.
    """
    # A list holds one entry per node, so equal entries mean two nodes share an
    # identifier. A set holds at most one copy of each value, so comparing the two
    # lengths detects that collapse: equal lengths means no duplicates.
    if len(set(tag_ids)) != len(tag_ids):
        raise ValueError("duplicate tag identifiers after sanitisation")
    return tag_ids


async def _collect_samples(
    endpoint: str,
    node_ids: list[str],
    period_s: float,
    n_samples: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Connect, take ``n_samples`` samples at ``period_s`` apart, then disconnect.

    Returns three parallel arrays, each shaped ``(len(node_ids), n_samples)``:
    timestamps in nanoseconds since the epoch, values, and OPC UA status codes.
    A timestamp is shared by every node read in the same round, so all columns
    are sampled at the same instants and line up row by row.
    """
    # Accumulate samples in lists first; numpy arrays would need resizing on every round.
    ts_ns: list[int] = []
    rows: list[list[float]] = []
    # One growing quality list per node, in the same order as `node_ids`.
    column_qualities: list[list[int]] = [[] for _ in node_ids]

    client = Client(url=endpoint, timeout=CONNECT_TIMEOUT_S)
    try:
        await _connect(client)
        for sample_index in range(n_samples):
            # The first call returns immediately; later ones wait out the period.
            await _sleep_before_next_sample(sample_index, period_s)
            ts_ns.append(time.time_ns())
            # `sample` is a list of (value, quality) pairs, one per node in `node_ids`.
            sample = await _sample_all(client, node_ids)
            rows.append([value for value, _ in sample])
            # `zip` pairs each quality column with its node's (value, quality) pair;
            # `strict=True` guards against a server returning a different node count.
            for column, (_, quality) in zip(column_qualities, sample, strict=True):
                column.append(quality)
    finally:
        # Close the session even if a read or a sleep raised.
        await _disconnect(client)

    # `.T` turns the sample-major lists into node-major arrays, so every node is one row.
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
    """Read one node, returning a float value with GOOD, or NaN with BAD on any problem.

    This is the read half of an OPC UA poll. OPC UA servers report a per-read
    "status code" that says whether the value is trustworthy; a value that was
    produced by a dead device is still returned, but flagged. The status code
    from the wire is translated here into two local ints, GOOD or BAD, so the
    rest of the program never has to know OPC UA's constant values.

    Returns:
        (value, quality) where value is a finite float on success — with its
        node's native unit, which is not known at this layer — or NaN, and
        quality is GOOD or BAD. Never raises: a single bad node must not stop
        a whole poll.
    """
    # The network call is the only step that can fail for reasons outside the
    # node itself (server down, socket closed, session expired). Any transport
    # or protocol error is a BAD reading rather than an exception to the caller.
    try:
        data_value = await client.get_node(node_id).read_data_value()
    except (OSError, ua.UaError, ua.UaStatusCodeError):
        return float("nan"), BAD
    # The server answered, but the answer may carry a bad status code: the value
    # is present yet known to be stale, uncertain or produced by a fault.
    if not _is_status_good(data_value.StatusCode):
        return float("nan"), BAD
    # The inner Value is the variant payload (an untyped union); it is None when
    # the server has no value to offer for this node.
    if data_value.Value is None:
        return float("nan"), BAD
    # AttributeError: the server returned a structured or array variant instead
    # of a scalar, so .Value does not exist. TypeError: the payload is not
    # numeric at all. ValueError: it is a float-like string, e.g. "NaN", that
    # float() refuses. All three mean "not a usable number".
    try:
        value = float(data_value.Value.Value)
    except (AttributeError, TypeError, ValueError):
        return float("nan"), BAD
    # Guard against NaN and the infinities. NaN would silently poison every
    # later average or max, and an infinity is almost always a sensor fault.
    if not np.isfinite(value):
        return float("nan"), BAD
    return value, GOOD


def _is_status_good(status_code: Any) -> bool:
    """Return True when an OPC UA StatusCode represents success.

    OPC UA is the industrial protocol the server speaks. Every response carries a StatusCode: a
    32-bit unsigned integer where 0 means "good" and any other value encodes a failure (bad
    credentials, missing node, timeout...). This helper hides that encoding from the caller.

    Newer python-opcua versions call the helper ``is_good``; older versions expose
    only ``value == 0``. Try both so the reader works across versions.

    Returns:
        True if the status means success, False otherwise.
    """
    # Ask the StatusCode object for its own accessor; older builds have none, so this is None.
    is_good = getattr(status_code, "is_good", None)
    if callable(is_good):
        return bool(is_good())
    # Fallback for old builds: unwrap the raw integer via ``value`` when present, otherwise trust
    # the argument itself to be the integer. The constant 0 is the OPC UA "Good" code.
    return bool(getattr(status_code, "value", status_code) == 0)


def _start_iso(ts_ns: np.ndarray) -> str:
    """Return the first timestamp as an ISO-8601 string with a trailing Z, whole seconds."""
    return datetime.fromtimestamp(int(ts_ns[0]) // NS_PER_S, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _tags_document(tag_ids: list[str], node_ids: list[str]) -> dict[str, Any]:
    """Build the tags.json document: one float tag per identifier, sourced from OPC UA.

    A "tag" is one named measurement a data historian should collect. Here each tag is
    identified by its tag_id and read from an OPC UA "node", while node_ids are the OPC UA
    NodeId strings that address those values on the server.
    """
    # The two lists are zipped elementwise, so tag_ids[0] is read from node_ids[0].
    # strict=True makes zip() raise ValueError when the lists differ in length: a mismatch
    # would silently drop tags otherwise, and the caller would never learn about it.
    #
    # Each tag is a dict with fixed keys:
    #   schema_version (str)  - version of this file format, so readers can parse it later
    #   tags (list[dict])     - one entry per (tag_id, node_id) pair
    # Within an entry:
    #   id, name (str)        - same string; there is no separate human-facing label here
    #   description, unit     - empty strings: a float tag carries no engineering unit yet
    #   type (str)            - "float", the only value stored for every tag
    #   role (str)            - "other", a placeholder classification for consumers
    #   source (dict)         - how to fetch the value:
    #     driver (str)        - "opcua", i.e. an OPC UA client reads the address
    #     address (str)       - the OPC UA NodeId, e.g. "ns=2;s=Temperature"
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
    """Summarise the sampled grid as an OpcUaImportReport.

    `values` is the sampled "grid" of tag readings: one row per tag and one
    column per sample instant, so its second axis (shape[1]) is the number of
    sampling instants and its first axis (shape[0]) is the number of tags.
    `n_tags` is the number of tags discovered in the source, which can be
    larger than values.shape[0] because some tags may have produced no samples
    at all and therefore have no row in the grid.

    Returns the report counting columns, tags and cells that hold NaN.
    """
    return OpcUaImportReport(
        # Sampling instants captured, i.e. one axis-1 position per timestamp;
        # unit: instants (not seconds).
        n_rows=values.shape[1],
        # Tags seen in the source; kept as a separate argument on purpose
        # because tags without any sample never get a row in `values`.
        n_tags=n_tags,
        # A NaN marks a reading that was missing or unreadable at that instant.
        # np.isnan gives a boolean grid of the same shape, and sum() counts the
        # True cells, i.e. the number of bad readings; unit: cells.
        n_bad_values=int(np.isnan(values).sum()),
    )
