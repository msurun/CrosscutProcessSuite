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

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SOURCE_EXAMPLE = "example"
SOURCE_USER = "user"


def examples_dir() -> Path:
    """Directory of the bundled example systems (next to the package in the repository)."""
    return Path(__file__).resolve().parents[2] / "examples"


def check_id(system_id: str) -> str:
    """The id when it is a plain identifier.

    Raises:
        FuzzyModelError: for anything that could be a path or is empty or too long.
    """
    if not ID_PATTERN.match(system_id):
        raise FuzzyModelError(f"invalid system id: {system_id!r}")
    return system_id


def list_systems(user_dir: Path) -> list[dict[str, str]]:
    """All systems as {id, name, source}; user systems first-class, examples fill the gaps."""
    found: dict[str, dict[str, str]] = {}
    for source, directory in ((SOURCE_EXAMPLE, examples_dir()), (SOURCE_USER, user_dir)):
        for path in sorted(directory.glob("*.json")) if directory.exists() else []:
            name = str(_read(path).get("name", path.stem))
            found[path.stem] = {"id": path.stem, "name": name, "source": source}
    return sorted(found.values(), key=lambda item: item["id"])


def load_document(system_id: str, user_dir: Path) -> dict[str, Any]:
    """The saved document (user copy first, then the example).

    Raises:
        FileNotFoundError: when no such system exists.
    """
    check_id(system_id)
    for directory in (user_dir, examples_dir()):
        path = directory / f"{system_id}.json"
        if path.exists():
            return _read(path)
    raise FileNotFoundError(system_id)


def save_document(system_id: str, document: Mapping[str, Any], user_dir: Path) -> None:
    """Validate the document completely, then write it as the user's system ``system_id``.

    Raises:
        FuzzyModelError: when the id or the document is not valid; nothing is written then.
    """
    check_id(system_id)
    system_from_dict(document)
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / f"{system_id}.json").write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf8"
    )


def _read(path: Path) -> dict[str, Any]:
    """One JSON file as a dict."""
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf8"))
    return document
