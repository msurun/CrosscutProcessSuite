"""OPC UA server that exposes a simulated plant as a set of Double variables.

The server advances the plant in real time scaled by ``speed``, publishes every tag on each
tick and forwards client writes to the plant. A heartbeat counter written by the client acts
as a simulated DCS watchdog: when it stops changing, cascade (CAS) loops fall back to AUTO.

Run from the command line with ``python -m crosscut_opcua.server --help``.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from asyncua import Server, ua
from asyncua.common.node import Node
from asyncua.server.address_space import NodeData
from asyncua.ua.attribute_ids import AttributeIds
from crosscut_sim.core import AUTO, CAS, Plant, Scenario
from crosscut_sim.run import PLANTS
from crosscut_sim.scenarios import build_scenario

NAMESPACE_URI = "urn:crosscut:sim"
PLANT_OBJECT_NAME = "Plant"
HEARTBEAT_TAG = "sim.heartbeat"
HEARTBEAT_OK_TAG = "sim.heartbeat_ok"
TIME_TAG = "sim.time_s"
EXTRA_TAGS = (HEARTBEAT_TAG, HEARTBEAT_OK_TAG, TIME_TAG)


def _node_id(idx: int, identifier: str) -> ua.NodeId:
    """Return the string NodeId ``ns=<idx>;s=<identifier>`` used for every plant node."""
    return ua.NodeId.from_string(f"ns={idx};s={identifier}")


@dataclass(frozen=True)
class ServerConfig:
    """Network and timing settings of a :class:`PlantServer`.

    The scenario is replayed in real time, scaled by ``speed``: 1.0 means one simulated second
    per wall-clock second, 2.0 runs it at double rate. ``tick_s`` is the period of the
    simulation loop in wall-clock seconds. The client is expected to change the heartbeat
    variable at least once every ``heartbeat_timeout_s`` seconds; if it does not, CAS loops
    fall back to AUTO.

    Raises:
        ValueError: if speed, tick_s or heartbeat_timeout_s is not positive, because a zero or
            negative interval would make the loop spin forever or run backwards in time.
    """

    seed: int
    host: str = "127.0.0.1"
    port: int = 4840
    speed: float = 1.0
    tick_s: float = 0.1
    heartbeat_timeout_s: float = 10.0

    def __post_init__(self) -> None:
        if self.speed <= 0 or self.tick_s <= 0 or self.heartbeat_timeout_s <= 0:
            raise ValueError("speed, tick_s and heartbeat_timeout_s must be positive")


class PlantServer:
    """Serve a plant over OPC UA (anonymous, no security) while it runs in the background.

    Client writes are intercepted with an asyncua value setter, so they never travel through
    the subscription machinery. The server's own publishing is flagged with ``_publishing`` and
    is stored unchanged, which avoids any feedback loop.
    """

    def __init__(self, plant: Plant, scenario: Scenario, config: ServerConfig) -> None:
        """Create the OPC UA server that mirrors the plant and runs the scenario.

        Nothing is started here; see :class:`ServerConfig` for the meaning of the settings
        and the validation it performs.
        """
        self.plant = plant
        self._scenario = scenario
        self._config = config

        # The asyncua server object, created lazily in start() so that building
        # the instance is cheap and side-effect free.
        self._server: Server | None = None
        # OPC UA node objects keyed by node id, so lookups during a tick are O(1).
        self._nodes: dict[str, Node] = {}
        # The background asyncio task running the publish loop; None means the
        # server is not started.
        self._task: asyncio.Task[None] | None = None
        # Whether the publish loop is currently allowed to send value updates.
        self._publishing = False
        # Heartbeat counter next expected from the client. The server stores the
        # last client heartbeat; a change marks the client as alive.
        self._heartbeat_value = 0
        # Monotonic timestamp (seconds, from time.monotonic()) of the last time
        # the heartbeat value changed; used to detect a stalled client.
        self._last_heartbeat_change = time.monotonic()
        # Result of the last liveness check; True until a timeout is observed.
        self._heartbeat_ok = True

    @property
    def endpoint(self) -> str:
        """Return the OPC UA endpoint URL for this client's host and port."""
        return f"opc.tcp://{self._config.host}:{self._config.port}"

    async def __aenter__(self) -> PlantServer:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def start(self) -> None:
        """Create the address space, start the server and the background tick loop.

        The plant is reset to a known state first so the server exposes a
        deterministic snapshot.  Each plant tag becomes an OPC UA variable node;
        writable tags get an attribute value setter that routes external writes
        back into the plant.  Finally the tick loop is scheduled as a task.
        """
        self.plant.reset(self._config.seed, self._scenario)
        self._heartbeat_value = 0
        self._heartbeat_ok = True

        server, plant_obj, idx = await self._create_address_space()
        writable = await self._add_plant_variables(plant_obj, idx)
        writable.append(await self._add_support_variables(plant_obj, idx))

        await server.start()
        self._server = server
        self._last_heartbeat_change = time.monotonic()
        # A value setter is OPC UA's hook for incoming client writes to a node;
        # it translates a remote write into a plant update for that tag.
        for tag_id, node in writable:
            server.set_attribute_value_setter(node.nodeid, self._make_setter(tag_id))

        # Publish an initial consistent snapshot before the tick loop takes over.
        await self._publish()
        # The tick loop runs concurrently so start() can return while publishing
        # continues in the background.
        self._task = asyncio.create_task(self._run())

    async def _create_address_space(self) -> tuple[Server, Node, int]:
        """Create the (not yet started) server and the object node that groups all tags.

        Returns the server, the plant object node and the namespace index ``idx``: the numeric
        index every NodeId built from this namespace must carry so clients can resolve it.
        """
        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        idx = await server.register_namespace(NAMESPACE_URI)
        # A variable cannot live at the root of the address space, so the tags
        # are grouped under a single "plant" object node.
        plant_obj = await server.nodes.objects.add_object(
            _node_id(idx, PLANT_OBJECT_NAME), PLANT_OBJECT_NAME
        )
        return server, plant_obj, idx

    async def _add_plant_variables(self, plant_obj: Node, idx: int) -> list[tuple[str, Node]]:
        """Add one Double variable per plant tag; return the writable ones with their ids."""
        writable: list[tuple[str, Node]] = []
        for spec in self.plant.tags:
            value, _ = self.plant.read(spec.id)
            # Every tag is exposed as an OPC UA Double, hence the float(...) cast
            # of the raw plant value.
            node = await plant_obj.add_variable(
                _node_id(idx, spec.id), spec.id, float(value), varianttype=ua.VariantType.Double
            )
            self._nodes[spec.id] = node
            if spec.writable:
                await node.set_writable()
                writable.append((spec.id, node))
        return writable

    async def _add_support_variables(self, plant_obj: Node, idx: int) -> tuple[str, Node]:
        """Add the heartbeat, heartbeat status and plant time nodes.

        Returns the heartbeat id and node: the only one of the three a client may write.
        """
        # Heartbeat variable the client writes: a change proves the client is alive.
        # The server stores the received value and compares it on each write.
        heartbeat = await plant_obj.add_variable(
            _node_id(idx, HEARTBEAT_TAG), HEARTBEAT_TAG, 0, varianttype=ua.VariantType.Int64
        )
        await heartbeat.set_writable()
        self._nodes[HEARTBEAT_TAG] = heartbeat
        # Health flag the server updates. False means the heartbeat has timed out.
        self._nodes[HEARTBEAT_OK_TAG] = await plant_obj.add_variable(
            _node_id(idx, HEARTBEAT_OK_TAG),
            HEARTBEAT_OK_TAG,
            True,
            varianttype=ua.VariantType.Boolean,
        )
        # Plant model time, exposed as a Double so clients can correlate with the plant.
        self._nodes[TIME_TAG] = await plant_obj.add_variable(
            _node_id(idx, TIME_TAG),
            TIME_TAG,
            float(self.plant.time_s),
            varianttype=ua.VariantType.Double,
        )
        return HEARTBEAT_TAG, heartbeat

    async def stop(self) -> None:
        """Stop the tick loop and the server; releases the port.

        Safe to call when already stopped: both handles are None-checked and cleared,
        so a second call is a no-op (idempotent shutdown).
        """
        # Cancel the background tick loop task and wait for it to actually finish.
        # Awaiting a cancelled task re-raises CancelledError inside us, so we swallow
        # that one exception: it is the expected signal that the loop unwound cleanly.
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Stop the OPC UA server (unbinds the listening socket, freeing the port) and
        # drop the reference so nothing can call methods on a stopped server later.
        if self._server is not None:
            await self._server.stop()
            self._server = None
        # Forget every registered node: the mapping is invalid once the server has stopped.
        self._nodes = {}

    # ----- simulation loop -------------------------------------------------------------------

    async def _run(self) -> None:
        """Drive the simulation loop at wall-clock speed until cancelled.

        Each iteration advances the plant by ``steps`` simulation steps so the
        simulated time elapsed per iteration matches ``self._tick_s`` real
        seconds at the configured speed factor.

        Returns:
            Never returns; runs until the task is cancelled.

        Raises:
            asyncio.CancelledError: Propagated when the surrounding task is cancelled.
        """
        # How many simulation steps to run per iteration. The plant advances by
        # self._scenario.dt_s seconds (simulation time) per step, so the number
        # of steps that correspond to one wall-clock iteration is:
        # steps = speed * tick_s / dt_s
        # speed is the playback multiplier (1.0 = real time), tick_s is the
        # wall-clock period of one iteration (seconds), dt_s is the simulation
        # step size (seconds). max(1, ...) guarantees at least one step even at
        # very low speed factors.
        steps = max(1, round(self._config.speed * self._config.tick_s / self._scenario.dt_s))
        while True:
            # Monotonic clock, not wall time: it cannot jump backwards on NTP or
            # DST adjustments, so the elapsed measurement below stays non-negative.
            started = time.monotonic()
            for _ in range(steps):
                self.plant.step()
            self._update_watchdog(time.monotonic())
            await self._publish()
            elapsed = time.monotonic() - started
            # Sleep only for the remainder of the tick period. max(0.0, ...) keeps
            # the argument non-negative when stepping and publishing took longer
            # than tick_s, in which case we run again immediately instead of
            # raising.
            await asyncio.sleep(max(0.0, self._config.tick_s - elapsed))

    async def _publish(self) -> None:
        """Copy every plant tag, the plant time and the heartbeat status to the address space.

        The address space (OPC UA nodes) is the read-only mirror a supervisor sees; the plant
        simulation owns the truth. Each tag is written one by one because that is the only
        granularity the underlying client exposes.
        """
        # Publish the live plant state first: the supervisor must never see a heartbeat that is
        # newer than the values it is checking.
        for spec in self.plant.tags:
            # read() returns (value, quality); is_simulated/quality is not part of the mirror,
            # so it is discarded. The cast to float normalises ints/bools to one node data type.
            value, _ = self.plant.read(spec.id)
            await self._write(spec.id, float(value))
        # TIME_TAG holds the plant clock in seconds since the simulation started (float64, UTC).
        await self._write(TIME_TAG, float(self.plant.time_s))
        # Sent last, as a liveness flag: if the loop stalls before this await completes, the
        # supervisor sees stale plant time and can trip on the missing beat.
        await self._write(HEARTBEAT_OK_TAG, self._heartbeat_ok)

    async def _write(self, tag_id: str, value: float | bool) -> None:
        """Write a value on behalf of the server (not a client write).

        OPC UA carries every value in a self-describing container called a
        ``Variant``, which pairs the raw value with an explicit data type. The
        server must therefore decide the wire type *before* sending, because
        the receiving client trusts the declared type rather than guessing it
        from the Python object.

        Args:
            tag_id: Name of the OPC UA node to write to.
            value: New value; a bool for boolean tags, otherwise a number.

        Returns:
            None. Failures from the node write propagate to the caller.
        """
        # Booleans are unambiguous, so the wire type follows directly from the
        # Python type of ``value``.
        if isinstance(value, bool):
            variant = ua.Variant(value, ua.VariantType.Boolean)
        else:
            # Every non-boolean tag is numeric, but the heartbeat carries a
            # monotonically increasing counter (an integer), so it must be sent
            # as Int64 to avoid losing precision on the wire. All other numeric
            # tags are measurements and use Double, the OPC UA default for
            # floating-point values.
            variant_type = (
                ua.VariantType.Int64 if tag_id == HEARTBEAT_TAG else ua.VariantType.Double
            )
            variant = ua.Variant(value, variant_type)

        # ``_publishing`` marks this task as the writer and is read by the
        # subscription/datachange callback. Without it, the server's own write
        # would look like a value change coming from a client and could be
        # echoed back as a client update (an infinite write loop). The flag is
        # reset in ``finally`` so it is cleared even if the node write raises,
        # keeping the invariant "flag is True only while a server write runs".
        self._publishing = True
        try:
            # ``DataValue`` wraps the Variant with source/timestamp metadata; this
            # call performs the actual OPC UA write on the node.
            await self._nodes[tag_id].write_value(ua.DataValue(variant))
        finally:
            self._publishing = False

    # ----- heartbeat watchdog ----------------------------------------------------------------

    def _heartbeat_alive(self, now: float) -> bool:
        return now - self._last_heartbeat_change <= self._config.heartbeat_timeout_s

    def _update_watchdog(self, now: float) -> None:
        alive = self._heartbeat_alive(now)
        if self._heartbeat_ok and not alive:
            self._return_cas_loops_to_auto()
        self._heartbeat_ok = alive

    def _return_cas_loops_to_auto(self) -> None:
        """Put every loop tag currently in CAS back to AUTO.

        A loop tag holds two things: the operator-facing setpoint (SP) and a
        mode flag telling the controller who owns the loop. In CAS ("cascade")
        the loop is driven remotely, by us, instead of by its local logic; the
        DCS takes the loops back when our heartbeat is gone: CAS loops fall
        to AUTO and keep their local SP.

        This method is the graceful handover of that ownership, called while we
        can still write. Tags we are not allowed to write, or whose value
        cannot be parsed, are skipped on purpose: a loop we cannot release is
        better left alone than half-switched.

        Returns:
            None. Failure to release a single loop is swallowed by design.
        """
        # A tag's role says what kind of signal it is; only MODE tags carry the
        # CAS/AUTO ownership flag, so every other role is irrelevant here.
        for spec in self.plant.tags:
            if spec.role != "MODE":
                continue
            # First value of the read tuple is the current mode; a loop already in
            # AUTO is nobody's business and we leave it untouched.
            if self.plant.read(spec.id)[0] != CAS:
                continue
            # Modes are exchanged as numbers on the wire, so AUTO (an int) is cast
            # to float to match the numeric type the write expects. An id the DCS
            # refuses (PermissionError), a non-numeric current value (ValueError) or
            # an unknown id (KeyError) is a loop we cannot release; skipping it
            # keeps the remaining loops released.
            try:
                self.plant.write(spec.id, float(AUTO))
            except (PermissionError, ValueError, KeyError):
                pass

    # ----- client writes ---------------------------------------------------------------------

    def _make_setter(self, tag_id: str) -> Callable[[NodeData, AttributeIds, ua.DataValue], None]:
        """Return the callback the OPC UA stack invokes when a client writes ``tag_id``."""

        def setter(node: NodeData, attr: AttributeIds, value: ua.DataValue) -> None:
            """Store the write directly while publishing, otherwise route it via the plant."""
            if self._publishing:
                node.attributes[attr].value = value
            elif tag_id == HEARTBEAT_TAG:
                self._on_heartbeat(int(value.Value.Value))  # type: ignore[union-attr]
                node.attributes[attr].value = value
            else:
                self._apply_client_write(node, attr, tag_id, value)

        return setter

    def _apply_client_write(
        self, node: NodeData, attr: AttributeIds, tag_id: str, value: ua.DataValue
    ) -> None:
        """Forward a client write to the plant, then refresh the node from the plant.

        The plant may clamp or reject the requested value, so the node always reflects what
        the plant holds after the write attempt (``plant.read`` returns ``(value, quality)``;
        element 0 is the value in engineering units).
        """
        self._on_client_write(tag_id, float(value.Value.Value))  # type: ignore[union-attr]
        stored = float(self.plant.read(tag_id)[0])
        node.attributes[attr].value = ua.DataValue(ua.Variant(stored, ua.VariantType.Double))

    def _on_heartbeat(self, value: int) -> None:
        if value != self._heartbeat_value:
            self._heartbeat_value = value
            self._last_heartbeat_change = time.monotonic()

    def _on_client_write(self, tag_id: str, value: float) -> None:
        """Forward a client write to the plant; a refused write leaves the plant unchanged.

        Called when an operator panel (the "client") asks to change a tag. In the
        process-control domain a write is advisory: the plant, not this method,
        decides whether it is legal, so a refusal (a raised exception) is normal
        and results in no change rather than an error surfaced to the caller.

        Args:
            tag_id: name of the tag to change, for example "TIC101.SP".
            value: requested value in the tag's own engineering units.
        """
        spec = self.plant.tags[tag_id]
        # A MODE write of CAS (cascade) hands control of the loop from the DCS
        # to the client. The DCS may only keep the loop stable if a fresh
        # heartbeat proves that we are alive, so a stale heartbeat must not
        # release that interlock.
        if spec.role == "MODE" and value == CAS and not self._heartbeat_alive(time.monotonic()):
            return  # the DCS holds the loop while the heartbeat is lost
        try:
            self.plant.write(tag_id, value)
        except (PermissionError, ValueError, KeyError):
            pass


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for ``python -m crosscut_opcua.server``.

    Returns:
        argparse.ArgumentParser: a fully configured parser whose argument groups
        are added by ``_add_plant_arguments`` and ``_add_timing_arguments``.
    """
    # argparse is the standard-library command-line parser. `prog` sets the name shown in
    # usage/error messages, so this spells out the exact way the user is expected to launch
    # the module (`python -m crosscut_opcua.server`) instead of argparse guessing from argv[0].
    parser = argparse.ArgumentParser(
        prog="python -m crosscut_opcua.server",
        description="Serve a simulated plant over OPC UA until interrupted (Ctrl+C).",
    )
    # These helpers keep the argument definitions grouped by concern: plant selection
    # and timing control. Splitting them makes the parser easier to read and test.
    _add_plant_arguments(parser)
    _add_timing_arguments(parser)
    return parser


def _add_plant_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the arguments that choose what to simulate and where to listen.

    Registers five command-line options on ``parser``: the plant to simulate,
    the scenario to run on it, the random seed, and the address and port of
    the server socket that exposes the simulated plant.

    Args:
        parser: The argument parser to populate; it is mutated in place and
            nothing is returned.

    Raises:
        ValueError: Propagated from ``argparse`` if ``--plant`` is missing or
            holds an identifier that is not a key of ``PLANTS``.
    """
    # PLANTS is the registry of the plant models the simulator can run; ``choices`` makes argparse
    # reject an unknown identifier at parse time instead of failing later when the model is built,
    # and sorted() keeps the help text and error message in a stable, alphabetical order.
    parser.add_argument("--plant", required=True, choices=sorted(PLANTS), help="plant identifier")
    # A scenario is a named operating schedule for the plant (for example "nominal", the fault-free
    # one, or a failure case); it is a plain string so new scenarios need no change here.
    parser.add_argument("--scenario", default="nominal", help="scenario name (default: nominal)")
    # Fixing the seed makes every random draw reproducible, so two runs with the same seed produce
    # byte-identical telemetry and a reported bug can be replayed exactly.
    parser.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    # The simulated plant is reachable as an OPC UA server. 127.0.0.1 binds to the loopback
    # interface only, that is, the machine running the simulator and nobody else.
    parser.add_argument("--host", default="127.0.0.1", help="listen address (default: 127.0.0.1)")
    # 4840 is the port reserved by the OPC UA specification for binary protocol servers; a client
    # can therefore connect without being told a non-standard port.
    parser.add_argument("--port", type=int, default=4840, help="listen port (default: 4840)")


