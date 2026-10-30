"""CI guard: fail if plant-specific words leak into the generic CrosscutProcessSuite repo.

The list of plant words is a plain text file whose path comes from the
environment variable ``CROSSCUT_PLANT_WORDS_FILE``.  Each non-comment line
in that file is a Python regular expression.  This module scans the
repository and fails the test run when any regex matches a line of a text
file.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

# Suffixes of text files that are scanned.  Binary files are intentionally
# excluded because reading them with ``errors="replace"`` would only produce
# noise, not useful matches.
SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".vue", ".json", ".md", ".toml",
                 ".yaml", ".yml", ".sql"}

# Directory names that are skipped anywhere in a relative path.  They contain
# generated output, dependencies, caches, or unrelated data and are not part
# of the generic repository content.
SKIP_DIRECTORY_NAMES = {
    "experiments", "graphify-out", "build", ".git", "node_modules",
    "__pycache__", ".venv", "data", ".agent-out", "artifacts",
}

# Known leftovers that still contain plant-specific words.  This list shall
# shrink as the affected files are removed or moved out of the generic repo.
# Each entry is a relative POSIX path that is either an exact match or a
# directory prefix.
ALLOW_LISTED_RELATIVE_PATHS = ("sim/", "opcua/")


def _read_lines(word_file: Path) -> list[str]:
    """Return the lines of ``word_file``, failing the test if it cannot be read.

    Args:
        word_file: UTF-8 text file to read.

    Returns:
        The file content split into lines.
    """
    try:
        return word_file.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        pytest.fail(f"Cannot read plant-word file {word_file}: {error}")


def _compile_line(word_file: Path, line_number: int, stripped_line: str) -> re.Pattern[str]:
    """Compile one regex line from ``word_file``, failing the test if invalid.

    Args:
        word_file: File the line came from, used in the failure message.
        line_number: One-based line number, used in the failure message.
        stripped_line: The regex text with surrounding whitespace removed.

    Returns:
        The compiled regular expression.
    """
    try:
        return re.compile(stripped_line)
    except re.error as error:
        pytest.fail(
            f"Invalid regex in {word_file} on line {line_number} "
            f"({stripped_line!r}): {error}"
        )


def load_patterns(word_file: Path) -> list[re.Pattern[str]]:
    """Load one regex per non-comment, non-blank line from ``word_file``.

    Args:
        word_file: UTF-8 text file containing regular expressions.

    Returns:
        Compiled patterns in the order they appear in the file.

    Raises:
        pytest.fail: If the file cannot be read, a line contains an invalid
            regex, or the file contains no usable patterns.
    """
    if not word_file.is_file():
        pytest.fail(
            f"Plant-word file {word_file} does not exist or is not a file; "
            "a configured guard that cannot read its list must fail loudly."
        )

    patterns: list[re.Pattern[str]] = []
    for line_number, raw_line in enumerate(_read_lines(word_file), start=1):
        stripped_line = raw_line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue
        patterns.append(_compile_line(word_file, line_number, stripped_line))

    if not patterns:
        pytest.fail(f"Plant-word file {word_file} contains no usable patterns.")
    return patterns


def iter_scan_files(root: Path) -> Iterator[Path]:
    """Yield text files below ``root``, honouring skip and allow lists.

    Args:
        root: Repository root directory.

    Yields:
        Absolute paths of regular files whose suffix is in
        :data:`SCAN_SUFFIXES`, whose relative POSIX path does not contain a
        skipped directory name, and which is not allow-listed.
    """
    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts

        if any(part in SKIP_DIRECTORY_NAMES for part in relative_parts):
            continue

        relative_posix_path = path.relative_to(root).as_posix()
        if relative_posix_path == ALLOW_LISTED_RELATIVE_PATHS[0]:
            continue
        if relative_posix_path.startswith(ALLOW_LISTED_RELATIVE_PATHS[1:]):
            continue

        if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES:
            yield path


def find_hits(root: Path, patterns: list[re.Pattern[str]]) -> list[str]:
    """Scan repository text files and return one human-readable string per match.

    Args:
        root: Repository root directory.
        patterns: Compiled plant-word regular expressions.

    Returns:
        Strings of the form ``"{relpath}:{lineno}: {pattern!r} -> {line}"``
        for every regex match.  ``line`` is the stripped matched line with
        whitespace collapsed, so the failure output stays compact.
    """
    hits: list[str] = []
    for file_path in iter_scan_files(root):
        hits.extend(_hits_in_file(root, file_path, patterns))
    return hits


def _hits_in_file(root: Path, file_path: Path, patterns: list[re.Pattern[str]]) -> list[str]:
    """Return one human-readable string per regex match inside ``file_path``.

    Args:
        root: Repository root directory, used to build relative paths.
        file_path: Text file to scan.
        patterns: Compiled plant-word regular expressions.

    Returns:
        Strings of the form ``"{relpath}:{lineno}: {pattern!r} -> {line}"``
        in file order, then line order, then pattern order.
    """
    relative_posix_path = file_path.relative_to(root).as_posix()
    text = file_path.read_text(encoding="utf-8", errors="replace")
    hits: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped_line = " ".join(raw_line.strip().split())
        for pattern in patterns:
            if pattern.search(stripped_line):
                hits.append(
                    f"{relative_posix_path}:{line_number}: "
                    f"{pattern.pattern!r} -> {stripped_line}"
                )
    return hits


def test_repo_contains_no_plant_words() -> None:
    """Fail if any plant-specific regex matches a repository text file."""
    word_file_env = os.environ.get("CROSSCUT_PLANT_WORDS_FILE")
    if not word_file_env:
        pytest.skip("CROSSCUT_PLANT_WORDS_FILE not set; plant-word check skipped")

    word_file = Path(word_file_env)
    patterns = load_patterns(word_file)
    repo_root = Path(__file__).resolve().parents[1]
    hits = find_hits(repo_root, patterns)

    if hits:
        pytest.fail(
            "Plant-specific words found in generic repository files:\n"
            + "\n".join(hits)
        )
