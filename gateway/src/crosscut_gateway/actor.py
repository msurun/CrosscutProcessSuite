"""Actor identity carried with each gateway command.

ActorContext records who issued a command and from where, for authorization and audit.
The gateway's own internal actions are attributed to GATEWAY_ACTOR.
"""

from __future__ import annotations

import unicodedata
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


_CONFUSABLE_SCRIPTS = frozenset({"LATIN", "CYRILLIC", "GREEK"})


def normalize_actor(name: str) -> str:
    """Return the canonical comparison form of an actor name.

    NFKC-normalised, surrounding whitespace stripped, inner whitespace collapsed, case folded
    (and re-normalised, as casefolding can denormalise). Use it for every comparison of
    proposer, approver and author; audit records keep the originally claimed spelling.
    """
    folded = " ".join(unicodedata.normalize("NFKC", name).split()).casefold()
    return unicodedata.normalize("NFKC", folded)


def _letter_scripts(name: str) -> set[str]:
    """Return the confusable-prone scripts (Latin, Cyrillic, Greek) of the letters in name."""
    scripts: set[str] = set()
    for char in name:
        if char.isalpha():
            script = unicodedata.name(char, "").split(" ", 1)[0]
            if script in _CONFUSABLE_SCRIPTS:
                scripts.add(script)
    return scripts


def _is_unsafe_char(char: str) -> bool:
    """Return True for control, format, surrogate, private-use, unassigned and line separators."""
    category = unicodedata.category(char)
    return category.startswith("C") or category in ("Zl", "Zp")


def is_valid_actor_name(name: object) -> bool:
    """Return True for a non-blank string that is safe to use as an actor identity.

    Refuses control, format (zero-width, bidi), surrogate, private-use and unassigned characters
    (Unicode category C*), line and paragraph separators, and names that mix Latin, Cyrillic
    or Greek letters (ASCII lookalikes such as Cyrillic "a" inside "admin").
    """
    if not isinstance(name, str) or not name.strip():
        return False
    if any(_is_unsafe_char(char) for char in name):
        return False
    return len(_letter_scripts(name)) <= 1