def _add_timing_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the arguments that control simulation and publish timing.

    The three rates are independent: `--speed` sets how fast the simulated plant advances,
    `--tick` sets how often the runtime publishes, and `--heartbeat-timeout` sets how long the
    runtime tolerates silence from a peer before it stops waiting for it. Each becomes a
    `float` on the parsed namespace.

    Args:
        parser: The argument parser to register the options on.

    Returns:
        None. The parser is modified in place.
    """

    # Ratio of simulated ("plant") time to real ("wall-clock") time: 2.0 runs the simulation
    # twice as fast as reality. Unit: plant seconds per wall-clock second.
    parser.add_argument(
        "--speed", type=float, default=1.0, help="plant time per wall-clock second (default: 1)"
    )

    # How often the runtime publishes its state. Shorter ticks give finer updates but more
    # messages and CPU. Unit: seconds, wall-clock (publishing is not sped up by --speed).
    parser.add_argument(
        "--tick", type=float, default=0.1, help="publish period in seconds (default: 0.1)"
    )

    # A CAS ("compare-and-swap") loop is a retry loop: read the shared value, try to swap it
    # with our new one, and retry if another process won the race. Peers announce they are
    # still alive with heartbeats; after this many seconds without one, the loop gives up
    # waiting and falls back instead of retrying forever. Unit: seconds.
    parser.add_argument(
        "--heartbeat-timeout",
        type=float,
        default=10.0,
        help="seconds without heartbeat changes before CAS loops fall back (default: 10)",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the OPC UA server until interrupted; returns the process exit code.

    OPC UA is an industrial machine-to-machine protocol: clients connect to this
    process to read and write variables exposed as an address space. `argv`
    defaults to None, which makes argparse read the real command line; tests
    pass a list of strings to parse instead.
    """
    # Build the command-line parser first: it is needed both to parse the
    # arguments and, later, to report a readable usage message.
    parser = _build_parser()

    # argparse turns the strings into an object with one attribute per flag,
    # e.g. args.endpoint holds the address the server listens on.
    args = parser.parse_args(argv)

    # The address space and the transport are configured from `args`, so the
    # server object can only be built once the arguments are known.
    server = _build_server(parser, args)

    # Blocking call: it serves requests until the user stops the process
    # (Ctrl+C or SIGTERM), then returns normally.
    _run_server_until_interrupted(server, args)

    # A clean shutdown is a success; an unrecoverable startup failure would
    # have raised earlier instead of reaching this point.
    return 0


