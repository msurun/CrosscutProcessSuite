"""Collect samples from a running OPC UA plant server into a Parquet dataset.

Command line: ``python -m crosscut_opcua.collector --help``.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from asyncua import Client, ua
from asyncua.common.node import Node
from asyncua.ua.attribute_ids import AttributeIds
from crosscut_sim.dataset import DEFAULT_START_UTC, write_dataset
from crosscut_sim.run import PLANTS, parse_duration
from crosscut_sim.scenarios import build_scenario

from crosscut_opcua.server import EXTRA_TAGS, NAMESPACE_URI, PLANT_OBJECT_NAME, TIME_TAG

GOOD_QUALITY = 0
BAD_QUALITY = 2


def _utc_to_ns(text: str) -> int:
    dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return int(dt.timestamp()) * 10**9


async def _discover_plant_nodes(client: Client, idx: int) -> tuple[Node, list[Node], list[str]]:
    """Return the time node, the plant tag nodes (server order) and their tag ids."""
    plant_obj = await _find_plant_object(client)
    time_node, tag_nodes, tag_ids = await _collect_plant_tags(plant_obj, idx)
    return time_node, tag_nodes, tag_ids


async def _find_plant_object(client: Client) -> Node:
    """Return the server's plant object node. Raise RuntimeError when it is absent."""
    for child in await client.nodes.objects.get_children():
        if (await child.read_browse_name()).Name == PLANT_OBJECT_NAME:
            return child
    raise RuntimeError(f"no '{PLANT_OBJECT_NAME}' object in the server address space")


async def _collect_plant_tags(plant_obj: Node, idx: int) -> tuple[Node, list[Node], list[str]]:
    """Split the plant variables into the time tag and the remaining tag nodes with their ids."""
    time_node: Node | None = None
    tag_nodes: list[Node] = []
    tag_ids: list[str] = []
    for node in await plant_obj.get_children(nodeclassmask=ua.NodeClass.Variable):
        tag_id = str(node.nodeid.Identifier)
        if tag_id == TIME_TAG:
            time_node = node
        elif tag_id not in EXTRA_TAGS:
            tag_nodes.append(node)
            tag_ids.append(tag_id)
    if time_node is None:
        raise RuntimeError(f"time tag {TIME_TAG!r} not found in namespace {idx}")
    return time_node, tag_nodes, tag_ids


