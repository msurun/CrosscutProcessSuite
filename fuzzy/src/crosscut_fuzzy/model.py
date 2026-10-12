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
    """One variable; its range and every term are checked.

    In a fuzzy model, a *variable* (the domain) such as "temperature" is defined over a numeric
    interval [low, high], and onto that interval we place *terms* -- fuzzy sets like "cold" or
    "hot" -- each described by its own membership function. This builder reads one variable from
    a mapping (e.g. parsed YAML/JSON) and returns the domain object.

    Args:
        item: Mapping with keys "id", "low", "high", "terms", and optional "label", "unit",
            "tag". "low"/"high" are in the variable's own unit and must satisfy low < high;
            "terms" is a sequence of term mappings, each consumed by _term.

    Returns:
        The constructed Variable, with terms clipped to [low, high].

    Raises:
        FuzzyModelError: If the range is empty or inverted (low >= high).
    """
    # The domain bounds: low and high are numbers (float, in the variable's own unit, e.g. 18.0
    # degrees Celsius). Casting to float means strings coming from YAML/JSON are accepted too.
    low, high = float(item["low"]), float(item["high"])
    # A fuzzy variable needs a non-empty interval; a zero-width or inverted range would make
    # every membership function degenerate, so fail loudly instead of producing silent nonsense.
    if not low < high:
        raise FuzzyModelError(f"variable {item['id']}: low must be below high")
    # Each term (fuzzy set) is built once, eagerly. Stored as a tuple: terms are
    # fixed at build time and the tuple keeps them immutable and hash-friendly.
    terms = tuple(_term(str(item["id"]), raw, low, high) for raw in item["terms"])
    # Assemble the domain. "label" and "unit" are presentation metadata ("" when absent, so callers
    # never compare against None). "tag" is an optional free-form marker carried through unchanged
    # -- it defaults to None because, unlike label/unit, an empty string would be a meaningful tag.
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
    """Build one fuzzy set (a "term", e.g. "cold", "warm") of a variable.

    `raw` is the JSON-like mapping for this term: its `name` (label), its `shape`
    (membership-function kind, a key of SHAPE_PARAMETER_COUNTS) and its `params`
    (the floats that define that shape, in the order the shape expects).

    `low` and `high` are the variable's universe bounds; kept in the signature for
    callers that validate against them, unused here.

    Returns a Term. Raises FuzzyModelError if the parameter count or ordering does
    not fit the shape.
    """
    name, shape = str(raw["name"]), str(raw["shape"])
    params = tuple(float(value) for value in raw["params"])
    # `where` is reused in every error message so the user can locate the bad term.
    where = f"variable {variable_id}, term {name}"
    # Each shape needs a fixed number of parameters (e.g. a triangle needs 3
    # points); a wrong count makes the arithmetic below meaningless.
    if len(params) != SHAPE_PARAMETER_COUNTS[shape]:
        raise FuzzyModelError(f"{where}: {shape} needs {SHAPE_PARAMETER_COUNTS[shape]} parameters")
    # Parameter meaning per shape:
    #   gauss: (mean, sigma); sigma is a standard deviation, so it must be > 0.
    #   trap/triangular: the breakpoints of the membership curve on the x-axis
    #     (e.g. a, b, c for a triangle), which must be non-decreasing and span
    #     a non-zero width — otherwise the fuzzy set is degenerate.
    if shape == "gauss":
        if params[1] <= 0.0:
            raise FuzzyModelError(f"{where}: sigma must be positive")
    elif list(params) != sorted(params) or params[0] == params[-1]:
        raise FuzzyModelError(
            f"{where}: parameters must be increasing (a <= b <= c [<= d], a < last)"
        )
    return Term(name, shape, params)


def _rule(item: Mapping[str, Any]) -> Rule:
    """Build one fuzzy rule from its raw JSON-like mapping.

    A rule has the shape::

        {"id": "r1", "if": [{"variable": "temp", "is": "hot"}],
         "then": {"variable": "fan", "is": "fast"},
         "operator": "and", "weight": 0.8, "enabled": true}

    Defaults are applied here (weight 1.0, operator "and", enabled true) and
    the numeric fields are range-checked, so everything downstream can rely on
    a Rule whose values are already valid.

    Returns:
        Rule: the validated rule.

    Raises:
        FuzzyModelError: if `weight` is outside [0, 1] or `operator` is
            neither "and" nor "or".
    """
    # `weight` is the rule's activation degree, a unitless number in [0, 1]:
    # 0 means the rule is ignored, 1 means it counts at full strength. Values
    # in between scale the rule's contribution (soft evidence).
    weight = float(item.get("weight", 1.0))
    # `operator` tells how the clauses in "if" are combined: AND takes the
    # minimum of their membership degrees, OR takes the maximum. Stored as a
    # plain string so it round-trips through JSON.
    operator = str(item.get("operator", AND))
    # Reject bad input loudly now, instead of producing silently wrong
    # inference results later.
    if not 0.0 <= weight <= 1.0:
        raise FuzzyModelError(f"rule {item['id']}: weight must be between 0 and 1")
    if operator not in (AND, OR):
        raise FuzzyModelError(f"rule {item['id']}: operator must be 'and' or 'or'")
    # "if" is a list of {variable, is} pairs (the antecedents); each is turned
    # into a Clause naming a linguistic term such as ("temp", "hot"). A tuple
    # is used so the Rule is immutable and hashable: the number and order of
    # conditions must never change after construction.
    return Rule(
        id=str(item["id"]),
        conditions=tuple(
            Clause(str(clause["variable"]), str(clause["is"])) for clause in item["if"]
        ),
        # "then" is the single consequent: the output variable and the term it
        # takes when the rule fires.
        consequent=Clause(str(item["then"]["variable"]), str(item["then"]["is"])),
        operator=operator,
        weight=weight,
        # `enabled` lets a rule stay in the model but be skipped, unitless
        # boolean (an explicit false keeps the rule present for editing).
        enabled=bool(item.get("enabled", True)),
    )


