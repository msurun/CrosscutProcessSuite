"""Tests for the SQL historian profiles (Phase 5, #50).

Every shipped profile is exercised against an in-memory sqlite database whose tables and
columns carry the names the profile's SQL expects. The data is synthetic and identical in
meaning for each vendor: two tags, four in-window samples with good/uncertain/bad quality,
one sample outside the requested window, and one latest sample per tag.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from crosscut_connectors.base import CAP_READ_LIVE, LiveValue
from crosscut_connectors.registry import connector_from_source
from crosscut_connectors.sql_connector import SqlConnector
from crosscut_connectors.sql_profiles import (
    PROFILE_SCHEMA_PATH,
    SQL_PROFILES_DIR,
    ProfileError,
    available_profiles,
    load_profile,
    map_quality,
    profile_problems,
)
from jsonschema import Draft202012Validator

START = "2026-01-01T00:00:00Z"
END = "2026-01-01T01:00:00Z"
IN_WINDOW = (
    "2026-01-01T00:10:00Z",
    "2026-01-01T00:20:00Z",
    "2026-01-01T00:30:00Z",
    "2026-01-01T00:40:00Z",
)
LATEST_TIME = "2026-01-01T00:40:00Z"
LATEST_VALUE = 53.5


@dataclass(frozen=True)
class HistorianCase:
    """Expected values for one vendor's synthetic database."""

    profile: str
    tag: str
    other_tag: str
    description: str
    unit: str
    good_code: int
    uncertain_code: int
    bad_code: int


@dataclass(frozen=True)
class Scenario:
    """One synthetic historian: its expected values and its connector."""

    case: HistorianCase
    connector: SqlConnector


IP21_SCHEMA = """
CREATE TABLE IP_AnalogDef (
    NAME TEXT, DESCRIPTION TEXT, ENG_UNITS TEXT, LO_LIMIT REAL, HI_LIMIT REAL
);
CREATE TABLE HISTORY (
    NAME TEXT, TS TEXT, VALUE REAL, QUALITY INTEGER, PERIOD INTEGER
);
"""
IP21_TAGS = (
    ("TIC101", "Reactor temperature", "degC", 0.0, 200.0),
    ("FIC102", "Feed flow", "m3/h", 0.0, 500.0),
)
IP21_SAMPLES = (
    ("TIC101", "2026-01-01T00:10:00Z", 50.5, 0, 60),
    ("TIC101", "2026-01-01T00:20:00Z", 51.0, 1, 5),
    ("TIC101", "2026-01-01T00:30:00Z", 52.0, 2, 60),
    ("TIC101", "2026-01-01T00:40:00Z", 53.5, 0, 60),
    ("TIC101", "2025-12-31T23:00:00Z", 99.0, 0, 60),
    ("FIC102", "2026-01-01T00:10:00Z", 100.0, 0, 60),
)
IP21_CASE = HistorianCase(
    "aspen_ip21", "TIC101", "FIC102", "Reactor temperature", "degC", 0, 1, 2
)

PHD_SCHEMA = """
CREATE TABLE TAG (
    TAGNAME TEXT, DESCRIPTION TEXT, UNIT TEXT, RANGE_LOW REAL, RANGE_HIGH REAL
);
CREATE TABLE HISTORY (
    TAGNAME TEXT, TIMESTAMP TEXT, VALUE REAL, QUALITY INTEGER
);
"""
PHD_TAGS = (
    ("TIC101", "Reactor temperature", "degC", 0.0, 200.0),
    ("FIC102", "Feed flow", "m3/h", 0.0, 500.0),
)
PHD_SAMPLES = (
    ("TIC101", "2026-01-01T00:10:00Z", 50.5, 0),
    ("TIC101", "2026-01-01T00:20:00Z", 51.0, 1),
    ("TIC101", "2026-01-01T00:30:00Z", 52.0, 2),
    ("TIC101", "2026-01-01T00:40:00Z", 53.5, 0),
    ("TIC101", "2025-12-31T23:00:00Z", 99.0, 0),
    ("FIC102", "2026-01-01T00:10:00Z", 100.0, 0),
)
PHD_CASE = HistorianCase(
    "honeywell_phd", "TIC101", "FIC102", "Reactor temperature", "degC", 0, 1, 2
)

