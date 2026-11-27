"""Promote dataset loop definitions and knowledge into the site catalogue.

Only catalogue-compatible fields are copied; legacy project files stay untouched.
"""

from copy import deepcopy
from pathlib import Path
from typing import Any

from crosscut_connectors.site import SiteError, validate_site
from crosscut_loops.project_edit import KNOWLEDGE_KEYS, apply_knowledge

from crosscut_api.site_version_routes import store_draft, working_site

TAG_ROLES = ("pv", "sp", "out", "mode")  # Controller signal roles, each holding a tag id.
TAG_METADATA = ("unit", "description")
SITE_SCHEMA_VERSION = 1


def catalogue_of(root: Path) -> dict[str, Any]:
    """Read the catalogue, or return the minimal valid new-site document."""
    working = working_site(root)
    if working is not None:
        return working
    return {"schema_version": SITE_SCHEMA_VERSION, "site": {"name": "Site"},
            "tags": [], "loops": []}


def promote_loop(
    catalogue: dict[str, Any], entry: dict[str, Any], tags: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return a catalogue copy containing the dataset loop and its missing tags."""
    document = deepcopy(catalogue)
    name = str(entry.get("name") or entry.get("id", ""))
    loop = {"id": name, **{role: entry[role] for role in TAG_ROLES if entry.get(role)}}
    document.setdefault("loops", []).append(loop)
    _add_missing_tags(document, loop, tags)
    # Project-only fields cannot pass the site schema. Copy the shared knowledge contract.
    knowledge = {key: entry[key] for key in KNOWLEDGE_KEYS if key in entry}
    return apply_knowledge(document, name, knowledge, tags)


def _add_missing_tags(
    document: dict[str, Any], loop: dict[str, Any], tags: list[dict[str, Any]]
) -> None:
    """Add signal identities without replacing any established site metadata."""
    known_ids = {row["id"] for row in document["tags"]}
    dataset_tags = {row["id"]: row for row in tags}
    for role in TAG_ROLES:
        tag_id = loop.get(role)
        if tag_id and tag_id not in known_ids:
            metadata = dataset_tags.get(tag_id, {})
            row = {key: metadata[key] for key in TAG_METADATA if key in metadata}
            document["tags"].append({"id": tag_id, **row})
            known_ids.add(tag_id)


def save_catalogue(root: Path, document: dict[str, Any], actor: str) -> None:
    """Validate and store as the site draft; SiteError describes any invalid catalogue fields.

    Raises HTTPException 409 (``busy``/``pending_exists``) from the draft store.
    """
    problems = validate_site(document)
    if problems:
        raise SiteError("; ".join(problems))
    store_draft(root, document, actor)


def migration_reason(catalogue: dict[str, Any], entry: dict[str, Any]) -> str:
    """Explain why an entry should stay untouched, or return an empty reason."""
    name = str(entry.get("name") or entry.get("id", ""))
    if not name:
        return "Loop has no name or id"
    if any(row.get("name", row.get("id")) == name for row in catalogue.get("loops", [])):
        return "Loop already exists in the site catalogue"
    if not any(entry.get(key) is not None for key in KNOWLEDGE_KEYS):
        return "Loop has no knowledge"
    return ""
