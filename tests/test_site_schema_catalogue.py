"""Contract tests for the site schema and its internal definitions.

Validates that the site schema correctly enforces constraints on signals,
equipment, loops, labs, and modes using the generic concentrator example.
"""

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "site.schema.json"
SITE_EXAMPLE = ROOT / "docs" / "examples" / "generic_concentrator" / "_site" / "site.json"


def load_validator() -> Draft202012Validator:
    """Return a Draft 2020-12 validator for the site schema."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def mutated(base: dict[str, Any], path: list[str | int], value: Any) -> dict[str, Any]:
    """Return a deep copy of base with the value at path replaced, or deleted."""
    out = copy.deepcopy(base)
    node: Any = out
    for key in path[:-1]:
        node = node[key]
    if value == "__delete__":
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return out


SITE_DOC: dict[str, Any] = json.loads(SITE_EXAMPLE.read_text(encoding="utf-8"))
Mutator = Callable[[dict[str, Any]], dict[str, Any]]


def test_base_valid() -> None:
    """The base example document must be valid."""
    assert load_validator().is_valid(SITE_DOC)


def test_minimal_doc_valid() -> None:
    """A minimal document with only the required fields must be valid."""
    minimal = {"schema_version": 1, "site": {"name": "min"}, "tags": [{"id": "T1"}]}
    assert load_validator().is_valid(minimal)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda base: mutated(base, ["signals", 0, "role"], "PV"),
        lambda base: mutated(base, ["signals", 0, "role"], "__delete__"),
        lambda base: mutated(base, ["signals", 0, "module"], "x"),
        lambda base: mutated(base, ["equipment", 0, "level"], "plant"),
        lambda base: mutated(base, ["equipment", 0, "criticality"], "extreme"),
        lambda base: mutated(base, ["equipment", 0, "unknown_key"], "val"),
        lambda base: mutated(base, ["loops", 0, "pv"], "__delete__"),
        lambda base: mutated(base, ["loops", 0, "action"], "up"),
        lambda base: mutated(base, ["loops", 0, "links"], [{"kind": "cascade2", "loop": "test"}]),
        lambda base: mutated(base, ["labs", 0, "stamp", "meaning"], "begin"),
        lambda base: mutated(base, ["labs", 0, "stamp", "meaning"], "__delete__"),
        lambda base: mutated(base, ["labs", 0, "composite_window_s"], 0),
        lambda base: mutated(base, ["labs", 0, "latency_s"], -1),
        lambda base: mutated(base, ["modes", 0, "condition"], "__delete__"),
        lambda base: mutated(base, ["modes", 0, "condition", "clauses"], []),
        lambda base: mutated(base, ["modes", 0, "condition", "clauses", 0, "op"], "=~"),
        lambda base: mutated(base, ["modes", 0, "unknown_top_key"], "val"),
        lambda base: mutated(base, ["tags", 0, "role"], "SP"),
    ],
)
def test_invalid_mutations(mutate: Mutator) -> None:
    """Invalid mutations of the example document must not validate."""
    assert not load_validator().is_valid(mutate(SITE_DOC))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda base: mutated(base, ["labs", 0, "stamp", "meaning"], "middle"),
        lambda base: mutated(base, ["modes", 0, "condition", "match"], "any"),
        lambda base: mutated(base, ["equipment", 0, "criticality"], "low"),
        lambda base: mutated(base, ["equipment", 0, "criticality"], "medium"),
        lambda base: mutated(base, ["equipment", 0, "criticality"], "high"),
        lambda base: mutated(base, ["equipment", 0, "criticality"], "critical"),
        lambda base: mutated(base, ["signals", 0, "role"], "pv"),
        lambda base: mutated(base, ["signals", 0, "role"], "sp"),
        lambda base: mutated(base, ["signals", 0, "role"], "out"),
        lambda base: mutated(base, ["signals", 0, "role"], "mode"),
        lambda base: mutated(base, ["signals", 0, "role"], "fb"),
        lambda base: mutated(base, ["signals", 0, "role"], "input"),
        lambda base: mutated(base, ["signals", 0, "role"], "target"),
        lambda base: mutated(base, ["signals", 0, "role"], "lab"),
        lambda base: mutated(base, ["signals", 0, "role"], "dv"),
    ],
)
def test_valid_mutations(mutate: Mutator) -> None:
    """Valid mutations of the example document must validate."""
    assert load_validator().is_valid(mutate(SITE_DOC))
