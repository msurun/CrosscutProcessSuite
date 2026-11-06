"""Advisory supervisor: gated, explained, logged advice from a fuzzy rule base (ADR 010).

The package never writes to a plant: it must not import opcua or connectors.
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
