"""Pure evaluator of the operating modes of the site catalogue (PRODUCT 3.1, #146).

A mode is a condition on tags (schema ``$defs/mode``) with an optional scope: the id of an
equipment entry, or empty for the whole site. For one target (an equipment entry, or the whole
site) this module turns the tag values of every sample into one mode label, so that loop KPIs and
anomaly limits can be kept per mode and stopped equipment can be left out.

Rules, in order of precedence (documented once, used everywhere):

1. Candidates are the modes whose scope is the target, one of its ancestors, or the whole site.
2. Specificity: a mode scoped to the target beats its parent's, and so on up to site-wide modes.
3. Within one scope, the mode id ``stopped`` wins over the others (safety: a stopped machine
   must never be scored as another mode), then catalogue order decides.
4. The first candidate that is neither false nor unknown decides. A candidate with missing or
   non-finite inputs is *unknown* (three-valued logic); if an unknown candidate comes before any
   true one, the sample is ``unknown``, because a higher-precedence mode might hold.
5. No candidate true or unknown gives ``none`` (the modes do not describe this state).

Samples are also excluded as stopped while the equipment's ``running`` signal is at or below its
threshold, even if no ``stopped`` mode is defined.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

STOPPED = "stopped"
UNKNOWN = "unknown"
NO_MODE = "none"
_OPS = {
    "<": np.less, "<=": np.less_equal, ">": np.greater,
    ">=": np.greater_equal, "==": np.equal, "!=": np.not_equal,
}


def _ancestors(site: Mapping[str, Any], target: str | None) -> list[str]:
    """Equipment ids from the target up to the top (target first); empty for the whole site."""
    by_id = {item["id"]: item for item in site.get("equipment", [])}
    chain: list[str] = []
    current = target
    while current and current in by_id and current not in chain:
        chain.append(current)
        current = by_id[current].get("parent") or None
    return chain


def applicable_modes(site: Mapping[str, Any], target: str | None) -> list[dict[str, Any]]:
    """Modes that apply to the target, in precedence order (rules 1 to 3 of the module doc)."""
    chain = _ancestors(site, target)
    ranked = []
    for index, mode in enumerate(site.get("modes", [])):
        scope = mode.get("scope") or ""
        if scope and scope not in chain:
            continue
        depth = chain.index(scope) if scope else len(chain)  # 0 = the target itself
        ranked.append((depth, mode["id"] != STOPPED, index, mode))
    return [mode for *_, mode in sorted(ranked, key=lambda item: item[:3])]


def mode_tags(site: Mapping[str, Any], target: str | None) -> list[str]:
    """Tags a target's mode evaluation reads: mode clauses and the running signal."""
    tags = [clause["tag"] for mode in applicable_modes(site, target)
            for clause in mode["condition"]["clauses"]]
    running = _running(site, target)
    if running:
        tags.append(running["tag"])
    return list(dict.fromkeys(tags))


def _running(site: Mapping[str, Any], target: str | None) -> dict[str, Any] | None:
    """The ``running`` definition of the target or its nearest ancestor that states one."""
    by_id = {item["id"]: item for item in site.get("equipment", [])}
    for equipment_id in _ancestors(site, target):
        if by_id[equipment_id].get("running"):
            return by_id[equipment_id]["running"]
    return None


def _clause(clause: Mapping[str, Any], data: Mapping[str, Any], count: int) -> tuple:
    """(true, known) boolean arrays of one clause; a missing or non-finite input is unknown."""
    if clause["tag"] not in data:
        return np.zeros(count, bool), np.zeros(count, bool)
    values = np.asarray(data[clause["tag"]], dtype=float)
    known = np.isfinite(values)
    with np.errstate(invalid="ignore"):
        truth = _OPS[clause["op"]](values, float(clause["value"])) & known
    return truth, known


def _condition(mode: Mapping[str, Any], data: Mapping[str, Any], count: int) -> tuple:
    """(true, false) arrays of a mode condition; neither is unknown (Kleene logic)."""
    condition = mode["condition"]
    parts = [_clause(clause, data, count) for clause in condition["clauses"]]
    trues = np.stack([truth for truth, _ in parts])
    falses = np.stack([known & ~truth for truth, known in parts])
    if condition.get("match", "all") == "any":
        return trues.any(axis=0), falses.all(axis=0)
    return trues.all(axis=0), falses.any(axis=0)


def evaluate(
    site: Mapping[str, Any], target: str | None, data: Mapping[str, Any], count: int,
) -> np.ndarray:
    """Mode label of each of ``count`` samples for one target (array of str)."""
    labels = np.full(count, NO_MODE, dtype=object)
    undecided = np.ones(count, dtype=bool)
    for mode in applicable_modes(site, target):
        holds, fails = _condition(mode, data, count)
        labels[undecided & holds] = mode["id"]
        labels[undecided & ~holds & ~fails] = UNKNOWN
        undecided &= fails  # only a definite false lets a lower-precedence mode decide
    return labels


def not_running(site: Mapping[str, Any], target: str | None, data: Mapping[str, Any],
                count: int) -> np.ndarray:
    """True where the running signal is known and at or below its threshold."""
    running = _running(site, target)
    if not running or running["tag"] not in data:
        return np.zeros(count, dtype=bool)
    values = np.asarray(data[running["tag"]], dtype=float)
    with np.errstate(invalid="ignore"):
        return np.isfinite(values) & (values <= float(running["above"]))


def stopped_mask(labels: np.ndarray, off: np.ndarray) -> np.ndarray:
    """Samples left out of KPIs and anomaly scoring: mode ``stopped`` or equipment not running."""
    return (np.asarray(labels, dtype=object) == STOPPED) | off


def evaluate_row(site: Mapping[str, Any], target: str | None, row: Mapping[str, float]) -> tuple:
    """(mode label, stopped flag) of one live sample given as ``{tag: value}``."""
    data = {tag: [value] for tag, value in row.items()}
    label = str(evaluate(site, target, data, 1)[0])
    return label, bool(stopped_mask(np.array([label], dtype=object),
                                    not_running(site, target, data, 1))[0])


def owner_of_loop(site: Mapping[str, Any], loop_id: str) -> str | None:
    """Id of the equipment that primarily owns the loop, None when no entry lists it."""
    for item in site.get("equipment", []):
        if loop_id in item.get("loops", []):
            return str(item["id"])
    return None
