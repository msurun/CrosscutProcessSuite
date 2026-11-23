"""Naming-rules engine for site tag classification.

# In plain words:
The engine compiles regex rules from the site schema, applies them to tag names,
and classifies the tags into loops, equipment, and signals. The rules are
ordered, and the first match wins. The engine also checks for conflicts and
incomplete loops.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from crosscut_connectors import role_mapping

# Presets for common naming conventions
PRESETS: dict[str, list[dict[str, Any]]] = {
    "isa_suffix": [
        {
            "pattern": (
                r"(?i)^(?P<loop>[A-Z]{2,4}-?\d{2,5}[A-Z]?)"
                r"[._-](?P<role>PV|SP|OP|OUT|MV|MODE)$"
            ),
            "roles": {"OP": role_mapping.ROLE_OUT, "MV": role_mapping.ROLE_PV},
        }
    ],
    "area_equipment_signal": [
        {
            "pattern": r"^(?P<area>\d{3})-(?P<equipment>[A-Z]{2}-\d{3})[-_.](?P<signal>.+)$",
            "name": "Area-Equipment-Signal",
        }
    ],
    "dcs_block_param": [
        {
            "pattern": r"(?i)^(?P<loop>[A-Z0-9_]+)\.(?P<role>PV|SP|OUT|MODE)$",
            "name": "DCS Block.Parameter",
        }
    ],
}

@dataclass(frozen=True)
class NamingRule:
    """A compiled naming rule with a pattern and optional roles and name."""
    pattern: str
    roles: dict[str, str] = field(default_factory=dict)
    name: str = ""

def compile_rules(raw: list[dict[str, Any]]) -> list[NamingRule]:
    """Compile and validate naming rules from raw dicts.

    # In plain words:
    Compiles each rule's pattern and checks that it has a loop or equipment group.
    Raises ValueError for invalid patterns or missing groups.
    """
    rules = []
    for i, rule_dict in enumerate(raw):
        try:
            pattern = rule_dict["pattern"]
            re.compile(pattern)
        except re.error as e:
            raise ValueError(f"Rule {i} has an invalid pattern: {e}") from e

        groups = set(re.compile(pattern).groupindex.keys())
        unknown = groups - ALLOWED_GROUPS
        if unknown:
            raise ValueError(f"Rule {i} has unknown named groups: {', '.join(sorted(unknown))}")
        if "loop" not in groups and "equipment" not in groups:
            raise ValueError(f"Rule {i} must have a 'loop' or 'equipment' group")

        rules.append(
            NamingRule(
                pattern=pattern,
                roles=rule_dict.get("roles", {}),
                name=rule_dict.get("name", ""),
            )
        )
    return rules

# Named regex groups a rule may use; anything else is a typo the engineer should see.
ALLOWED_GROUPS = frozenset({"loop", "role", "area", "equipment", "signal"})


@dataclass(frozen=True)
class TagMatch:
    """A tag matched by a naming rule."""
    tag: str
    rule: int
    loop: str | None = None
    role: str | None = None
    area: str | None = None
    equipment: str | None = None
    signal: str | None = None

def _new_tree() -> dict[str, dict[str, dict[str, list]]]:
    """Return an empty area -> equipment -> {loops, signals} tree."""
    return defaultdict(lambda: defaultdict(lambda: defaultdict(list)))


@dataclass
class NamingResult:
    """The result of applying naming rules to tags."""
    matches: list[TagMatch] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    loops: dict[str, dict[str, str]] = field(default_factory=dict)
    incomplete: list[dict[str, Any]] = field(default_factory=list)
    tree: dict[str, dict[str, dict[str, list]]] = field(default_factory=_new_tree)

def apply_rules(rules: list[NamingRule], tags: list[str]) -> NamingResult:
    """Apply naming rules to tags and return the result.

    # In plain words:
    Applies each rule to each tag in order, and classifies the tags into loops,
    equipment, and signals. The first matching rule wins per tag. The result
    includes the matches, unmatched tags, conflicts, loops, incomplete loops,
    and a tree of areas, equipment, and signals.
    """
    result = NamingResult()
    loop_roles: dict[str, dict[str, str]] = defaultdict(dict)
    conflicts: dict[tuple[str, str], list[str]] = defaultdict(list)

    for tag in tags:
        tag_match = _match_tag(tag, rules)
        if tag_match:
            result.matches.append(tag_match)
            _update_loop_roles(tag_match, loop_roles, conflicts)
            _update_tree(tag_match, result.tree)
        else:
            result.unmatched.append(tag)

    result.loops = dict(loop_roles)
    # Plain dicts so the result serialises and compares like any JSON document.
    result.tree = {a: {e: dict(n) for e, n in eq.items()} for a, eq in result.tree.items()}
    result.conflicts = [
        {"loop": loop, "role": role, "tags": tags}
        for (loop, role), tags in conflicts.items()
    ]
    result.incomplete = _find_incomplete_loops(loop_roles)

    return result

def _match_tag(tag: str, rules: list[NamingRule]) -> TagMatch | None:
    """Match a tag to the first applicable naming rule."""
    for i, rule in enumerate(rules):
        match = re.fullmatch(rule.pattern, tag)
        if match:
            groups = match.groupdict()
            role = _map_role(groups.get("role"), rule.roles)
            return TagMatch(
                tag=tag,
                rule=i,
                loop=groups.get("loop"),
                role=role,
                area=groups.get("area"),
                equipment=groups.get("equipment"),
                signal=groups.get("signal"),
            )
    return None

def _update_loop_roles(
    tag_match: TagMatch,
    loop_roles: dict[str, dict[str, str]],
    conflicts: dict[tuple[str, str], list[str]],
) -> None:
    """Update loop roles and conflicts based on the tag match."""
    if tag_match.loop and tag_match.role:
        loop_id = tag_match.loop
        role_id = tag_match.role
        if role_id in loop_roles[loop_id]:
            first = loop_roles[loop_id][role_id]
            conflicts.setdefault((loop_id, role_id), [first]).append(tag_match.tag)
        else:
            loop_roles[loop_id][role_id] = tag_match.tag

def _update_tree(tag_match: TagMatch, tree: dict[str, dict[str, dict[str, list]]]) -> None:
    """Update the tree of areas, equipment, and signals based on the tag match."""
    node = tree[tag_match.area or ""][tag_match.equipment or ""]
    node.setdefault("loops", [])
    node.setdefault("signals", [])
    if tag_match.loop and tag_match.loop not in node["loops"]:
        node["loops"].append(tag_match.loop)  # one entry per loop, not per loop tag
    elif not tag_match.loop and tag_match.equipment:
        node["signals"].append(tag_match.tag)

def _map_role(role: str | None, roles: dict[str, str]) -> str | None:
    """Map a role to a canonical role using the rule's roles dict."""
    if not role:
        return None
    canonical_role = roles.get(role.lower(), role_mapping.SUFFIX_TO_ROLE.get(role.lower()))
    return canonical_role if canonical_role in role_mapping.LOOP_ROLES else None

def _find_incomplete_loops(loop_roles: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Find loops that are missing required roles."""
    incomplete = []
    for loop_id, roles in loop_roles.items():
        missing = []
        if role_mapping.ROLE_PV not in roles:
            missing.append(role_mapping.ROLE_PV)
        if role_mapping.ROLE_OUT not in roles:
            missing.append(role_mapping.ROLE_OUT)
        if role_mapping.ROLE_SP not in roles:
            missing.append(role_mapping.ROLE_SP)
        if missing:
            incomplete.append({"loop": loop_id, "missing": missing})
    return incomplete
