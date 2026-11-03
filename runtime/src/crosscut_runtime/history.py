"""
Own SQLite-based history store for live samples.
Provides local historical data because the OPC UA test server has no HistoryRead support.
Resolves Phase 1 #44.
"""

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

HISTORY_FILE = "history.sqlite3"


class HistoryError(RuntimeError):
    """Raised when a database operation fails, wrapping the underlying SQLite error."""


def history_path(root: Path) -> Path:
    """
    Get the path to the history database file for a given project root.
    
    Returns:
        The path to the history SQLite database.
    """
    return root / "_runtime" / HISTORY_FILE


class HistoryStore:
    """
    Stores time-series samples in a local SQLite database.
    Thread-safe by opening a new connection for each operation.
    """

    def __init__(self, path: Path) -> None:
        """
        Initialize the store, creating the file and schema if they do not exist.
        """
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create the schema and configure the database (WAL mode)."""
        schema = """
        CREATE TABLE IF NOT EXISTS samples(
            tag TEXT NOT NULL,
            ts REAL NOT NULL,
            value REAL NOT NULL,
            PRIMARY KEY(tag, ts)
        ) WITHOUT ROWID;
        """
        try:
            with closing(sqlite3.connect(self._path)) as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                with conn:
                    conn.execute(schema)
        except sqlite3.Error as err:
            raise HistoryError(f"Failed to initialize database: {err}") from err

    def append(self, rows: Iterable[tuple[str, float, float]]) -> int:
        """
        Insert multiple samples, ignoring existing exact duplicates (tag + timestamp).
        
        Args:
            rows: Iterable of (tag, timestamp in epoch seconds UTC, value in engineering units).
            
        Returns:
            The number of rows successfully inserted.
        """
        query = "INSERT OR IGNORE INTO samples (tag, ts, value) VALUES (?, ?, ?)"
        try:
            with closing(sqlite3.connect(self._path)) as conn:
                start_changes = conn.total_changes
                with conn:
                    conn.executemany(query, rows)
                return conn.total_changes - start_changes
        except sqlite3.Error as err:
            raise HistoryError(f"Failed to append rows: {err}") from err

    def query(
        self, tag: str, since_ts: float | None = None, until_ts: float | None = None
    ) -> list[tuple[float, float]]:
        """
        Retrieve historical samples for a specific tag.
        
        Args:
            tag: The tag to query.
            since_ts: Start time (inclusive) in epoch seconds UTC.
            until_ts: End time (inclusive) in epoch seconds UTC.
            
        Returns:
            A list of (timestamp UTC, value) sorted by timestamp ascending.
        """
        query = "SELECT ts, value FROM samples WHERE tag = ?"
        params: list[str | float] = [tag]

        if since_ts is not None:
            query += " AND ts >= ?"
            params.append(since_ts)
        if until_ts is not None:
            query += " AND ts <= ?"
            params.append(until_ts)

        query += " ORDER BY ts ASC"

        try:
            with closing(sqlite3.connect(self._path)) as conn:
                cursor = conn.execute(query, params)
                return [(row[0], row[1]) for row in cursor.fetchall()]
        except sqlite3.Error as err:
            raise HistoryError(f"Failed to query tag {tag}: {err}") from err

    def tags(self) -> list[str]:
        """
        Get all unique tags currently stored in the database.
        
        Returns:
            A list of tag strings sorted alphabetically.
        """
        query = "SELECT DISTINCT tag FROM samples ORDER BY tag ASC"
        try:
            with closing(sqlite3.connect(self._path)) as conn:
                cursor = conn.execute(query)
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as err:
            raise HistoryError(f"Failed to list tags: {err}") from err

    def prune(self, older_than_ts: float) -> int:
        """
        Delete samples older than the specified timestamp.
        
        Args:
            older_than_ts: Cutoff time in epoch seconds UTC (exclusive).
            
        Returns:
            The number of rows deleted.
        """
        query = "DELETE FROM samples WHERE ts < ?"
        try:
            with closing(sqlite3.connect(self._path)) as conn:
                start_changes = conn.total_changes
                with conn:
                    conn.execute(query, (older_than_ts,))
                return conn.total_changes - start_changes
        except sqlite3.Error as err:
            raise HistoryError(f"Failed to prune old data: {err}") from err

    def count(self) -> int:
        """
        Count the total number of samples across all tags.
        
        Returns:
            The total row count.
        """
        query = "SELECT COUNT(*) FROM samples"
        try:
            with closing(sqlite3.connect(self._path)) as conn:
                cursor = conn.execute(query)
                return int(cursor.fetchone()[0])
        except sqlite3.Error as err:
            raise HistoryError(f"Failed to count rows: {err}") from err
