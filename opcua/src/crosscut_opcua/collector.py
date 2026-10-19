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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from asyncua import Client, ua
from asyncua.common.node import Node
from asyncua.ua.attribute_ids import AttributeIds
from crosscut_sim.dataset import DEFAULT_START_UTC, DatasetInfo, Samples, write_dataset
from crosscut_sim.run import PLANTS, parse_duration
from crosscut_sim.scenarios import build_scenario

from crosscut_opcua.server import EXTRA_TAGS, NAMESPACE_URI, PLANT_OBJECT_NAME, TIME_TAG

GOOD_QUALITY = 0
BAD_QUALITY = 2


def _utc_to_ns(text: str) -> int:
    """Convert ``YYYY-MM-DDTHH:MM:SSZ`` to Unix nanoseconds."""
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


@dataclass(frozen=True)
class CollectorConfig:
    """What to record and how, independent of the server address.

    Parameters
    ----------
    sim_duration_s
        Length of the recording in plant seconds. Polling stops once the plant clock has advanced
        this far past the first sample.
    sample_period_s
        Minimum plant-time step (s) between two recorded samples; sets the dataset's sampling rate.
    dataset_id, plant_name, scenario_name, seed, start_utc, git_commit
        Provenance written into the dataset (``seed`` and ``scenario_name`` are optional).
    timeout_s
        Wall-clock budget (s) for the whole collection, independent of ``sim_duration_s``.
    poll_s
        Idle sleep (s) between two reads of the OPC UA server; 0 means "poll as fast as possible".

    Raises
    ------
    ValueError
        If ``sim_duration_s``, ``sample_period_s`` or ``poll_s`` is not usable.
    """

    sim_duration_s: float
    sample_period_s: float
    dataset_id: str
    plant_name: str
    scenario_name: str | None = None
    seed: int | None = None
    start_utc: str = DEFAULT_START_UTC
    timeout_s: float = 3600.0
    poll_s: float = 0.01
    git_commit: str | None = None

    def __post_init__(self) -> None:
        # Reject impossible sampling settings before touching the network: a negative
        # poll_s would busy-loop, and zero or negative durations would never make progress.
        # Error message is intentionally minimal because one check covers all the cases.
        if self.sim_duration_s <= 0 or self.sample_period_s <= 0 or self.poll_s < 0:
            raise ValueError("sim_duration_s and sample_period_s must be positive")


@dataclass
class _Recording:
    """Samples gathered so far; the three lists have one entry per recorded sample, same order.

    ``ts_ns`` holds Unix nanoseconds, ``rows`` the float tag values in ``tag_ids`` order and
    ``quality_rows`` the quality codes (0 good, 2 bad) aligned with ``rows``.
    """

    start_ns: int
    sample_period_s: float
    ts_ns: list[int] = field(default_factory=list)
    rows: list[list[float]] = field(default_factory=list)
    quality_rows: list[list[int]] = field(default_factory=list)
    # Plant clock (s) at the very first poll: the dataset's time origin.
    first_plant_time: float | None = None
    # Plant clock (s) of the most recent recorded sample; drives the sampling period check.
    last_recorded: float | None = None

    def elapsed_s(self, plant_time: float) -> float:
        """Plant seconds since the first poll (the first poll defines the origin)."""
        if self.first_plant_time is None:
            self.first_plant_time = plant_time
        return plant_time - self.first_plant_time

    def offer(self, plant_time: float, tag_values: Sequence[ua.DataValue]) -> None:
        """Record the tag values when the plant clock advanced by one sample period.

        The ``1e-9`` slack absorbs float rounding so an exactly-on-period advance is not skipped.
        """
        elapsed = self.elapsed_s(plant_time)
        if (
            self.last_recorded is not None
            and plant_time - self.last_recorded < self.sample_period_s - 1e-9
        ):
            return
        # Epoch-relative nanoseconds: elapsed_ns = round(elapsed_s * 1e9).
        self.ts_ns.append(self.start_ns + round(elapsed * 1e9))
        self.rows.append([float(dv.Value.Value) for dv in tag_values])  # type: ignore[union-attr]
        # A tag is good unless the server reports an explicit non-good status code.
        # `BAD_QUALITY` rows are still stored, so downstream code can skip or flag them.
        self.quality_rows.append([_quality_flag(dv) for dv in tag_values])
        self.last_recorded = plant_time


def _quality_flag(data_value: ua.DataValue) -> int:
    """Return GOOD_QUALITY unless the server reported an explicit non-good status code."""
    status = data_value.StatusCode
    return GOOD_QUALITY if status is None or status.is_good() else BAD_QUALITY


