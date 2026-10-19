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
from typing import Any

import numpy as np
from asyncua import Client, ua
from crosscut_sim.core import BAD, GOOD
from crosscut_sim.dataset import DatasetInfo, Samples, write_dataset

from crosscut_connectors.csv_import import _sanitize_tag_name
from crosscut_connectors.import_target import ImportTarget

CONNECT_TIMEOUT_S = 5.0
RECONNECT_ATTEMPTS = 3  # tries to restore a lost session before the round stays BAD
RECONNECT_DELAY_S = 1.0  # wait between two reconnect tries, in seconds
NAMESPACE_URI_PREFIX = "nsu="  # OPC UA "ExpandedNodeId" form: nsu=<namespace uri>;s=<name>
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


@dataclass(frozen=True)
class PollPlan:
    """How often and how many times the nodes are read.

    Attributes
    ----------
    period_s: float
        Delay in seconds between two samples; must be strictly positive.
    n_samples: int
        Number of samples to take; must be at least one.
    """

    period_s: float = 1.0
    n_samples: int = 10


def import_opcua(
    endpoint: str,
    nodes: Mapping[str, str],
    target: ImportTarget,
    plan: PollPlan = PollPlan(),  # noqa: B008 - frozen dataclass, safe as a shared default
) -> OpcUaImportReport:
    """Poll the given OPC UA nodes and write the samples as a dataset.

    OPC UA (Open Platform Communications Unified Architecture) is the industrial
    protocol used by PLCs and sensors to expose their values. Each value lives at
    a "node id" such as ``ns=2;s=Temperature``. This importer polls: it reads all nodes
    once per period (``opcua_subscribe`` is the variant where the server pushes changes).

    Parameters
    ----------
    endpoint: str
        OPC UA endpoint URL of the server to connect to.
    nodes: Mapping[str, str]
        Mapping of output tag name to OPC UA node id string.
    target: ImportTarget
        Output directory and dataset id (its timezone is unused: samples are
        stamped from the local clock in UTC).
    plan: PollPlan
        Sampling period and number of samples.

    Returns
    -------
    OpcUaImportReport
        Summary of the import operation.

    Raises
    ------
    ValueError
        If ``nodes`` is empty, or ``plan.n_samples`` is not positive, or
        ``plan.period_s`` is not strictly positive.
    ConnectionError
        If the endpoint cannot be reached, or the connection times out.
    """
    _validate_arguments(nodes, plan)

    # Tag names come from an external config and may contain characters that are
    # illegal in column names, so each one is normalised into a "tag id".
    # ``tag_ids`` is aligned with ``nodes``: same order, same length.
    tag_ids = [_sanitize_tag_name(tag) for tag in nodes]

    # Two distinct tags may normalise to the same id, which would silently merge
    # two different signals into one column. The helper raises in that case and
    # returns the list unchanged otherwise.
    unique_tag_ids = _check_identifier_uniqueness(tag_ids)

    # Node id strings, in the same order as ``nodes``; the parallel order with
    # ``tag_ids`` (and therefore ``unique_tag_ids``) is what lets the collected
    # columns be matched to the tags.
    node_ids = [nodes[tag] for tag in nodes]

    # One event loop runs the whole acquisition: connect, then read every node
    # ``n_samples`` times, sleeping ``period_s`` between rounds.
    # ``ts_ns`` are UTC epoch timestamps in nanoseconds (int64), shape
    # (n_samples,); ``values`` is shape (n_tags, n_samples); ``qualities`` is
    # the same shape and holds local GOOD/BAD ints, not raw OPC UA StatusCodes.
    ts_ns, values, qualities = asyncio.run(_collect_samples(endpoint, node_ids, plan))

    # Persist everything in one call: samples, tag list and source description.
    info = _dataset_info(target.dataset_id, endpoint, ts_ns, (unique_tag_ids, node_ids))
    write_dataset(target.out_dir, Samples(ts_ns, unique_tag_ids, values, qualities), info)

    return _make_report(values, len(unique_tag_ids))


def _dataset_info(
    dataset_id: str,
    endpoint: str,
    ts_ns: np.ndarray,
    tags_and_nodes: tuple[list[str], list[str]],
) -> DatasetInfo:
    """Describe the dataset: OPC UA source, first-sample time and tag-to-node mapping.

    ``tags_and_nodes`` is (tag_ids, node_ids), parallel lists: the tags document
    records, for each tag id, which OPC UA node id it was read from.
    """
    tag_ids, node_ids = tags_and_nodes
    return DatasetInfo(
        dataset_id=dataset_id,
        source={"kind": "opcua", "endpoint": endpoint},
        start_utc=_start_iso(ts_ns),
        tags_document=_tags_document(tag_ids, node_ids),
    )