def _build_server(parser: argparse.ArgumentParser, args: argparse.Namespace) -> PlantServer:
    """Build the server described by the parsed command line arguments.

    Raises SystemExit (through parser.error) when the requested scenario is invalid.
    """
    # A scenario is a fixed timeline of setpoints that the plant must follow during a
    # simulation run. We always build a 24-hour one (duration_s is in seconds), so the
    # simulation clock has a finite, reproducible end. build_scenario raises ValueError
    # for an unknown plant/scenario name or for a scenario shorter than the duration.
    try:
        scenario = build_scenario(args.plant, args.scenario, duration_s=24 * 3600.0)
    except ValueError as e:
        # parser.error prints the message to stderr and raises SystemExit, which is the
        # argparse convention for "the command line cannot be used as given".
        parser.error(str(e))

    # PLANTS maps a plant name to its class; calling it instantiates the plant model to
    # simulate, which we pair with the scenario and the network/timing options.
    # Units: speed is a simulation time multiplier (1.0 = real time), tick_s is the
    # interval between simulation steps in seconds, heartbeat_timeout_s is how long a
    # client may stay silent before the server drops it, in seconds.
    config = ServerConfig(
        seed=args.seed,
        host=args.host,
        port=args.port,
        speed=args.speed,
        tick_s=args.tick,
        heartbeat_timeout_s=args.heartbeat_timeout,
    )
    return PlantServer(PLANTS[args.plant](), scenario, config)