async def collect(
    endpoint: str,
    out_dir: str | Path,
    *,
    sim_duration_s: float,
    sample_period_s: float,
    dataset_id: str,
    plant_name: str,
    scenario_name: str | None = None,
    seed: int | None = None,
    start_utc: str = DEFAULT_START_UTC,
    timeout_s: float = 3600.0,
    poll_s: float = 0.01,
    git_commit: str | None = None,
) -> dict[str, Any]:
    """Record plant samples from an OPC UA server into ``out_dir`` and return the dataset document.

    OPC UA is an industrial protocol: the client connects to an ``endpoint`` URL and reads
    *nodes*, each addressed by a numeric node id. Here one node carries the plant clock (simulated
    seconds, not wall-clock time) and the remaining nodes carry the tag values recorded in the
    dataset.

    Sampling rule: samples are taken whenever the plant clock has advanced by ``sample_period_s``
    since the last sample; the first poll is always recorded. Sample timestamps are ``start_utc``
    plus the plant time elapsed since the first sample, so the dataset is reproducible regardless
    of how fast the simulation actually runs.

    Parameters
    ----------
    sim_duration_s
        Length of the recording in plant seconds. Polling stops once the plant clock has advanced
        this far past the first sample.
    sample_period_s
        Minimum plant-time step (s) between two recorded samples; sets the dataset's sampling rate.
    timeout_s
        Wall-clock budget (s) for the whole collection, independent of ``sim_duration_s``.
    poll_s
        Idle sleep (s) between two reads of the OPC UA server; 0 means "poll as fast as possible".

    Returns
    -------
    dict[str, Any]
        The dataset document written by :func:`write_dataset` (metadata plus file references).

    Raises
    ------
    ValueError
        If ``sim_duration_s``, ``sample_period_s`` or ``poll_s`` is not usable.
    TimeoutError
        If ``sim_duration_s`` of plant time has not elapsed within ``timeout_s`` wall seconds.
    """
    # Reject impossible sampling settings before touching the network. Checking one condition
    # keeps the error message focused; a negative poll_s would busy-loop, so it is rejected too.
    if sim_duration_s <= 0 or sample_period_s <= 0 or poll_s < 0:
        raise ValueError("sim_duration_s and sample_period_s must be positive")

    # `start_ns` is the Unix epoch timestamp of the dataset's first instant, in nanoseconds, so
    # that sample times can later be reconstructed as `start_ns + elapsed*1e9` without doing
    # floating-point time arithmetic on absolute dates.
    start_ns = _utc_to_ns(start_utc)
    # One entry per recorded sample, in the same order across all four structures below.
    # ts_ns: sample time in Unix nanoseconds since the epoch.
    # rows: one row of float tag values per sample, in `tag_ids` order.
    # quality_rows: one row of 0/1 quality flags per sample, aligned column-wise with `rows`.
    ts_ns: list[int] = []
    rows: list[list[float]] = []
    quality_rows: list[list[int]] = []
    # Plant clock value (s) at the very first poll; this is the dataset's time origin.
    first_plant_time: float | None = None
    # Plant clock value (s) of the most recent recorded sample; drives the sampling period check.
    last_recorded: float | None = None
    # Wall-clock deadline (monotonic seconds). Monotonic time is used because it is immune to
    # system clock adjustments and only ever moves forward.
    deadline = time.monotonic() + timeout_s

    async with Client(endpoint) as client:
        # Namespace indices are assigned per server; the returned index is the numeric prefix used
        # in OPC UA node ids for this application's own nodes.
        idx = await client.get_namespace_index(NAMESPACE_URI)
        time_node, tag_nodes, tag_ids = await _discover_plant_nodes(client, idx)
        # One single read call is issued for the clock and every tag, so all values in a row come
        # from the same server-side instant.
        all_nodes = [time_node, *tag_nodes]

        while True:
            # `data_values` is parallel to `all_nodes`: index 0 is the clock, the rest are tags.
            data_values = await client.read_attributes(all_nodes, AttributeIds.Value)
            # Plant time in seconds. It starts near zero at simulation start and advances with the
            # simulation, unrelated to wall-clock time.
            plant_time = float(data_values[0].Value.Value)  # type: ignore[union-attr]
            if first_plant_time is None:
                first_plant_time = plant_time
            # Record when the plant clock has moved at least `sample_period_s` since the previous
            # recorded sample. The `1e-9` slack absorbs float rounding so an exactly-on-period
            # advance is not skipped.
            if last_recorded is None or plant_time - last_recorded >= sample_period_s - 1e-9:
                # Plant seconds since the first sample, converted to the dataset's epoch-relative
                # nanoseconds: elapsed_ns = elapsed_s * 1e9.
                elapsed = plant_time - first_plant_time
                ts_ns.append(start_ns + round(elapsed * 1e9))
                # Tag values for this sample, in `tag_ids` order (element 0 of the read is the
                # clock, hence the `[1:]`).
                rows.append([float(dv.Value.Value) for dv in data_values[1:]])  # type: ignore[union-attr]
                # A tag is good unless the server reports an explicit non-good status code.
                # `BAD_QUALITY` rows are still stored, so downstream code can skip or flag them.
                quality_rows.append(
                    [
                        GOOD_QUALITY
                        if dv.StatusCode is None or dv.StatusCode.is_good()
                        else BAD_QUALITY
                        for dv in data_values[1:]
                    ]
                )
                last_recorded = plant_time
            # Stop once the requested span of plant time has been observed.
            if plant_time - first_plant_time >= sim_duration_s:
                break
            # The simulation may be slower than real time, so guard against running forever.
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"plant time {plant_time - first_plant_time:.1f}s of {sim_duration_s:.1f}s "
                    f"after {timeout_s:.0f} wall seconds"
                )
            await asyncio.sleep(poll_s)

    # Provenance recorded with the dataset: which plant was sampled, and optionally which scenario
    # and RNG seed produced it, so the run can be reproduced.
    source: dict[str, Any] = {"kind": "opcua", "plant": plant_name}
    if scenario_name is not None:
        source["scenario"] = scenario_name
    if seed is not None:
        source["seed"] = seed

    # Every tag discovered on the server becomes a dataset column. Units and roles are unknown from
    # OPC UA alone, so they are left empty/`other` for the user to fill in later. The `address`
    # string is the canonical OPC UA node id ("ns=<namespace index>;s=<string id>").
    tags_document: dict[str, Any] = {
        "schema_version": "0.1.0",
        "tags": [
            {
                "id": tag_id,
                "name": tag_id,
                "unit": "",
                "type": "float",
                "role": "other",
                "source": {"driver": "opcua", "address": f"ns={idx};s={tag_id}"},
            }
            for tag_id in tag_ids
        ],
    }

    # The collected lists are turned into fixed-dtype arrays once, at the end: int64 nanoseconds,
    # float64 values and uint8 quality flags match what the dataset format expects on disk.
    return write_dataset(
        out_dir,
        np.asarray(ts_ns, dtype=np.int64),
        tag_ids,
        np.asarray(rows, dtype=np.float64),
        np.asarray(quality_rows, dtype=np.uint8),
        dataset_id=dataset_id,
        source=source,
        start_utc=start_utc,
        tags_document=tags_document,
        git_commit=git_commit,
    )