async def _poll_until_done(
    client: Client, all_nodes: list[Node], config: CollectorConfig, recording: _Recording
) -> None:
    """Read the clock and every tag repeatedly until ``sim_duration_s`` of plant time passed.

    One single read call is issued for the clock and every tag, so all values in a row come
    from the same server-side instant. ``data_values[0]`` is the clock, the rest are tags.
    Raises TimeoutError when the wall-clock budget ``timeout_s`` runs out first (the simulation
    may be slower than real time). The deadline uses monotonic time, which is immune to system
    clock adjustments.
    """
    deadline = time.monotonic() + config.timeout_s
    while True:
        data_values = await client.read_attributes(all_nodes, AttributeIds.Value)
        # Plant time in seconds; unrelated to wall-clock time.
        plant_time = float(data_values[0].Value.Value)  # type: ignore[union-attr]
        recording.offer(plant_time, data_values[1:])
        elapsed = recording.elapsed_s(plant_time)
        if elapsed >= config.sim_duration_s:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"plant time {elapsed:.1f}s of {config.sim_duration_s:.1f}s "
                f"after {config.timeout_s:.0f} wall seconds"
            )
        await asyncio.sleep(config.poll_s)


def _build_source(config: CollectorConfig) -> dict[str, Any]:
    """Provenance of the dataset: the plant and, when known, the scenario and RNG seed."""
    source: dict[str, Any] = {"kind": "opcua", "plant": config.plant_name}
    if config.scenario_name is not None:
        source["scenario"] = config.scenario_name
    if config.seed is not None:
        source["seed"] = config.seed
    return source


def _build_tags_document(tag_ids: list[str], idx: int) -> dict[str, Any]:
    """Describe every discovered tag as a dataset column.

    Units and roles are unknown from OPC UA alone, so they are left empty/`other` for the user
    to fill in later. The `address` is the canonical OPC UA node id ("ns=<namespace index>;s=<id>").
    """
    return {
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


async def collect(endpoint: str, out_dir: str | Path, config: CollectorConfig) -> dict[str, Any]:
    """Record plant samples from an OPC UA server into ``out_dir`` and return the dataset document.

    OPC UA is an industrial protocol: the client connects to an ``endpoint`` URL and reads
    *nodes*, each addressed by a node id (here namespace index plus the tag id as string).
    Here one node carries the plant clock (simulated
    seconds, not wall-clock time) and the remaining nodes carry the tag values recorded in the
    dataset.

    Sampling rule: samples are taken whenever the plant clock has advanced by
    ``config.sample_period_s`` since the last sample; the first poll is always recorded. Sample
    timestamps are ``config.start_utc`` plus the plant time elapsed since the first sample, so the
    dataset is reproducible regardless of how fast the simulation actually runs.

    Returns
    -------
    dict[str, Any]
        The dataset document written by :func:`write_dataset` (metadata plus file references).

    Raises
    ------
    TimeoutError
        If ``sim_duration_s`` of plant time has not elapsed within ``timeout_s`` wall seconds.
    """
    recording = _Recording(_utc_to_ns(config.start_utc), config.sample_period_s)
    async with Client(endpoint) as client:
        idx = await client.get_namespace_index(NAMESPACE_URI)
        time_node, tag_nodes, tag_ids = await _discover_plant_nodes(client, idx)
        await _poll_until_done(client, [time_node, *tag_nodes], config, recording)

    # The collected lists are turned into fixed-dtype arrays once, at the end: int64
    # nanoseconds, float64 values and uint8 quality flags match what the dataset format
    # expects on disk.
    samples = Samples(
        np.asarray(recording.ts_ns, dtype=np.int64),
        tag_ids,
        np.asarray(recording.rows, dtype=np.float64),
        np.asarray(recording.quality_rows, dtype=np.uint8),
    )
    info = DatasetInfo(
        dataset_id=config.dataset_id,
        source=_build_source(config),
        start_utc=config.start_utc,
        tags_document=_build_tags_document(tag_ids, idx),
        git_commit=config.git_commit,
    )
    return write_dataset(out_dir, samples, info)


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
                # capture_output keeps git's chatter off stdout; text=True decodes bytes to str;
                # check=True raises CalledProcessError on a non-zero exit status (not a repo, no
                # commits yet).
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            # An empty string means git printed nothing useful. Normalise it to None so
            # callers have a single "unknown" value rather than two ("" and None).
            or None
        )
    except (subprocess.SubprocessError, OSError):
        # SubprocessError covers the non-zero exit raised by check=True;
        # OSError covers the case where the `git` binary cannot be executed.
        return None


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser that the collector module runs on.

    The collector is a long-running process: it connects to a live OPC UA server, polls the
    plant tags and writes the samples into a Parquet dataset, so all its inputs come from the
    command line rather than from a config file. Two clocks are in play and the option
    names make this explicit:

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
    # Interval between two consecutive samples, again on the plant clock (default 1 s).
    parser.add_argument("--sample-period", default="1s", help="plant time between samples (1s)")
    # Directory that will hold the Parquet files; Path conversion turns the shell string into
    # a pathlib.Path so the rest of the code never has to deal with raw strings.
    parser.add_argument("--out", required=True, type=Path, help="output root directory")
    # Optional label for the produced dataset. When omitted the collector derives it from the
    # plant and scenario names (``<plant>_<scenario or opcua>_collected``).
    parser.add_argument("--dataset-id", default=None, help="dataset id (default: derived)")
    # Which known plant layout to talk to. Restricting the choices here means a typo fails at
    # parse time, with the list of valid names in the error message, instead of at connect time.
    parser.add_argument("--plant", required=True, choices=sorted(PLANTS), help="plant identifier")
    # Free-form scenario label, copied verbatim into the dataset metadata; it does not change
    # what is recorded, only how the recording is described later.
    parser.add_argument("--scenario", default=None, help="scenario name used for the metadata")
    # Seed the server was started with; it is only written into the dataset metadata (the
    # collector does not talk to the server's random generators).
    parser.add_argument("--seed", type=int, default=None, help="seed used by the server")
    # UTC instant assigned to the first sample (the plant clock only supplies the elapsed time).
    # Fixing it makes two recordings comparable even if they are made on different days.
    parser.add_argument(
        "--start-utc", default=DEFAULT_START_UTC, help="timestamp of the first sample"
    )
    # Safety net: stop the process after this many seconds of real time. It must be a float so
    # that fractional-second limits are allowed, and its unit is seconds, not plant time.
    parser.add_argument(
        "--timeout", type=float, default=3600.0, help="wall-clock limit in seconds (3600)"
    )
    return parser


