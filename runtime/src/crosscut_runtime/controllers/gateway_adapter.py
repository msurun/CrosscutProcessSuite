"""Gateway ports for the controller host: proposals and MV availability via the file mailbox.

Only the mailbox client of crosscut-api is used (signed ``propose`` and read-only
``mv_availability`` commands); no gateway write code is imported. Controllers propose, the
gateway decides. Imported lazily so the runtime runs without crosscut-api for other jobs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from crosscut_runtime.controllers.protocol import Move

Availability = Callable[[list[str]], Mapping[str, Mapping[str, Any]]]
LOGGER = logging.getLogger(__name__)
CLIENT_ERRORS = (OSError, TimeoutError, ValueError, PermissionError, RuntimeError, KeyError)
NS_PER_S = 1_000_000_000
REASON_MAX_CHARS = 300


def proposer_name(controller_id: str) -> str:
    """The ``source`` of every proposal of a controller."""
    return f"controller:{controller_id}"


def proposal_args(move: Move, controller_id: str, now_ns: int) -> dict[str, Any]:
    """Arguments of the gateway ``propose`` command for one move."""
    return {
        "target_tag": move.target_tag,
        "value": move.value,
        "proposer": proposer_name(controller_id),
        "t_ns": now_ns,
        "reason": move.reason[:REASON_MAX_CHARS],
    }


def make_gateway_ports(
    root: Path, controller_id: str, now_ns: Callable[[], int]
) -> tuple[Callable[[list[str]], Mapping[str, Mapping[str, Any]]], Callable[[Move], None]]:
    """``(availability, propose)`` callables for the host; the client is built on first use."""
    from crosscut_api.auth.actor import ActorContext  # type: ignore[import-untyped]  # noqa: PLC0415
    from crosscut_api.gateway_client import (  # type: ignore[import-untyped]  # noqa: PLC0415
        FileGatewayClient,
    )

    client = FileGatewayClient(root)
    actor = ActorContext(
        actor=f"svc:{proposer_name(controller_id)}",
        roles=("service",),
        session="0" * 16,
        source_ip="127.0.0.1",
        stepup=False,
        permissions=frozenset({"gw.propose"}),
    )
    return _availability(client, actor), _propose(client, actor, controller_id, now_ns)


def _availability(client: Any, actor: Any) -> Availability:
    """Availability query; a gateway that cannot be asked answers nothing (every MV is down)."""

    def ask(targets: list[str]) -> Mapping[str, Mapping[str, Any]]:
        try:
            answer: Mapping[str, Mapping[str, Any]] = client.mv_availability(targets, actor=actor)
        except CLIENT_ERRORS as error:
            LOGGER.warning("mv_availability failed: %s", error)
            return {}
        return answer

    return ask


def _propose(
    client: Any, actor: Any, controller_id: str, now_ns: Callable[[], int]
) -> Callable[[Move], None]:
    """Propose callable; a refusal is logged (the gateway audit holds the reason)."""

    def propose(move: Move) -> None:
        args = proposal_args(move, controller_id, now_ns())
        try:
            decision = client.propose(args, actor=actor)
        except CLIENT_ERRORS as error:
            LOGGER.warning("proposal for %s failed: %s", move.target_tag, error)
            return
        if not decision.get("accepted", False):
            LOGGER.info("proposal for %s refused: %s", move.target_tag, decision.get("reason_code"))

    return propose
