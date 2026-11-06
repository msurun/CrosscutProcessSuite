"""Argument validation and mapping of the ``propose_params`` command (ADR 014 section 3).

Strict and bounded: a list of item objects with exactly the known keys, finite numbers (bool
refused), limited sizes. Anything else is an invalid_args reply, before the engine sees it.
"""

from __future__ import annotations

import math
from typing import Any

from crosscut_gateway.interfaces import ParamItem, ParamSetProposal

MAX_ITEMS = 8
MAX_TEXT = 128
MAX_REASON = 1000
MAX_NS = 2**63 - 1
_ITEM_TEXT = ("param", "target", "unit", "vendor_form")
_ITEM_KEYS = frozenset((*_ITEM_TEXT, "from", "to"))
_ARG_KEYS = frozenset(
    ("proposal_id", "loop_id", "items", "proposer", "t_ns", "expires_ns", "reason", "rollback_of")
)


class ParamArgsError(ValueError):
    """The arguments of a propose_params command are malformed."""


def _text(name: str, value: Any, *, limit: int = MAX_TEXT, blank: bool = False) -> str:
    """A str of at most ``limit`` characters (non-empty unless ``blank``)."""
    if not isinstance(value, str) or len(value) > limit or (not blank and not value.strip()):
        raise ParamArgsError(f"propose_params: {name} must be a text of 1-{limit} characters")
    return value


def _number(name: str, value: Any) -> float:
    """A finite int or float; bool and non-finite values are refused."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParamArgsError(f"propose_params: {name} must be a number, not bool")
    try:
        finite = math.isfinite(float(value))
    except OverflowError:
        finite = False
    if not finite:
        raise ParamArgsError(f"propose_params: {name} out of range")
    return float(value)


def _ns(name: str, value: Any) -> int:
    """A positive int below 2**63 (UTC nanoseconds); bool is refused."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= MAX_NS:
        raise ParamArgsError(f"propose_params: {name} must be a positive int (ns)")
    return value


def parse_item(index: int, raw: Any) -> ParamItem:
    """Validate one item object and build the ParamItem."""
    if not isinstance(raw, dict) or set(raw) != _ITEM_KEYS:
        keys = sorted(_ITEM_KEYS)
        raise ParamArgsError(f"propose_params: items[{index}] must have exactly {keys}")
    texts = {key: _text(f"items[{index}].{key}", raw[key]) for key in _ITEM_TEXT}
    return ParamItem(
        param=texts["param"],
        target=texts["target"],
        unit=texts["unit"],
        vendor_form=texts["vendor_form"],
        from_value=_number(f"items[{index}].from", raw["from"]),
        to_value=_number(f"items[{index}].to", raw["to"]),
    )


def _rollback_of(args: dict[str, Any]) -> str | None:
    """The optional id of the reverted proposal: absent or null means None."""
    value = args.get("rollback_of")
    return None if value is None else _text("rollback_of", value)


def parse_propose_params(args: dict[str, Any]) -> ParamSetProposal:
    """Validate the arguments of propose_params and build the ParamSetProposal.

    Raises:
        ParamArgsError: When any argument is missing, of the wrong type, out of range or unknown.
    """
    unknown = sorted(set(args) - _ARG_KEYS)
    if unknown:
        raise ParamArgsError(f"propose_params: unknown argument {unknown[0]!r}")
    items = args.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise ParamArgsError(f"propose_params: items must be a list of 1-{MAX_ITEMS} objects")
    return ParamSetProposal(
        proposal_id=_text("proposal_id", args.get("proposal_id")),
        loop_id=_text("loop_id", args.get("loop_id")),
        items=tuple(parse_item(index, raw) for index, raw in enumerate(items)),
        proposer=_text("proposer", args.get("proposer")),
        t_ns=_ns("t_ns", args.get("t_ns")),
        expires_ns=_ns("expires_ns", args.get("expires_ns")),
        reason=_text("reason", args.get("reason"), limit=MAX_REASON, blank=True),
        rollback_of=_rollback_of(args),
    )


def item_summary(item: ParamItem) -> dict[str, Any]:
    """The JSON form of an item (state.json and the API): ``from``/``to`` as numbers."""
    return {
        "param": item.param,
        "target": item.target,
        "unit": item.unit,
        "vendor_form": item.vendor_form,
        "from": item.from_value,
        "to": item.to_value,
    }


def proposal_summary(key: str, proposal: ParamSetProposal) -> dict[str, Any]:
    """The summary of a pending parameter set for state.json."""
    return {
        "key": key,
        "kind": "pid_param",
        "proposal_id": proposal.proposal_id,
        "loop_id": proposal.loop_id,
        "proposer": proposal.proposer,
        "t_ns": proposal.t_ns,
        "expires_ns": proposal.expires_ns,
        "reason": proposal.reason,
        "rollback_of": proposal.rollback_of,
        "items": [item_summary(item) for item in proposal.items],
    }
