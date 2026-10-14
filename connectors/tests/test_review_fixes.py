"""Regression tests for the code-review findings on the connectors (2026-10-14).

Each test names the failure it guards against: unit headers that collide, text quality flags,
a fixed anonymiser seed, a linked tag that overrides a kept one, and SQL that writes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from crosscut_connectors.anonymise import anonymise
from crosscut_connectors.csv_import import import_csv, split_unit
from crosscut_connectors.csv_long import import_csv_long
from crosscut_connectors.import_target import ImportTarget
from crosscut_connectors.sql_import import fetch_rows
from crosscut_sim.dataset import read_dataset, to_wide


def test_a_bracket_after_a_digit_or_with_a_number_is_not_a_unit() -> None:
    """'Valve [1]', 'LIC101[PV]' and 'Temp (reactor 1)' keep their whole text as the name."""
    for header in ("Valve [1]", "LIC101[PV]", "Temp (reactor 1)"):
        assert split_unit(header) == (header, "")


def test_headers_that_collide_without_their_suffix_keep_their_full_names(tmp_path: Path) -> None:
    """'Level (A)' and 'Level (B)' import as two tags instead of failing on duplicates."""
    path = tmp_path / "a.csv"
    path.write_text("time;Level (A);Level (B)\n2026-01-01T00:00:00Z;1;2\n", encoding="utf-8")
    import_csv(path, tmp_path / "out", dataset_id="d")
    _, columns = to_wide(read_dataset(tmp_path / "out"))
    assert len(columns) == 2


def test_text_quality_words_in_a_long_csv_are_understood(tmp_path: Path) -> None:
    """'Good', 'Bad' and an empty quality cell no longer abort the import."""
    path = tmp_path / "l.csv"
    path.write_text(
        "time,tag,value,quality\n"
        "2026-01-01T00:00:00Z,A,1,Good\n"
        "2026-01-01T00:00:10Z,A,2,Bad\n"
        "2026-01-01T00:00:20Z,A,3,\n",
        encoding="utf-8",
    )
    report = import_csv_long(path, ImportTarget(tmp_path / "out", "q"))
    assert report.n_rows == 3


def test_an_unknown_quality_word_is_a_clear_error(tmp_path: Path) -> None:
    """A quality that is neither a number nor a known word raises ValueError naming it."""
    path = tmp_path / "l.csv"
    path.write_text("time,tag,value,quality\n2026-01-01T00:00:00Z,A,1,maybe\n", encoding="utf-8")
    with pytest.raises(ValueError, match="maybe"):
        import_csv_long(path, ImportTarget(tmp_path / "out", "q"))


def test_without_a_seed_two_runs_differ_and_the_seed_is_returned() -> None:
    """The default seed is random, so customers do not share one transform; it is kept."""
    t_s = np.arange(50.0)
    columns = {"a": np.sin(t_s)}
    first, second = anonymise(t_s, columns), anonymise(t_s, columns)
    assert first.time_shift_s != second.time_shift_s
    assert anonymise(t_s, columns, seed=first.seed).time_shift_s == first.time_shift_s


def test_a_tag_both_linked_and_kept_is_refused() -> None:
    """A mode flag put in a linked group by mistake must not be scaled silently."""
    t_s = np.arange(10.0)
    columns = {"pv": t_s, "mode": np.ones(10)}
    with pytest.raises(ValueError, match="mode"):
        anonymise(t_s, columns, linked_groups=[["pv", "mode"]], keep_values=["mode"])


def test_an_empty_linked_group_is_a_value_error() -> None:
    """An empty group gives ValueError instead of IndexError."""
    with pytest.raises(ValueError, match="at least one"):
        anonymise(np.arange(3.0), {"a": np.zeros(3)}, linked_groups=[[]])


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * INTO copy FROM history",
        "SELECT 1 -- DROP TABLE t",
        "SELECT 1 /* x */",
        "WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x",
        "EXEC sp_who",
    ],
)
def test_sql_that_writes_or_hides_text_is_refused(query: str) -> None:
    """Queries with INTO, INSERT, EXEC or comments never reach the connection."""
    with pytest.raises(ValueError):
        fetch_rows(object(), query)
