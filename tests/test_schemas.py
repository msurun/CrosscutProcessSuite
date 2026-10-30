"""Contract tests for the JSON Schemas in schemas/.

Each schema must be a valid Draft 2020-12 schema, accept the valid example
documents below and reject the invalid mutations of them.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
DRAFT = "https://json-schema.org/draft/2020-12/schema"

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64

TAG: dict[str, Any] = {
    "id": "sim.mill1.hpgr.press_sp",
    "name": "sim.mill1.hpgr.press_sp",
    "description": "HPGR specific pressing force setpoint",
    "unit": "N/mm2",
    "type": "float",
    "eng_min": 0.0,
    "eng_max": 6.0,
    "role": "SP",
    "source": {"driver": "opcua", "address": "ns=2;s=mill1.hpgr.press_sp"},
    "sample_period_s": 1.0,
    "writable": True,
}

TAGS_DOC: dict[str, Any] = {"schema_version": "0.1.0", "tags": [TAG]}

DATASET_DOC: dict[str, Any] = {
    "schema_version": "0.1.0",
    "dataset_id": "wood_berry_nominal_seed42",
    "created_utc": "2026-10-10T12:00:00Z",
    "source": {"kind": "sim", "plant": "wood_berry", "scenario": "nominal", "seed": 42},
    "time_range": {"start_utc": "2026-01-01T00:00:00Z", "end_utc": "2026-01-01T06:00:00Z"},
    "tags": ["sim.wb.top_comp", "sim.wb.bottom_comp"],
    "row_count": 43200,
    "storage": {"format": "parquet", "layout": "long", "partitioning": "daily", "path": "data/wb"},
    "code": {"git_commit": "88bb329"},
    "data_sha256": SHA_A,
}

PROJECT_DOC: dict[str, Any] = {
    "schema_version": "0.1.0",
    "meta": {"name": "wood-berry-demo", "description": "Wood-Berry column demo project"},
    "tags_file": "tags.json",
    "loops": [
        {
            "id": "top_comp_loop",
            "pv": "sim.wb.top_comp",
            "sp": "sim.wb.top_comp_sp",
            "out": "sim.wb.reflux",
            "mode": "sim.wb.top_comp_mode",
        }
    ],
    "variables": [
        {"tag": "sim.wb.reflux", "role": "MV", "low": 0.0, "high": 10.0},
        {"tag": "sim.wb.top_comp", "role": "CV"},
        {"tag": "sim.wb.feed_rate", "role": "DV"},
    ],
}

MANIFEST_DOC: dict[str, Any] = {
    "schema_version": "0.1.0",
    "artifact_type": "model",
    "created_utc": "2026-10-10T12:00:00Z",
    "creator": {"tool": "crosscut-ident", "version": "0.1.0", "git_commit": "88bb329"},
    "inputs": [{"dataset_hash": SHA_A}],
    "tags_signature": SHA_B,
    "payload": [{"path": "model.npz", "sha256": SHA_C}],
    "metrics": {"rmse": 0.12},
    "valid_context": {},
    "signature": None,
}


def load(name: str) -> dict[str, Any]:
    """Read one JSON schema file from the schemas directory."""
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def validator(name: str) -> Draft202012Validator:
    """Return a validator for the named schema, after checking the schema itself is valid."""
    schema = load(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


FUZZY_EXAMPLE = Path(__file__).resolve().parents[1] / "fuzzy/examples/mill_feed_supervisor.json"
FUZZY_DOC: dict[str, Any] = json.loads(FUZZY_EXAMPLE.read_text("utf8"))


def mutated(doc: dict[str, Any], path: list[str | int], value: Any) -> dict[str, Any]:
    """Return a deep copy of doc with the value at path replaced (or deleted if value is a
    sentinel string "__delete__")."""
    out = copy.deepcopy(doc)
    node: Any = out
    for key in path[:-1]:
        node = node[key]
    if value == "__delete__":
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return out


SCHEMA_FILES = [
    "tags.schema.json",
    "dataset.schema.json",
    "project.schema.json",
    "artifact-manifest.schema.json",
    "fuzzy.schema.json",
]


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_schema_metadata(name: str) -> None:
    schema = load(name)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == DRAFT
    assert schema["$id"].startswith("https://")
    assert schema["title"]
    assert schema["description"]


@pytest.mark.parametrize(
    ("name", "doc"),
    [
        ("tags.schema.json", TAGS_DOC),
        ("dataset.schema.json", DATASET_DOC),
        ("project.schema.json", PROJECT_DOC),
        ("artifact-manifest.schema.json", MANIFEST_DOC),
        ("fuzzy.schema.json", FUZZY_DOC),
    ],
)
def test_valid_documents(name: str, doc: dict[str, Any]) -> None:
    errors = list(validator(name).iter_errors(doc))
    assert errors == [], [error.message for error in errors]


TAGS_INVALID = [
    mutated(TAGS_DOC, ["tags", 0, "id"], "__delete__"),
    mutated(TAGS_DOC, ["tags", 0, "role"], "XX"),
    mutated(TAGS_DOC, ["tags", 0, "type"], "string"),
    mutated(TAGS_DOC, ["tags", 0, "sample_period_s"], 0),
    mutated(TAGS_DOC, ["tags", 0, "unexpected"], 1),
    mutated(TAGS_DOC, ["schema_version"], "1.0"),
    mutated(TAGS_DOC, ["tags"], "__not_a_list__"),
]

DATASET_INVALID = [
    mutated(DATASET_DOC, ["source", "kind"], "magic"),
    mutated(DATASET_DOC, ["source", "ground_truth"], {"loop": {"stiction_band": "wide"}}),
    mutated(DATASET_DOC, ["source", "ground_truth"], ["stiction"]),
    mutated(DATASET_DOC, ["storage", "layout"], "diagonal"),
    mutated(DATASET_DOC, ["row_count"], -1),
    mutated(DATASET_DOC, ["data_sha256"], "abc"),
    mutated(DATASET_DOC, ["tags"], "__delete__"),
    mutated(DATASET_DOC, ["schema_version"], "v1"),
]

PROJECT_INVALID = [
    mutated(PROJECT_DOC, ["meta"], "__delete__"),
    mutated(PROJECT_DOC, ["variables", 0, "role"], "SP"),
    mutated(PROJECT_DOC, ["loops", 0, "pv"], "__delete__"),
    mutated(PROJECT_DOC, ["tags_file"], "__delete__"),  # neither tags nor tags_file left
    mutated(PROJECT_DOC, ["schema_version"], "x"),
    mutated(PROJECT_DOC, ["loops", 0, "delay_s"], -5),
    mutated(PROJECT_DOC, ["loops", 0, "amplitude_limit"], 0),
]

FUZZY_INVALID = [
    mutated(FUZZY_DOC, ["inputs"], []),
    mutated(FUZZY_DOC, ["inputs", 0, "terms", 0, "shape"], "bell"),
    mutated(FUZZY_DOC, ["inputs", 0, "terms", 0, "params"], [1]),
    mutated(FUZZY_DOC, ["inputs", 0, "id"], "has space"),
    mutated(FUZZY_DOC, ["rules", 0, "weight"], 1.5),
    mutated(FUZZY_DOC, ["rules", 0, "operator"], "xor"),
    mutated(FUZZY_DOC, ["rules", 0, "then"], "__delete__"),
    mutated(FUZZY_DOC, ["rules", 0, "if"], []),
    mutated(FUZZY_DOC, ["schema_version"], "1"),
]

MANIFEST_INVALID = [
    mutated(MANIFEST_DOC, ["payload", 0, "sha256"], "short"),
    mutated(MANIFEST_DOC, ["creator"], "__delete__"),
    mutated(MANIFEST_DOC, ["artifact_type"], ""),
    mutated(MANIFEST_DOC, ["schema_version"], "v1"),
    mutated(MANIFEST_DOC, ["inputs", 0, "dataset_hash"], "zz"),
    mutated(MANIFEST_DOC, ["signature"], 12),
]


@pytest.mark.parametrize("doc", TAGS_INVALID)
def test_tags_rejects_invalid(doc: dict[str, Any]) -> None:
    assert list(validator("tags.schema.json").iter_errors(doc))


@pytest.mark.parametrize("doc", DATASET_INVALID)
def test_dataset_rejects_invalid(doc: dict[str, Any]) -> None:
    assert list(validator("dataset.schema.json").iter_errors(doc))


@pytest.mark.parametrize("doc", PROJECT_INVALID)
def test_project_rejects_invalid(doc: dict[str, Any]) -> None:
    assert list(validator("project.schema.json").iter_errors(doc))


@pytest.mark.parametrize("doc", FUZZY_INVALID)
def test_fuzzy_rejects_invalid(doc: dict[str, Any]) -> None:
    assert list(validator("fuzzy.schema.json").iter_errors(doc))


@pytest.mark.parametrize("doc", MANIFEST_INVALID)
def test_manifest_rejects_invalid(doc: dict[str, Any]) -> None:
    assert list(validator("artifact-manifest.schema.json").iter_errors(doc))


def test_project_accepts_per_loop_settings() -> None:
    doc = copy.deepcopy(PROJECT_DOC)
    settings = {"name": "Top composition", "delay_s": 1.0, "ultimate_period_s": 6.0}
    doc["loops"][0].update(settings, amplitude_limit=0.5)
    assert not list(validator("project.schema.json").iter_errors(doc))


def test_project_inline_catalog() -> None:
    doc = mutated(PROJECT_DOC, ["tags_file"], "__delete__")
    doc["tags"] = [TAG]
    assert list(validator("project.schema.json").iter_errors(doc)) == []


def test_manifest_accepts_string_signature() -> None:
    doc = mutated(MANIFEST_DOC, ["signature"], "base64:AAAA")
    assert list(validator("artifact-manifest.schema.json").iter_errors(doc)) == []


def test_dataset_accepts_ground_truth_of_injected_faults() -> None:
    doc = mutated(DATASET_DOC, ["source", "ground_truth"], {"hpgr_press": {"stiction_band": 2.0}})
    assert list(validator("dataset.schema.json").iter_errors(doc)) == []


SITE_EXAMPLE = SCHEMAS.parents[0] / "docs/examples/generic_concentrator/_site/site.json"
SITE_DOC: dict[str, Any] = json.loads(SITE_EXAMPLE.read_text("utf8"))


def site_errors(doc: dict[str, Any]) -> list[Any]:
    return list(validator("site.schema.json").iter_errors(doc))


def test_site_schema_metadata() -> None:
    Draft202012Validator.check_schema(load("site.schema.json"))


def test_site_example_validates() -> None:
    assert site_errors(SITE_DOC) == []


def test_site_has_no_plant_defaults() -> None:
    """The schema states no default values, so no plant's convention is built in."""
    assert '"default"' not in (SCHEMAS / "site.schema.json").read_text("utf8")


