"""Fuzzy supervisor: gated, explained, logged advice from a fuzzy rule base (ADR 010).

Advice can become a setpoint proposal, but only the Write Gateway writes (ADR 012):
the package must not import opcua or connectors.
"""

from crosscut_supervisor.proposal import (
    ProposalContext,
    ProposalRefusal,
    SetpointProposal,
    build_setpoint_proposal,
    signed_change,
)

__all__ = [
    "ProposalContext",
    "ProposalRefusal",
    "SetpointProposal",
    "build_setpoint_proposal",
    "signed_change",
]
