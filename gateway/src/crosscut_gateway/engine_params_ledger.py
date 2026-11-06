"""The gateway's own ledger of applied parameter sets (ADR 014 section 6); no I/O, no audit.

It decides whether a rollback may skip ``min_interval`` and ``max_ratio``. Everything it knows
comes from values the gateway itself read in the plant and wrote to its audit log (live path:
``record`` after the audit succeeded; restart: ``replay`` of the audit records). Nothing is taken
from proposal data. Units: values in the unit of the parameter.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from crosscut_gateway.interfaces import ParamSetProposal

SameValue = Callable[[str, float, float], bool]


@dataclass
class AppliedSet:
    """One applied set: per target the audited (from, to) values read from the plant."""

    proposal_id: str
    loop_id: str
    rollback_of: str | None
    size: int
    values: dict[str, tuple[float, float]] = field(default_factory=dict)
    unaudited: bool = False
    rolled_back: bool = False

    @property
    def complete(self) -> bool:
        """True when every item of the set has an audited (from, to) pair."""
        return len(self.values) == self.size and not self.unaudited


def _number(text: object) -> float | None:
    """A finite float from audit text, or None (never invented)."""
    try:
        value = float(str(text))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _items_refusal(
    orig: AppliedSet, proposal: ParamSetProposal, same: SameValue
) -> str | None:
    """Compare the rollback's targets, ``from`` and ``to`` with the audited original."""
    targets = [item.target for item in proposal.items]
    if len(set(targets)) != len(targets) or set(targets) != set(orig.values):
        return "targets_mismatch"
    for item in proposal.items:
        before, after = orig.values[item.target]
        if not same(item.target, item.from_value, after):
            return "from_mismatch"
        if not same(item.target, item.to_value, before):
            return "to_mismatch"
    return None


class AppliedLedger:
    """Applied sets by proposal id, the latest set per loop and which sets were rolled back."""

    def __init__(self) -> None:
        """Start empty."""
        self._sets: dict[str, AppliedSet] = {}
        self._latest: dict[str, str] = {}

    def record(
        self,
        proposal: ParamSetProposal,
        read: tuple[Mapping[str, float], Mapping[str, float]],
        audited: bool,
    ) -> None:
        """Add a set the gateway applied; ``audited`` is False when its audit write failed."""
        entry = self._start(proposal.proposal_id, proposal.loop_id, proposal.rollback_of,
                            len(proposal.items))
        from_read, to_read = read
        for item in proposal.items:
            if item.target in from_read and item.target in to_read:
                entry.values[item.target] = (from_read[item.target], to_read[item.target])
        entry.unaudited = not audited

    def _start(self, pid: str, loop: str, rollback_of: str | None, size: int) -> AppliedSet:
        """Create (or fetch) the entry of ``pid``; a new one becomes the latest of its loop."""
        entry = self._sets.get(pid)
        if entry is None:
            entry = AppliedSet(pid, loop, rollback_of, size)
            self._sets[pid] = entry
            self._latest[loop] = pid
            original = self._sets.get(rollback_of or "")
            if original is not None:
                original.rolled_back = True
        return entry

    def replay(self, records: Sequence[Mapping[str, str]]) -> None:
        """Rebuild the ledger from the audit records (``param_write`` rows, in log order)."""
        for row in records:
            if row.get("event") == "param_write":
                self._take(row)

    def _take(self, row: Mapping[str, str]) -> None:
        """Add one audited item; a row that does not parse leaves the set incomplete."""
        pid, tag = str(row.get("proposal_id", "")), str(row.get("tag", ""))
        size = int(_number(row.get("set_size")) or 0)
        if not pid or not tag:
            return
        entry = self._start(pid, str(row.get("loop", "")), row.get("rollback_of") or None, size)
        before, after = _number(row.get("applied_from")), _number(row.get("applied_to"))
        if before is not None and after is not None:
            entry.values[tag] = (before, after)

    def rollback_refusal(self, proposal: ParamSetProposal, same: SameValue) -> str | None:
        """Why ``proposal`` gets no rollback exemption (None = verified, exemption applies).

        The original must be audited and complete, not itself a rollback, not rolled back yet,
        the loop's most recent applied set, and the rollback must restore exactly its audited
        values (``from`` = audited applied_to, ``to`` = audited applied_from).
        """
        orig = self._sets.get(proposal.rollback_of or "")
        if orig is None or not orig.complete:
            return "no_baseline"
        if orig.rollback_of:
            return "rollback_of_rollback"
        if orig.loop_id != proposal.loop_id:
            return "loop_mismatch"
        if orig.rolled_back:
            return "already_rolled_back"
        if self._latest.get(orig.loop_id) != orig.proposal_id:
            return "not_latest_apply"
        return _items_refusal(orig, proposal, same)