@pytest.mark.parametrize("code", [-999, -9999, 1e30, 65535, 0])
def test_site_accepts_any_missing_code(code: float) -> None:
    doc = mutated(SITE_DOC, ["import", "missing_codes"], [code])
    doc["tags"][0]["missing_codes"] = [code, -1]
    assert site_errors(doc) == []


def test_site_accepts_minimal_document() -> None:
    doc = {"schema_version": 1, "site": {"name": "x"}, "tags": [{"id": "A.B"}]}
    assert site_errors(doc) == []


def test_site_accepts_full_tag() -> None:
    tag = {
        "id": "T1",
        "unit": "%",
        "source": "sim",
        "address": "ns=2;s=T1",
        "dtype": "float",
        "range": {"min": 0, "max": 100},
        "eng_limits": {"max": 90},
        "sampling": {"period_s": 5, "on_change": True},
        "compression": {"deadband": 0.5, "deadband_unit": "percent_of_span"},
        "quality_map": {"192": "good", "0": "bad"},
    }
    assert site_errors({**SITE_DOC, "tags": [tag]}) == []


SITE_INVALID = [
    mutated(SITE_DOC, ["schema_version"], 2),
    mutated(SITE_DOC, ["site"], "__delete__"),
    mutated(SITE_DOC, ["tags"], "__delete__"),
    mutated(SITE_DOC, ["unexpected"], 1),
    mutated(SITE_DOC, ["import", "missing_codes"], ["-9999"]),
    mutated(SITE_DOC, ["import", "missing_codes"], [-1, -1]),
    mutated(SITE_DOC, ["import", "delimiter"], ";;"),
    mutated(SITE_DOC, ["import", "time_names"], []),
    mutated(SITE_DOC, ["defaults", "sample_period_s"], 0),
    mutated(SITE_DOC, ["sources", 0, "driver"], "ftp"),
    mutated(SITE_DOC, ["sources", 0, "password"], "secret"),
    mutated(SITE_DOC, ["tags", 0, "id"], "has space"),
    mutated(SITE_DOC, ["tags", 0, "dtype"], "XX"),
    mutated(SITE_DOC, ["tags", 0, "eng_limits"], {}),
    mutated(SITE_DOC, ["tags", 0, "min"], 0),
    mutated(SITE_DOC, ["tags", 0, "quality_map"], {"192": "fine"}),
    mutated(SITE_DOC, ["tags", 0, "compression"], {"deadband": -1}),
]


@pytest.mark.parametrize("doc", SITE_INVALID)
def test_site_rejects_invalid(doc: dict[str, Any]) -> None:
    assert site_errors(doc)


def test_site_rejects_zero_conversion_factor() -> None:
    conversion = {"from": "a", "to": "b", "factor": 0}
    assert site_errors({**SITE_DOC, "units": {"conversions": [conversion]}})