def _check_unique(system: FuzzySystem) -> None:
    """Variable ids, term names inside a variable and rule ids must not repeat.

    A fuzzy system addresses inputs and outputs by id, and the terms of a
    variable by name. Duplicates would make those lookups ambiguous: the
    same id could mean two different variables, and the same name two
    different membership functions. Rules have the same problem with their
    ids.

    Raises:
        DuplicateError: if any id or term name appears more than once.
    """
    # Variables are keyed independently of the input/output split: names must be
    # unique across both lists, so build one flat id lookup covering both.
    ids = [variable.id for variable in (*system.inputs, *system.outputs)]
    _reject_duplicates(ids, "variable id")
    # Rules are addressed by id, so a repeated id would make it impossible to
    # tell which rule is meant.
    _reject_duplicates([rule.id for rule in system.rules], "rule id")
    # Term names only need to be unique within their own variable; the same
    # name ("low", "high") is expected to appear in several variables.
    for variable in (*system.inputs, *system.outputs):
        _reject_duplicates([term.name for term in variable.terms], f"term of {variable.id}")


def _reject_duplicates(names: Sequence[str], what: str) -> None:
    """Raise when a name occurs twice."""
    for name in names:
        if names.count(name) > 1:
            raise FuzzyModelError(f"duplicate {what}: {name}")


def _check_references(system: FuzzySystem) -> None:
    """Every clause must point at an existing variable and term of the right kind.

    A fuzzy system is a set of IF-THEN rules. Each rule has 'conditions' (the IF part)
    and exactly one 'consequent' (the THEN part). A clause is a single term of the form
    '<variable> IS <term>', e.g. 'temperature IS hot'; it names a variable by id and a
    term by id. This function cross-checks those ids against the variables that really
    exist in the system, so a typo in a rule is reported as an error instead of silently
    making the rule dead.

    Raises:
        ReferenceError: if any clause names a variable or term that does not exist, or
            names it in the wrong place (an input variable in the THEN part, or an
            output variable in the IF part). The exception message carries the rule id and
            the offending clause so the user can find the mistake.
    """
    # Index the declared variables by id for O(1) lookup while scanning the rules, instead
    # of searching the input/output lists for every clause. Both dicts are re-created here
    # so the check always reflects the current state of the system.
    inputs = {variable.id: variable for variable in system.inputs}
    outputs = {variable.id: variable for variable in system.outputs}
    for rule in system.rules:
        # The IF part of a rule may only mention input variables, since it is evaluated
        # against the observed facts.
        for clause in rule.conditions:
            _check_clause(rule.id, clause, inputs)
        # The THEN part of a rule assigns an output variable, so it is checked against the
        # outputs table only. This asymmetric lookup is what enforces the input/output
        # distinction mentioned in the docstring.
        _check_clause(rule.id, rule.consequent, outputs)


def _check_clause(rule_id: str, clause: Clause, variables: Mapping[str, Variable]) -> None:
    """Check one clause of a fuzzy rule before the rule is used.

    A clause refers to one variable (for example "temperature") and one of that
    variable's terms (a named fuzzy set on it, for example "warm"). Both names are
    plain strings in the rule text, so they can be misspelled; this function turns
    a misspelling into a clear error instead of a confusing failure later.

    Args:
        rule_id: name of the rule being validated, used only to build error messages.
        clause: the clause to validate, holding a variable name and a term name.
        variables: all known variables, keyed by their name.

    Raises:
        FuzzyModelError: if the variable is unknown, or if the variable exists but
            has no term with that name.
    """
    # values in a mapping are their own kind: this is a cross-check, not a title lookup.
    variable = variables.get(clause.variable)
    if variable is None:
        raise FuzzyModelError(f"rule {rule_id}: unknown variable {clause.variable}")
    # like a query can actually be found: term names are the per-variable list of strings.
    if clause.term not in [term.name for term in variable.terms]:
        raise FuzzyModelError(f"rule {rule_id}: {clause.variable} has no term {clause.term}")
