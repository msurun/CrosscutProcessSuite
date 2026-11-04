"""Actor identity carried with each gateway command.

ActorContext records who issued a command and from where, for authorization and audit.
The gateway's own internal actions are attributed to GATEWAY_ACTOR.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActorContext:
    """Identity of the party issuing a command, with the fields written to the audit log."""

    actor: str
    roles: tuple[str, ...] = ()
    session: str = ""
    source_ip: str = ""
    cmd_id: str = ""

    def audit_fields(self) -> dict[str, str]:
        """Return the audit-log fields for this actor; roles are joined with commas."""
        return {
            "actor": self.actor,
            "roles": ",".join(self.roles),
            "session": self.session,
            "source_ip": self.source_ip,
            "cmd_id": self.cmd_id,
        }


GATEWAY_ACTOR = ActorContext(actor="gateway")
