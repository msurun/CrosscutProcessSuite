"""Send one signed `propose` command to the gateway inbox, as a runtime service would.

Usage: python gateway_propose.py --root <data root> --tag T --value V [--actor svc:runtime]
       [--roles service] [--reason text]

Signs with the gateway key (like the API does), drops the envelope in the inbox and waits for the
answer. Prints one JSON line: {"answered": true, "decision": {...}} or, when the gateway refused
the command at its gate (it writes no answer then), {"answered": false, "reason": "..."}.
"""

from __future__ import annotations

import argparse
import json
import secrets
import time
from pathlib import Path

from crosscut_api.auth.actor import ActorContext
from crosscut_api.gateway_client import FileGatewayClient

ANSWER_WAIT_S = 8.0


def _actor(name: str, roles: str) -> ActorContext:
    """Build the signing identity: a fresh session id, no step-up, no local permission check."""
    return ActorContext(
        actor=name,
        roles=tuple(part for part in roles.split(",") if part),
        session=secrets.token_hex(8),
        source_ip="127.0.0.1",
        stepup=False,
        permissions=None,
    )


def _rejected_reason(root: Path, cmd_id: str) -> str:
    """Return the reason the gateway filed for a refused command, or an empty string."""
    path = root / "_gateway" / "rejected" / f"{cmd_id}.json.reason.txt"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def propose(args: argparse.Namespace) -> dict[str, object]:
    """Send the proposal and return the JSON-able outcome."""
    client = FileGatewayClient(args.root, timeout_s=ANSWER_WAIT_S)
    body = {
        "target_tag": args.tag,
        "value": args.value,
        "proposer": args.actor,
        "t_ns": time.time_ns(),
        "reason": args.reason,
    }
    cmd_id = client._write_command("propose", body, _actor(args.actor, args.roles))
    try:
        answer = client._await_answer(cmd_id)
    except TimeoutError:
        return {"answered": False, "reason": _rejected_reason(args.root, cmd_id)}
    return {"answered": True, "ok": answer.get("ok"), "decision": answer.get("result"),
            "error": answer.get("error")}


def main() -> int:
    """Parse the arguments, send the proposal and print the outcome."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--value", type=float, required=True)
    parser.add_argument("--actor", default="svc:runtime")
    parser.add_argument("--roles", default="service")
    parser.add_argument("--reason", default="e2e proposal")
    print(json.dumps(propose(parser.parse_args())), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
