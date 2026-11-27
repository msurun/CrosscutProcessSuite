"""Cross-reference checks of the controllers[] section (Phase 2.5 step 1).

Runs after the schema passes. Each function returns readable lines such as
``controllers.0.variables.1.binding: unknown tag 'X'``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

Document = dict[str, Any]
PAIRS = ("validity", "eng", "operator")  # outer to inner


def controller_problems(document: Document) -> list[str]:
    """All problems of the controllers section of a schema-valid document."""
    tags = {tag["id"] for tag in document["tags"]}
    loops = {loop["id"]: loop for loop in document.get("loops", [])}
    controllers = document.get("controllers", [])
    counts = Counter(entry["id"] for entry in controllers)
    problems = [f"controllers: duplicate id {i!r}" for i in sorted(counts) if counts[i] > 1]
    for index, controller in enumerate(controllers):
        problems += _controller(f"controllers.{index}", controller, tags, loops)
    return problems


def _controller(
    where: str, controller: Document, tags: set[str], loops: dict[str, Document]
) -> list[str]:
    """Variable ids, roles and every variable of one controller."""
    variables = controller["variables"]
    counts = Counter(var["id"] for var in variables)
    problems = [f"{where}.variables: duplicate id {i!r}" for i in sorted(counts) if counts[i] > 1]
    roles = {var["role"] for var in variables}
    for role in ("MV", "CV"):
        if role not in roles:
            problems.append(f"{where}.variables: needs at least one {role}")
    problems += _kind_problems(where, controller)
    for index, var in enumerate(variables):
        problems += _variable(f"{where}.variables.{index}", var, tags, loops)
    return problems


def _kind_problems(where: str, controller: Document) -> list[str]:
    """Settings that belong to the controller kind: mpc needs ``mpc``, fuzzy has none of it."""
    mpc = controller["type"] == "mpc"
    problems = []
    if mpc and "mpc" not in controller:
        problems.append(f"{where}.mpc: a controller of type mpc needs its mpc settings")
    if not mpc and "mpc" in controller:
        problems.append(f"{where}.mpc: only a controller of type mpc has mpc settings")
    if mpc and "rule_base" in controller:
        problems.append(f"{where}.rule_base: only a fuzzy controller has a rule_base")
    for index, var in enumerate(controller["variables"]):
        if "target" in var and not (mpc and var["role"] == "CV"):
            problems.append(f"{where}.variables.{index}.target: only a CV of an mpc controller")
    if mpc and "economics" in controller.get("mpc", {}):
        problems += economics_problems(f"{where}.mpc.economics", controller)
    return problems


def _variable(where: str, var: Document, tags: set[str], loops: dict[str, Document]) -> list[str]:
    """Binding, limits and role-specific fields of one variable."""
    problems = _binding(where, var, tags, loops)
    limits = var.get("limits", {})
    if var["role"] != "MV":
        if "move_max" in limits:
            problems.append(f"{where}.limits.move_max: only an MV has move_max")
        if var.get("required"):
            problems.append(f"{where}.required: only an MV can be required")
    return problems + _limit_problems(f"{where}.limits", limits)


def _binding(where: str, var: Document, tags: set[str], loops: dict[str, Document]) -> list[str]:
    """An MV binds a loop that has a mode tag; the others bind a tag."""
    binding, spot = var["binding"], f"{where}.binding"
    if var["role"] == "MV":
        if "loop" not in binding:
            return [f"{spot}: an MV needs a loop"]
        loop = loops.get(binding["loop"])
        if loop is None:
            return [f"{spot}: unknown loop {binding['loop']!r}"]
        return [] if "mode" in loop else [f"{spot}: loop {binding['loop']!r} has no mode tag"]
    if "tag" not in binding:
        return [f"{spot}: a {var['role']} needs a tag"]
    return [] if binding["tag"] in tags else [f"{spot}: unknown tag {binding['tag']!r}"]


def _limit_problems(where: str, limits: Document) -> list[str]:
    """Each pair has lo < hi and the pairs nest: validity, eng, operator."""
    problems = [
        f"{where}.{name}: lo must be below hi"
        for name in PAIRS
        if name in limits and limits[name]["lo"] >= limits[name]["hi"]
    ]
    given = [name for name in PAIRS if name in limits]
    for outer, inner in zip(given, given[1:], strict=False):
        if limits[inner]["lo"] < limits[outer]["lo"] or limits[inner]["hi"] > limits[outer]["hi"]:
            problems.append(f"{where}.{inner}: must lie within {outer}")
    return problems


def economics_problems(where: str, controller: Document) -> list[str]:
    """Economics keys name variables of the right role and soft limits are ordered."""
    block = controller["mpc"]["economics"]
    roles = {var["id"]: var["role"] for var in controller["variables"]}
    problems = []
    for section, allowed in (("cv_value", ("CV", "ICV")), ("mv_cost", ("MV",))):
        for name in block.get(section, {}):
            if roles.get(name) not in allowed:
                problems.append(f"{where}.{section}.{name}: not a {'/'.join(allowed)} of this controller")
    for name, bounds in block.get("soft_limits", {}).items():
        if roles.get(name) not in ("CV", "ICV", "MV"):
            problems.append(f"{where}.soft_limits.{name}: not an MV or CV of this controller")
        elif "lo" in bounds and "hi" in bounds and bounds["lo"] >= bounds["hi"]:
            problems.append(f"{where}.soft_limits.{name}: lo must be below hi")
    return problems