WONDERWARE_SCHEMA = """
CREATE TABLE Tag (TagName TEXT, Description TEXT);
CREATE TABLE AnalogTag (TagName TEXT, EngUnits TEXT, MinEU REAL, MaxEU REAL);
CREATE TABLE EngineeringUnit (EngUnits TEXT, Description TEXT);
CREATE TABLE History (
    TagName TEXT, DateTime TEXT, Value REAL, QualityDetail INTEGER,
    wwRetrievalMode TEXT, wwResolution INTEGER
);
"""
WONDERWARE_TAGS = (
    ("TIC101", "Reactor temperature"),
    ("FIC102", "Feed flow"),
)
WONDERWARE_ANALOG_TAGS = (
    ("TIC101", "degC", 0.0, 200.0),
    ("FIC102", "m3/h", 0.0, 500.0),
)
WONDERWARE_UNITS = (("degC", "degC"), ("m3/h", "m3/h"))
WONDERWARE_SAMPLES = (
    ("TIC101", "2026-01-01T00:10:00Z", 50.5, 192, "Delta", 0),
    ("TIC101", "2026-01-01T00:20:00Z", 51.0, 64, "Delta", 0),
    ("TIC101", "2026-01-01T00:30:00Z", 52.0, 128, "Delta", 0),
    ("TIC101", "2026-01-01T00:40:00Z", 53.5, 192, "Delta", 0),
    ("TIC101", "2025-12-31T23:00:00Z", 99.0, 192, "Delta", 0),
    ("FIC102", "2026-01-01T00:10:00Z", 100.0, 192, "Delta", 0),
    ("TIC101", "2026-01-01T00:10:00Z", 50.5, 192, "Cyclic", 60),
    ("TIC101", "2026-01-01T00:20:00Z", 51.0, 64, "Cyclic", 60),
    ("TIC101", "2026-01-01T00:40:00Z", 53.5, 192, "Cyclic", 60),
)
WONDERWARE_CASE = HistorianCase(
    "aveva_wonderware", "TIC101", "FIC102", "Reactor temperature", "degC", 192, 64, 128
)

WINCC_SCHEMA = """
CREATE TABLE TAG (TAG_NAME TEXT, COMMENT TEXT, UNIT TEXT);
CREATE TABLE WINCC_ARCHIVE (
    TAG_NAME TEXT, TIMESTAMP_UTC TEXT, VALUE REAL, QUALITY INTEGER
);
"""
WINCC_TAGS = (
    ("TIC101", "Reactor temperature", "degC"),
    ("FIC102", "Feed flow", "m3/h"),
)
WINCC_SAMPLES = (
    ("TIC101", "2026-01-01T00:10:00Z", 50.5, 192),
    ("TIC101", "2026-01-01T00:20:00Z", 51.0, 64),
    ("TIC101", "2026-01-01T00:30:00Z", 52.0, 128),
    ("TIC101", "2026-01-01T00:40:00Z", 53.5, 192),
    ("TIC101", "2025-12-31T23:00:00Z", 99.0, 192),
    ("FIC102", "2026-01-01T00:10:00Z", 100.0, 192),
)
WINCC_CASE = HistorianCase(
    "siemens_wincc", "TIC101", "FIC102", "Reactor temperature", "degC", 192, 64, 128
)


def _build_ip21_database() -> sqlite3.Connection:
    """An in-memory IP.21-shaped database with synthetic tags and samples."""
    connection = sqlite3.connect(":memory:")
    connection.executescript(IP21_SCHEMA)
    connection.executemany("INSERT INTO IP_AnalogDef VALUES (?, ?, ?, ?, ?)", IP21_TAGS)
    connection.executemany("INSERT INTO HISTORY VALUES (?, ?, ?, ?, ?)", IP21_SAMPLES)
    return connection


def _build_phd_database() -> sqlite3.Connection:
    """An in-memory PHD-shaped database with synthetic tags and samples."""
    connection = sqlite3.connect(":memory:")
    connection.executescript(PHD_SCHEMA)
    connection.executemany("INSERT INTO TAG VALUES (?, ?, ?, ?, ?)", PHD_TAGS)
    connection.executemany("INSERT INTO HISTORY VALUES (?, ?, ?, ?)", PHD_SAMPLES)
    return connection