def _run_server_until_interrupted(server: PlantServer, args: argparse.Namespace) -> None:
    """Serve requests until the user presses Ctrl+C, which ends the process quietly.

    `server` is a PlantServer (an async context manager): entering it starts accepting
    connections, leaving it shuts them down cleanly. `args` holds the parsed CLI options.

    The event loop is created here and lives only for the duration of this call.
    """

    async def serve_forever() -> None:
        """Run the server until the process is interrupted."""
        # Entering the async context manager binds the listening socket and starts the
        # background tasks that handle incoming requests. It stays open for the whole
        # `async with` block and is released on exit, even if this coroutine is cancelled.
        async with server:
            print(f"serving {args.plant} at {server.endpoint} (Ctrl+C to stop)", flush=True)

            # An Event starts unset, so `wait()` blocks forever: this coroutine never
            # returns on its own and the loop keeps serving in the background. It only
            # ends when the process receives an interrupt (KeyboardInterrupt / SIGINT),
            # which aborts the await and unwinds the `async with` block above.
            await asyncio.Event().wait()

    try:
        asyncio.run(serve_forever())
    except KeyboardInterrupt:
        # Ctrl+C is the documented way to stop the server, so it is not an error.
        pass


if __name__ == "__main__":
    raise SystemExit(main())