def _git_commit() -> str | None:
    """Return the short commit hash of the repository holding this file, or None.

    "Short" means git's abbreviated form, typically the first 7 hex characters of
    the full 40-character SHA-1. Used to record which revision of the code
    produced a result.

    Returns None when the hash cannot be determined, e.g. the working copy is not
    a git repository or the `git` executable is missing.
    """
    try:
        # Ask git itself for the current commit instead of parsing .git by hand.
        # `rev-parse` resolves a name to an object id; HEAD is "whatever commit is
        # checked out". `--short` truncates the id to its unique abbreviated form.
        # cwd pins the search to this file's folder so a parent repository higher up
        # the tree is not picked up by accident.
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=Path(__file__).parent,
                # capture_output keeps git's chatter off stdout; text=True decodes
                # bytes to str; check=True raises CalledProcessError on a non-zero
                # exit status (not a repo, no commits yet, git not installed).
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            # An empty string means git printed nothing useful. Normalise it to None
            # so callers have a single "unknown" value rather than two ("" and None).
            or None
        )
    except (subprocess.SubprocessError, OSError):
        # SubprocessError covers the non-zero exit raised by check=True;
        # OSError covers the case where the `git` binary cannot be executed.
        return None


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser that the collector module runs on.

    The collector is a long-running process: it connects to a live OPC UA server and copies
    every value change into a Parquet dataset, so all its inputs come from the command line
    rather than from a config file. Two clocks are in play and the option names make this
    explicit:

      * plant time - the timeline of the simulated plant, the clock the recorded data carries;
      * wall-clock time - the real time the collector process spends running.

    ``--duration`` and ``--sample-period`` are expressed in plant time, ``--timeout`` in
    wall-clock seconds. Durations accept suffixes (``1h``, ``30m``, ``10s``).

    Returns:
        argparse.ArgumentParser: the parser, with every option already registered. It has not
        parsed ``sys.argv`` yet; the caller decides what to pass to ``parse_args``.
    """
    parser = argparse.ArgumentParser(
        prog="python -m crosscut_opcua.collector",
        description="Record a running OPC UA plant server into a Parquet dataset.",
    )
    # Where the OPC UA server listens. The scheme is part of the string, hence the example.
    parser.add_argument("--endpoint", required=True, help="e.g. opc.tcp://127.0.0.1:4840")
    # Length of the recording, measured on the plant clock (not how long the process runs).
    parser.add_argument("--duration", required=True, help="plant time to record, e.g. 1h")
    # Interval between two consecutive samples, again on the plant clock. The default of one
    # second is the resolution at which the plant's tags are intended to be observed.
    parser.add_argument("--sample-period", default="1s", help="plant time between samples (1s)")
    # Directory that will hold the Parquet files; Path conversion turns the shell string into
    # a pathlib.Path so the rest of the code never has to deal with raw strings.
    parser.add_argument("--out", required=True, type=Path, help="output root directory")
    # Optional label for the produced dataset. When omitted the collector computes one itself
    # (by convention plant, scenario and start timestamp are folded into it).
    parser.add_argument("--dataset-id", default=None, help="dataset id (default: derived)")
    # Which known plant layout to talk to. Restricting the choices here means a typo fails at
    # parse time, with the list of valid names in the error message, instead of at connect time.
    parser.add_argument("--plant", required=True, choices=sorted(PLANTS), help="plant identifier")
    # Free-form scenario label, copied verbatim into the dataset metadata; it does not change
    # what is recorded, only how the recording is described later.
    parser.add_argument("--scenario", default=None, help="scenario name used for the metadata")
    # Random seed handed to the server, so a run can be reproduced. None lets the server pick.
    parser.add_argument("--seed", type=int, default=None, help="seed used by the server")
    # Plant-time instant assigned to the first sample. Fixing it makes two recordings of the
    # same plant comparable even if they are made on different days.
    parser.add_argument(
        "--start-utc", default=DEFAULT_START_UTC, help="timestamp of the first sample"
    )
    # Safety net: stop the process after this many seconds of real time. It must be a float so
    # that fractional-second limits are allowed, and its unit is seconds, not plant time.
    parser.add_argument(
        "--timeout", type=float, default=3600.0, help="wall-clock limit in seconds (3600)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Collect a dataset from a running server; returns the process exit code.

    A "dataset" here is a folder of files on disk describing one recording session:
    the rows collected from the server plus a document of metadata about it.

    `argv` is the command line arguments without the program name (None means "read
    `sys.argv`"). Returns 0 on success, 1 if the dataset folder already exists; on bad
    arguments it prints usage and exits (via `parser.error`, which never returns).
    """
    parser = _build_parser()
    # argv is the argument list "without the program name", e.g. ["--plant", "north"].
    args = parser.parse_args(argv)
    try:
        duration_s = parse_duration(args.duration)
        sample_period_s = parse_duration(args.sample_period)
    except ValueError as e:
        # BAD: an unrecognised duration string is a user mistake, so show usage.
        parser.error(str(e))

    if args.scenario is not None:
        # A scenario describes how the simulated plant behaves over time; building it
        # writes the scenario files into the plant folder and validates its name.
        try:
            build_scenario(args.plant, args.scenario, duration_s=duration_s)
        except ValueError as e:
            parser.error(str(e))

    # If the user gave no id, derive one from what identifies the recording; the
    # "opcua" fallback means "took live values instead of replaying a scenario".
    dataset_id = args.dataset_id or f"{args.plant}_{args.scenario or 'opcua'}_collected"
    # The dataset_id doubles as the folder name, so `args.out / dataset_id`
    # is the directory that collection creates (and refuses to overwrite).
    dataset_dir = args.out / dataset_id
    try:
        doc = asyncio.run(
            collect(
                args.endpoint,
                dataset_dir,
                sim_duration_s=duration_s,
                sample_period_s=sample_period_s,
                dataset_id=dataset_id,
                plant_name=args.plant,
                scenario_name=args.scenario,
                seed=args.seed,
                start_utc=args.start_utc,
                timeout_s=args.timeout,
                git_commit=_git_commit(),
            )
        )
    except FileExistsError as e:
        # We never merge into an existing dataset: half-old, half-new rows would be
        # unusable, so tell the user and report failure.
        print(str(e), file=sys.stderr)
        return 1
    # doc is the dataset's metadata document; row_count is how many samples were
    # written, i.e. duration_s / sample_period_s for a clean run.
    print(f"{dataset_dir} ({doc['row_count']} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
