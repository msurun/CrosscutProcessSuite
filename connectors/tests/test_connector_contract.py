"""Contract tests for Connector protocol and adapters (Phase 1, #43).

Verifies declared capabilities, uniform exception handling for unsupported operations,
registry instantiation, and CSV connector browsing and history reading.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from crosscut_connectors.base import (
    CAP_BROWSE,
    CAP_HISTORY,
    CAP_METADATA,
    CAP_READ_LIVE,
    Connector,
    NotSupportedError,
)
from crosscut_connectors.csv_connector import CsvConnector
from crosscut_connectors.opcua_connector import OpcUaConnector
from crosscut_connectors.registry import create_connector
from crosscut_connectors.sql_connector import SqlConnector


def test_registry_creates_expected_adapter_types(tmp_path: Path) -> None:
    csv_conn = create_connector("csv", str(tmp_path))
    assert isinstance(csv_conn, Connector)
    assert isinstance(csv_conn, CsvConnector)

    sql_conn = create_connector("sql", "sqlite:///:memory:")
    assert isinstance(sql_conn, Connector)
    assert isinstance(sql_conn, SqlConnector)

    opc_conn = create_connector("opcua", "opc.tcp://127.0.0.1:4840")
    assert isinstance(opc_conn, Connector)
    assert isinstance(opc_conn, OpcUaConnector)


def test_registry_rejects_unknown_driver() -> None:
    with pytest.raises(ValueError, match="unknown connector driver"):
        create_connector("unsupported_protocol", "endpoint://test")


def test_csv_connector_capabilities(tmp_path: Path) -> None:
    conn = CsvConnector(str(tmp_path))
    caps = conn.capabilities()
    assert CAP_BROWSE in caps
    assert CAP_METADATA in caps
    assert CAP_HISTORY in caps
    assert CAP_READ_LIVE not in caps

    with pytest.raises(NotSupportedError):
        conn.read_live(["TAG1"])


def test_opcua_connector_capabilities() -> None:
    conn = OpcUaConnector("opc.tcp://127.0.0.1:4840")
    caps = conn.capabilities()
    assert CAP_BROWSE in caps
    assert CAP_METADATA in caps
    assert CAP_READ_LIVE in caps
    assert CAP_HISTORY not in caps

    with pytest.raises(NotSupportedError, match="HistoryRead"):
        conn.history(["TAG1"], "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z")


def test_sql_connector_capabilities() -> None:
    conn = SqlConnector("sqlite:///:memory:")
    caps = conn.capabilities()
    assert CAP_BROWSE in caps
    assert CAP_METADATA in caps
    assert CAP_HISTORY in caps
    assert CAP_READ_LIVE not in caps

    with pytest.raises(NotSupportedError):
        conn.read_live(["TAG1"])


def test_csv_connector_browse_and_metadata(tmp_path: Path) -> None:
    csv_file = tmp_path / "feed_data.csv"
    csv_text = "timestamp,TIC101,FIC102\n2026-01-01T00:00:00Z,50.5,100.2\n"
    csv_file.write_text(csv_text, encoding="utf-8")

    conn = CsvConnector(str(tmp_path))
    nodes = conn.browse()
    assert any(n.name == "feed_data.csv" for n in nodes)

    file_nodes = conn.browse(node_id="feed_data.csv")
    names = {n.name for n in file_nodes}
    assert "TIC101" in names
    assert "FIC102" in names

    meta = conn.metadata(["feed_data.csv/TIC101"])
    assert len(meta) == 1
    assert meta[0].id == "feed_data.csv/TIC101"

    hist = conn.history(["feed_data.csv/TIC101"], "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z")
    assert len(hist["data"]) == 1
    assert hist["data"][0]["TIC101"] == "50.5"


def test_sql_connector_browse_and_history(tmp_path: Path) -> None:
    import sqlite3
    db_file = tmp_path / "test.db"
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE history (timestamp TEXT, TIC101 REAL, FIC102 REAL)")
        conn.execute("INSERT INTO history VALUES ('2026-01-01T00:00:00Z', 50.5, 100.2)")
        conn.commit()

    sql_conn = SqlConnector(f"sqlite:///{db_file}", options={"table": "history"})
    tables = sql_conn.browse()
    assert any(t.name == "history" for t in tables)

    columns = sql_conn.browse(node_id="history")
    col_names = {c.name for c in columns}
    assert "TIC101" in col_names

    hist = sql_conn.history(["history.TIC101"], "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z")
    assert "SELECT" in hist["query"]
    assert len(hist["data"]) == 1
    assert hist["data"][0][1] == 50.5