def _validate_arguments(nodes: Mapping[str, str], plan: PollPlan) -> None:
    """Reject arguments that would make the import meaningless or fail later.

    Called before any file or network access so the caller gets an early, clear
    error instead of a confusing failure deep inside the import.

    Args:
        nodes: Mapping of tag name -> node identifier. The tag is the column
            name used in the output; the value is the source path or address.
        plan: Sampling plan; ``n_samples`` is a count of samples per tag and
            ``period_s`` the interval between two consecutive samples, in seconds.

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
    if plan.n_samples < 1:
        raise ValueError("n_samples must be at least 1")
    # period_s is the time step of the series, used to compute durations and
    # rates; zero would divide by zero there, a negative value would reverse time.
    if plan.period_s <= 0:
        raise ValueError("period_s must be strictly positive")


def _check_identifier_uniqueness(tag_ids: list[str]) -> list[str]:
    """Validate that sanitised tag identifiers are unique.

    A "tag identifier" is the sanitised (cleaned up) form of a node name: sanitisation
    may map two distinct node names onto the same identifier, e.g. by lowercasing them
    or replacing spaces with underscores.

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
    plan: PollPlan,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Connect, take ``plan.n_samples`` samples ``plan.period_s`` apart, then disconnect.

    Returns timestamps ``(n_samples,)`` in nanoseconds since the epoch, then values and
    qualities, each shaped ``(len(node_ids), n_samples)``. A timestamp is shared by
    every node read in the same round, so all columns line up.
    """
    client = Client(url=endpoint, timeout=CONNECT_TIMEOUT_S)
    try:
        await _connect(client)
        ts_ns, rows, column_qualities = await _poll_rounds(client, node_ids, plan)
    finally:
        # Close the session even if a read or a sleep raised.
        await _disconnect(client)

    # `.T` turns the sample-major lists into node-major arrays, so every node is one row.
    return (
        np.array(ts_ns, dtype=np.int64),
        np.array(rows, dtype=np.float64).T,
        np.array(column_qualities, dtype=np.uint8).T,
    )


async def _poll_rounds(
    client: Client, node_ids: list[str], plan: PollPlan
) -> tuple[list[int], list[list[float]], list[list[int]]]:
    """Read every node ``plan.n_samples`` times; return timestamps, value rows, quality columns."""
    # Accumulate in lists first; numpy arrays would need resizing on every round.
    ts_ns: list[int] = []
    rows: list[list[float]] = []
    # One growing quality list per node, in the same order as `node_ids`.
    column_qualities: list[list[int]] = [[] for _ in node_ids]
    # Namespace indexes belong to one session, so they are looked up again after a reconnect.
    resolved = [await resolve_node_id(client, node_id) for node_id in node_ids]
    for sample_index in range(plan.n_samples):
        # The first call returns immediately; later ones wait out the period.
        await _sleep_before_next_sample(sample_index, plan.period_s)
        ts_ns.append(time.time_ns())
        # `sample` is a list of (value, quality) pairs, one per node in `node_ids`.
        sample = await _sample_all(client, resolved)
        if all(np.isnan(value) for value, _ in sample) and await _restore_session_if_lost(client):
            resolved = [await resolve_node_id(client, node_id) for node_id in node_ids]
        rows.append([value for value, _ in sample])
        # `strict=True` guards against a mismatch between the node list and the sample.
        for column, (_, quality) in zip(column_qualities, sample, strict=True):
            column.append(quality)
    return ts_ns, rows, column_qualities


async def _connect(client: Client) -> None:
    """Connect to the server, turning any low-level failure into a ConnectionError."""
    try:
        await client.connect()
    except (TimeoutError, OSError, ua.UaError, ua.UaStatusCodeError) as error:
        raise ConnectionError(f"could not connect to {client.server_url}: {error}") from error


async def resolve_node_id(client: Client, node_id: str) -> str:
    """Turn ``nsu=<uri>;s=Tag`` into ``ns=<index>;s=Tag``; other forms pass through unchanged.

    Namespace indexes are assigned per server session and change when the server restarts or is
    replaced, so a configuration should name the namespace by its URI and look the index up here.

    Raises:
        ValueError: if the server does not publish a namespace with that URI.
    """
    if not node_id.startswith(NAMESPACE_URI_PREFIX):
        return node_id
    uri, separator, identifier = node_id[len(NAMESPACE_URI_PREFIX) :].partition(";")
    if not separator or not uri:
        raise ValueError(f"node id {node_id!r} must look like 'nsu=<uri>;s=<name>'")
    try:
        index = await client.get_namespace_index(uri)
    except ValueError as error:
        raise ValueError(f"namespace {uri!r} is not published by the server") from error
    return f"ns={index};{identifier}"


async def _restore_session_if_lost(client: Client) -> bool:
    """After a round with no usable value: if the session is dead, reconnect (a few tries).

    A round of only BAD values has two causes: wrong node ids (the session is fine, nothing to do)
    or a lost connection. ``check_connection`` tells them apart; if every try fails the round
    simply stays BAD and the next round tries again, so a long outage never aborts the import.
    Returns True when a new session was opened (the caller must look up namespace indexes again).
    """
    try:
        await client.check_connection()
        return False
    except (OSError, ua.UaError, ua.UaStatusCodeError, ConnectionError, TimeoutError):
        pass
    for _ in range(RECONNECT_ATTEMPTS):
        await _disconnect(client)
        try:
            await client.connect()
            return True
        except (OSError, ua.UaError, ua.UaStatusCodeError, TimeoutError):
            await asyncio.sleep(RECONNECT_DELAY_S)
    return False


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
    32-bit unsigned integer where 0 is "Good"; the top two bits give the severity (good,
    uncertain, bad) and the rest says why (missing node, timeout...). This helper hides that
    encoding from the caller.

    asyncua's StatusCode has an ``is_good()`` method; for an object that exposes only the
    raw number the fallback compares ``value == 0``. Try both.

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
    return datetime.fromtimestamp(int(ts_ns[0]) // NS_PER_S, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    `n_tags` is passed in and equals shape[0].

    Returns the report with the number of sampling instants, the number of tags and the
    number of cells that hold NaN.
    """
    return OpcUaImportReport(
        # Sampling instants captured, i.e. one axis-1 position per timestamp;
        # unit: instants (not seconds).
        n_rows=values.shape[1],
        # Number of tags (rows of `values`).
        n_tags=n_tags,
        # A NaN marks a reading that was missing or unreadable at that instant.
        # np.isnan gives a boolean grid of the same shape, and sum() counts the
        # True cells, i.e. the number of bad readings; unit: cells.
        n_bad_values=int(np.isnan(values).sum()),
    )