def _build_wonderware_database() -> sqlite3.Connection:
    """An in-memory InSQL-shaped database with Delta and Cyclic history rows."""
    connection = sqlite3.connect(":memory:")
    connection.executescript(WONDERWARE_SCHEMA)
    connection.executemany("INSERT INTO Tag VALUES (?, ?)", WONDERWARE_TAGS)
    connection.executemany("INSERT INTO AnalogTag VALUES (?, ?, ?, ?)", WONDERWARE_ANALOG_TAGS)
    connection.executemany("INSERT INTO EngineeringUnit VALUES (?, ?)", WONDERWARE_UNITS)
    connection.executemany("INSERT INTO History VALUES (?, ?, ?, ?, ?, ?)", WONDERWARE_SAMPLES)
    return connection


def _build_wincc_database() -> sqlite3.Connection:
    """An in-memory WinCC-shaped database with a site WINCC_ARCHIVE view."""
    connection = sqlite3.connect(":memory:")
    connection.executescript(WINCC_SCHEMA)
    connection.executemany("INSERT INTO TAG VALUES (?, ?, ?)", WINCC_TAGS)
    connection.executemany("INSERT INTO WINCC_ARCHIVE VALUES (?, ?, ?, ?)", WINCC_SAMPLES)
    return connection


CASES: dict[str, tuple[HistorianCase, Callable[[], sqlite3.Connection]]] = {
    "aspen_ip21": (IP21_CASE, _build_ip21_database),
    "honeywell_phd": (PHD_CASE, _build_phd_database),
    "aveva_wonderware": (WONDERWARE_CASE, _build_wonderware_database),
    "siemens_wincc": (WINCC_CASE, _build_wincc_database),
}


def _connector(profile: str, connection: sqlite3.Connection) -> SqlConnector:
    """A connector reading the given in-memory database through the named profile."""
    return SqlConnector("sqlite://", {"profile": profile}, connection=connection)


