"""Rule bases as data: immutable model objects and the check that turns a JSON document into one.

The JSON layout is fixed by ``schemas/fuzzy.schema.json``; this module adds the checks a schema
cannot express (parameter order of a membership function, references between rules and terms).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

SHAPE_PARAMETER_COUNTS = {"tri": 3, "trap": 4, "gauss": 2}
AND = "and"
OR = "or"


class FuzzyModelError(ValueError):
    """A rule base document that cannot be evaluated (the message says what is wrong)."""


@dataclass(frozen=True)
class Term:
    """A linguistic term such as "high": a membership function with its parameters."""

    name: str
    shape: str  # "tri" (a, b, c), "trap" (a, b, c, d) or "gauss" (mean, sigma)
    params: tuple[float, ...]


@dataclass(frozen=True)
class Variable:
    """An input or output variable with its engineering range and terms."""

    id: str
    low: float
    high: float
    terms: tuple[Term, ...]
    label: str = ""
    unit: str = ""
    tag: str | None = None

    def term(self, name: str) -> Term:
        """The term called ``name``."""
        return next(term for term in self.terms if term.name == name)


@dataclass(frozen=True)
class Clause:
    """One "variable IS term" statement."""

    variable: str
    term: str


@dataclass(frozen=True)
class Rule:
    """IF clauses (joined by AND or OR) THEN one output clause, with a weight and a switch."""

    id: str
    conditions: tuple[Clause, ...]
    consequent: Clause
    operator: str = AND
    weight: float = 1.0
    enabled: bool = True


@dataclass(frozen=True)
class FuzzySystem:
    """A complete Mamdani system: inputs, outputs and the rule base."""

    name: str
    inputs: tuple[Variable, ...]
    outputs: tuple[Variable, ...]
    rules: tuple[Rule, ...]

    def input(self, variable_id: str) -> Variable:
        """The input called ``variable_id``."""
        return next(variable for variable in self.inputs if variable.id == variable_id)

    def output(self, variable_id: str) -> Variable:
        """The output called ``variable_id``."""
        return next(variable for variable in self.outputs if variable.id == variable_id)


def system_from_dict(document: Mapping[str, Any]) -> FuzzySystem:
    """Build a :class:`FuzzySystem` from a (schema-valid) document, checking what the schema cannot.

    Raises:
        FuzzyModelError: for bad parameter order, duplicate names or references to unknown names.
    """
    try:
        inputs = tuple(_variable(item) for item in document["inputs"])
        outputs = tuple(_variable(item) for item in document["outputs"])
        rules = tuple(_rule(item) for item in document["rules"])
        system = FuzzySystem(str(document["name"]), inputs, outputs, rules)
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        if isinstance(error, FuzzyModelError):
            raise
        raise FuzzyModelError(f"malformed document: {error!r}") from error
    _check_unique(system)
    _check_references(system)
    return system


def _variable(item: Mapping[str, Any]) -> Variable:
    """One variable; its range and every term are checked."""
    low, high = float(item["low"]), float(item["high"])
    if not low < high:
        raise FuzzyModelError(f"variable {item['id']}: low must be below high")
    terms = tuple(_term(str(item["id"]), raw, low, high) for raw in item["terms"])
    return Variable(
        id=str(item["id"]),
        low=low,
        high=high,
        terms=terms,
        label=str(item.get("label", "")),
        unit=str(item.get("unit", "")),
        tag=item.get("tag"),
    )


def _term(variable_id: str, raw: Mapping[str, Any], low: float, high: float) -> Term:
    """One term; the parameters must fit the shape and be ordered."""
    name, shape = str(raw["name"]), str(raw["shape"])
    params = tuple(float(value) for value in raw["params"])
    where = f"variable {variable_id}, term {name}"
    if len(params) != SHAPE_PARAMETER_COUNTS[shape]:
        raise FuzzyModelError(f"{where}: {shape} needs {SHAPE_PARAMETER_COUNTS[shape]} parameters")
    if shape == "gauss":
        if params[1] <= 0.0:
            raise FuzzyModelError(f"{where}: sigma must be positive")
    elif list(params) != sorted(params) or params[0] == params[-1]:
        raise FuzzyModelError(
            f"{where}: parameters must be increasing (a <= b <= c [<= d], a < last)"
        )
    return Term(name, shape, params)


def _rule(item: Mapping[str, Any]) -> Rule:
    """One rule; weight and operator are range-checked."""
    weight = float(item.get("weight", 1.0))
    operator = str(item.get("operator", AND))
    if not 0.0 <= weight <= 1.0:
        raise FuzzyModelError(f"rule {item['id']}: weight must be between 0 and 1")
    if operator not in (AND, OR):
        raise FuzzyModelError(f"rule {item['id']}: operator must be 'and' or 'or'")
    return Rule(
        id=str(item["id"]),
        conditions=tuple(
            Clause(str(clause["variable"]), str(clause["is"])) for clause in item["if"]
        ),
        consequent=Clause(str(item["then"]["variable"]), str(item["then"]["is"])),
        operator=operator,
        weight=weight,
        enabled=bool(item.get("enabled", True)),
    )


def _check_unique(system: FuzzySystem) -> None:
    """Variable ids, term names inside a variable and rule ids must not repeat."""
    ids = [variable.id for variable in (*system.inputs, *system.outputs)]
    _reject_duplicates(ids, "variable id")
    _reject_duplicates([rule.id for rule in system.rules], "rule id")
    for variable in (*system.inputs, *system.outputs):
        _reject_duplicates([term.name for term in variable.terms], f"term of {variable.id}")


def _reject_duplicates(names: Sequence[str], what: str) -> None:
    """Raise when a name occurs twice."""
    for name in names:
        if names.count(name) > 1:
            raise FuzzyModelError(f"duplicate {what}: {name}")


def _check_references(system: FuzzySystem) -> None:
    """Every clause must point at an existing variable and term of the right kind."""
    inputs = {variable.id: variable for variable in system.inputs}
    outputs = {variable.id: variable for variable in system.outputs}
    for rule in system.rules:
        for clause in rule.conditions:
            _check_clause(rule.id, clause, inputs)
        _check_clause(rule.id, rule.consequent, outputs)


def _check_clause(rule_id: str, clause: Clause, variables: Mapping[str, Variable]) -> None:
    """The clause names a known variable of the expected kind and one of its terms."""
    variable = variables.get(clause.variable)
    if variable is None:
        raise FuzzyModelError(f"rule {rule_id}: unknown variable {clause.variable}")
    if clause.term not in [term.name for term in variable.terms]:
        raise FuzzyModelError(f"rule {rule_id}: {clause.variable} has no term {clause.term}")
