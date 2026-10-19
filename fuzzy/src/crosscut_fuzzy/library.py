"""Where rule bases live: bundled examples (read-only) and the user's own saved systems.

A user system with the same id as an example hides it, so "save" on an example creates the user
copy. Ids are plain identifiers; anything else is refused so an id can never walk out of the
directory.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from crosscut_fuzzy.model import FuzzyModelError, system_from_dict

ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
SOURCE_EXAMPLE = "example"
SOURCE_USER = "user"


def examples_dir() -> Path:
    """Directory of the bundled example systems (next to the package in the repository)."""
    return Path(__file__).resolve().parents[2] / "examples"


def check_id(system_id: str) -> str:
    """The id when it is a plain identifier.

    A "system id" names one fuzzy system inside its catalogue. Because the id is later used as a
    file name, it must be a plain identifier and nothing that could escape to another directory
    (no slash, no backslash, no ".." traversal).

    Raises:
        FuzzyModelError: for anything that could be a path or is empty or too long.
    """
    # fullmatch() succeeds only when the WHOLE string is a plain identifier. ``$`` would also
    # accept a trailing newline, which must never reach a file name.
    if not ID_PATTERN.fullmatch(system_id):
        raise FuzzyModelError(f"invalid system id: {system_id!r}")
    return system_id


def list_systems(user_dir: Path) -> list[dict[str, str]]:
    """All systems as {id, name, source}; user systems first-class, examples fill the gaps.

    Returns one dict per system with:
      id     - the file stem, used as the stable identifier everywhere else
      name   - the human-readable name from the JSON, falling back to the stem
      source - SOURCE_EXAMPLE or SOURCE_USER, so callers can tell shipped from local

    Duplicate ids resolve in favour of the user directory: examples are read first
    and the user's entry overwrites them in the dict below. Returns the list sorted
    by id, so output order is independent of filesystem ordering.
    """
    found: dict[str, dict[str, str]] = {}
    for source, directory in ((SOURCE_EXAMPLE, examples_dir()), (SOURCE_USER, user_dir)):
        for path in sorted(directory.glob("*.json")) if directory.exists() else []:
            name = str(_read(path).get("name", path.stem))
            found[path.stem] = {"id": path.stem, "name": name, "source": source}
    return sorted(found.values(), key=lambda item: item["id"])


def load_document(system_id: str, user_dir: Path) -> dict[str, Any]:
    """The saved document (user copy first, then the example).

    The search path is a two-level fallback: a user may override a bundled example by
    placing a file with the same name in their own directory.

    Raises:
        FileNotFoundError: when no such system exists.
    """
    # Validate the id before touching the filesystem so a malformed id (e.g. one
    # containing "/" or "..") cannot escape the intended directory.
    check_id(system_id)
    # Fallback order: user copy shadows the shipped example. The first existing
    # file wins; we stop at the first hit rather than merging the two.
    for directory in (user_dir, examples_dir()):
        path = directory / f"{system_id}.json"
        if path.exists():
            return _read(path)
    raise FileNotFoundError(system_id)


def save_document(system_id: str, document: Mapping[str, Any], user_dir: Path) -> None:
    """Validate the document completely, then write it as the user's system ``system_id``.

    A "system" is a fuzzy inference system: a mapping of linguistic variables and rules
    that maps numeric inputs to outputs. `system_id` is its name inside the user's
    directory, used as the file name.

    The document is written to ``(user_dir / f"{system_id}.json")``. Validation comes
    first so a bad id or document never leaves a partial or corrupt file on disk.

    Raises:
        FuzzyModelError: when the id or the document is not valid; nothing is written then.
    """
    # Both checks raise FuzzyModelError, so reaching the next line means the id is a legal file name
    # and the document is a valid system. system_from_dict() is called only to validate; its
    # returned object is discarded, and the original mapping is what gets serialised.
    check_id(system_id)
    system_from_dict(document)

    # parents=True: create any missing parent of user_dir. exist_ok=True: succeed when
    # the directory is already there, so saving twice in a row is fine.
    user_dir.mkdir(parents=True, exist_ok=True)

    # The file is UTF-8 JSON, indented by 2 spaces for readability; ensure_ascii=False keeps non-
    # ASCII characters human-readable. The trailing "\n" (LF) makes the file end with a newline, as
    # POSIX tools and diff expect.
    (user_dir / f"{system_id}.json").write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf8"
    )


def _read(path: Path) -> dict[str, Any]:
    """One JSON file as a dict."""
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf8"))
    return document