def _shipped_document(profile_name: str) -> dict[str, Any]:
    """The raw JSON document of one shipped profile."""
    path = SQL_PROFILES_DIR / f"{profile_name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _profile_schema() -> dict[str, Any]:
    """The profile JSON Schema as a Python object."""
    return json.loads(PROFILE_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(params=sorted(CASES))
def scenario(request: pytest.FixtureRequest) -> Scenario:
    """A fresh connector and synthetic database for each shipped profile."""
    profile_name = request.param
    case, build_database = CASES[profile_name]
    return Scenario(case, _connector(profile_name, build_database()))


@pytest.mark.parametrize("profile_name", available_profiles())
def test_shipped_profile_matches_the_profile_schema(profile_name: str) -> None:
    """Every JSON file in sql_profiles/ is accepted by the published schema."""
    Draft202012Validator(_profile_schema()).validate(_shipped_document(profile_name))


@pytest.mark.parametrize("profile_name", available_profiles())
def test_shipped_profile_loads_without_problems(profile_name: str) -> None:
    """Every shipped profile passes schema and cross-field checks."""
    profile = load_profile(profile_name)

    assert profile.name == profile_name


def test_history_is_time_bounded_and_ordered(scenario: Scenario) -> None:
    """Only samples inside the window are returned, oldest first."""
    result = scenario.connector.history([scenario.case.tag], START, END)

    assert [sample["timestamp_utc"] for sample in result["data"]] == list(IN_WINDOW)


def test_history_excludes_samples_after_the_end(scenario: Scenario) -> None:
    """Narrowing the end time drops later samples from the same archive."""
    result = scenario.connector.history([scenario.case.tag], START, "2026-01-01T00:20:00Z")

    assert [sample["timestamp_utc"] for sample in result["data"]] == list(IN_WINDOW[:2])


def test_history_maps_every_vendor_quality_code(scenario: Scenario) -> None:
    """Good, uncertain and bad vendor codes become 0, 1 and 2 in that order."""
    result = scenario.connector.history([scenario.case.tag], START, END)

    assert [sample["quality"] for sample in result["data"]] == [0, 1, 2, 0]


def test_history_returns_only_the_requested_tag(scenario: Scenario) -> None:
    """A one-tag request does not leak samples of the other tag."""
    result = scenario.connector.history([scenario.case.tag], START, END)

    assert {sample["tag_id"] for sample in result["data"]} == {scenario.case.tag}


def test_latest_value_is_the_newest_archive_sample(scenario: Scenario) -> None:
    """The latest query returns the newest sample with its mapped quality."""
    values = scenario.connector.read_live([scenario.case.tag])

    assert values[scenario.case.tag] == LiveValue(LATEST_VALUE, 0, LATEST_TIME)


def test_browse_lists_tags_with_description_and_unit(scenario: Scenario) -> None:
    """Browsing the profile root returns both tags with their engineering unit."""
    nodes = {node.name: node for node in scenario.connector.browse()}

    assert nodes[scenario.case.tag].description == scenario.case.description
    assert nodes[scenario.case.tag].unit == scenario.case.unit
    assert scenario.case.other_tag in nodes


def test_metadata_reports_description_and_unit(scenario: Scenario) -> None:
    """Metadata carries the description and unit of the requested tag."""
    [metadata] = scenario.connector.metadata([scenario.case.tag])

    assert (metadata.description, metadata.unit) == (
        scenario.case.description,
        scenario.case.unit,
    )


def test_profile_connector_declares_latest_value_support(scenario: Scenario) -> None:
    """A profile supplies latest values, so read_live is advertised."""
    assert CAP_READ_LIVE in scenario.connector.capabilities()


def test_each_quality_class_maps_to_its_live_value_code(scenario: Scenario) -> None:
    """The profile's own good, uncertain and bad codes map to 0, 1 and 2."""
    profile = load_profile(scenario.case.profile)

    assert map_quality(profile.quality, scenario.case.good_code) == 0
    assert map_quality(profile.quality, scenario.case.uncertain_code) == 1
    assert map_quality(profile.quality, scenario.case.bad_code) == 2


def test_an_unknown_quality_code_is_bad() -> None:
    """A code outside every range must not look trustworthy."""
    profile = load_profile("aspen_ip21")

    assert map_quality(profile.quality, 999) == 2


def test_ip21_period_request_uses_the_period_query() -> None:
    """A 60-second request reads only IP.21 samples recorded with that period."""
    connector = _connector("aspen_ip21", _build_ip21_database())

    result = connector.history(["TIC101"], START, END, period_s=60)

    assert [sample["timestamp_utc"] for sample in result["data"]] == [
        "2026-01-01T00:10:00Z",
        "2026-01-01T00:30:00Z",
        "2026-01-01T00:40:00Z",
    ]


def test_wonderware_period_request_uses_cyclic_history() -> None:
    """A period request switches InSQL from Delta retrieval to Cyclic retrieval."""
    connector = _connector("aveva_wonderware", _build_wonderware_database())

    result = connector.history(["TIC101"], START, END, period_s=60)

    assert [sample["value"] for sample in result["data"]] == [50.5, 51.0, 53.5]


def test_ip21_metadata_reports_engineering_limits() -> None:
    """The IP.21 metadata query exposes the analog definition limits."""
    connector = _connector("aspen_ip21", _build_ip21_database())

    [metadata] = connector.metadata(["TIC101"])

    assert (metadata.eng_min, metadata.eng_max) == (0.0, 200.0)


def test_metadata_for_an_unknown_tag_is_an_error() -> None:
    """Asking for a tag the historian does not know raises a clear LookupError."""
    connector = _connector("aspen_ip21", _build_ip21_database())

    with pytest.raises(LookupError, match="has no tag"):
        connector.metadata(["NOPE"])


def test_a_site_source_selects_a_profile() -> None:
    """A source-level profile reaches the connector built from the site catalogue."""
    connector = connector_from_source(
        {"driver": "sql", "endpoint": "sqlite://", "profile": "aspen_ip21"}
    )

    assert isinstance(connector, SqlConnector)
    assert connector.profile is not None
    assert connector.profile.name == "aspen_ip21"


def test_an_unknown_profile_name_is_an_error() -> None:
    """A name that is not shipped is reported with the available names."""
    with pytest.raises(ProfileError, match="unknown SQL historian profile"):
        load_profile("not_a_vendor")


def test_a_profile_name_cannot_leave_the_profile_folder() -> None:
    """Path characters are rejected before a file is opened."""
    with pytest.raises(ProfileError, match="invalid SQL historian profile name"):
        load_profile("../aspen_ip21")


def test_the_profile_schema_requires_a_history_quality_column() -> None:
    """A profile without a quality column cannot map quality and is rejected."""
    document = _shipped_document("aspen_ip21")
    del document["history"]["columns"]["quality"]

    problems = profile_problems(document)

    assert any("quality" in problem for problem in problems)


def test_the_wincc_profile_documents_the_tag_r_archive_syntax() -> None:
    """The unverified list names TAG:R, the syntax a site view has to wrap."""
    profile = load_profile("siemens_wincc")

    assert any("TAG:R" in item for item in profile.unverified)