def _parse_durations(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> tuple[float, float]:
    """Return ``(duration_s, sample_period_s)`` from the command line; exit on a bad value."""
    try:
        return parse_duration(args.duration), parse_duration(args.sample_period)
    except ValueError as error:
        parser.error(str(error))


def _validate_scenario(
    parser: argparse.ArgumentParser, args: argparse.Namespace, duration_s: float
) -> None:
    """Exit with a usage error when ``--scenario`` is given but cannot be built.

    A scenario describes how the simulated plant behaves over time. Only the name is checked
    here, by building the scenario object (nothing is written); the server was started with
    the scenario separately.
    """
    if args.scenario is None:
        return
    try:
        build_scenario(args.plant, args.scenario, duration_s=duration_s)
    except ValueError as error:
        parser.error(str(error))


def _build_config(
    args: argparse.Namespace, duration_s: float, sample_period_s: float
) -> CollectorConfig:
    """Translate the parsed command line into a :class:`CollectorConfig`."""
    # If the user gave no id, derive one from the plant and scenario names; without
    # --scenario the word 'opcua' stands in. The dataset_id doubles as the folder name
    # that collection creates (and refuses to overwrite).
    dataset_id = args.dataset_id or f"{args.plant}_{args.scenario or 'opcua'}_collected"
    return CollectorConfig(
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


def main(argv: Sequence[str] | None = None) -> int:
    """Collect a dataset from a running server; returns the process exit code.

    A "dataset" here is a folder of files on disk describing one recording session:
    the rows collected from the server plus a document of metadata about it.

    `argv` is the command line arguments without the program name (None means "read
    `sys.argv`"). Returns 0 on success, 1 if the dataset folder already exists; on bad
    arguments it prints usage and exits (via `parser.error`, which never returns).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    duration_s, sample_period_s = _parse_durations(parser, args)
    _validate_scenario(parser, args, duration_s)

    config = _build_config(args, duration_s, sample_period_s)
    dataset_dir = args.out / config.dataset_id
    try:
        doc = asyncio.run(collect(args.endpoint, dataset_dir, config))
    except FileExistsError as error:
        # We never merge into an existing dataset: half-old, half-new rows would be
        # unusable, so tell the user and report failure.
        print(str(error), file=sys.stderr)
        return 1
    print(f"{dataset_dir} ({doc['row_count']} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
