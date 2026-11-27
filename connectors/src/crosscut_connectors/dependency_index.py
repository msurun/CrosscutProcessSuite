"""Dependency index: what each config, model and job was built on, and what went stale (#166).

``<root>/_site/dependencies.json`` keeps, per dependent (``job:<id>``, ``anomaly:<id>``,
``softsensor:<id>``, ``ident_model:<id>``), the tags it uses with the fingerprint and catalogue
version it was built on. Publishing a catalogue version runs :func:`on_publish`, which baselines
dependents that have no record against the PREVIOUS catalogue and records which ones are now
stale and why. :func:`stale_reasons` is the same comparison against any catalogue, so the runtime
and the API never disagree. A stale dependent is cleared by relearning or re-registering it
(:func:`register`) or by an engineer's :func:`confirm`.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crosscut_connectors.site import SITE_FOLDER
from crosscut_connectors.site_fingerprint import (
    controller_tag_ids,
    diff_fingerprints,
    job_tag_ids,
    tag_fingerprints,
)

Doc = dict[str, Any]
INDEX_FILE = "dependencies.json"
LOCK_FILE = "dependencies.lock"
LOCK_TRIES = 40
LOCK_WAIT_S = 0.05
MODEL_KINDS = ("anomaly", "softsensor", "ident_model")


class DependencyError(ValueError):
    """The dependent does not exist or the index cannot be written."""


def index_path(root: Path) -> Path:
    """Where the index lives."""
    return root / SITE_FOLDER / INDEX_FILE


def empty_index() -> Doc:
    """A new index with no dependents."""
    return {"schema_version": 1, "items": {}, "stale": {}}


def load_index(root: Path) -> Doc:
    """The stored index; an absent or unreadable file is an empty index."""
    try:
        value = json.loads(index_path(root).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return empty_index()
    return value if isinstance(value, dict) and "items" in value else empty_index()


def _locked_write(root: Path, index: Doc) -> None:
    """Write the index atomically while holding an exclusive lock file."""
    folder = root / SITE_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / LOCK_FILE
    for attempt in range(LOCK_TRIES):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            if attempt == LOCK_TRIES - 1:
                raise DependencyError("the dependency index is busy") from None
            time.sleep(LOCK_WAIT_S)
    try:
        handle, temp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(index, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temp, index_path(root))
    finally:
        lock.unlink(missing_ok=True)


def _read(path: Path) -> Doc:
    """A JSON object from a file, empty when absent or unreadable."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _ident_tags(names: list[str], site: Mapping[str, Any]) -> set[str]:
    """Tags behind the channel names of an identified model (tag ids or controller variables)."""
    tag_ids = {tag["id"] for tag in site.get("tags", [])}
    variables = {
        v["id"]: (c, v) for c in site.get("controllers", []) for v in c.get("variables", [])
    }
    tags = {name for name in names if name in tag_ids}
    for name in names:
        if name in variables:
            controller, variable = variables[name]
            one = {**controller, "variables": [variable]}
            tags |= controller_tag_ids(one, site.get("loops", []))
    return tags


def _config_dependents(root: Path, folder: str, kind: str) -> Doc:
    """Dependents of one config folder (``_anomaly`` or ``_softsensor``): configs without a dot."""
    found: Doc = {}
    for path in sorted((root / folder).glob("*.json")):
        if "." in path.stem:
            continue
        doc = _read(path)
        names = list(doc.get("tags", [])) if kind == "anomaly" else (
            [doc["target_tag"], *doc.get("input_tags", [])] if "target_tag" in doc else []
        )
        found[f"{kind}:{path.stem}"] = {"kind": kind, "id": path.stem, "tags": sorted(set(names))}
    return found


def scan_dependents(root: Path, site: Mapping[str, Any]) -> Doc:
    """Every dependent now on disk with the tags it resolves to under ``site``."""
    found: Doc = {}
    for job in _read(root / "_runtime" / "jobs.json").get("jobs", []):
        tags = sorted(job_tag_ids(job, site))
        found[f"job:{job['id']}"] = {"kind": "job", "id": job["id"], "tags": tags}
    found |= _config_dependents(root, "_anomaly", "anomaly")
    found |= _config_dependents(root, "_softsensor", "softsensor")
    for model in sorted((root / "_mpc" / "models").glob("*/model.json")):
        payload = _read(model)
        names = [*payload.get("input_names", []), *payload.get("cv_names", [])]
        found[f"ident_model:{model.parent.name}"] = {
            "kind": "ident_model", "id": model.parent.name,
            "tags": sorted(_ident_tags(names, site)),
        }
    return found


def baseline_entry(
    dependent: Mapping[str, Any], site: Mapping[str, Any], version: int | None
) -> Doc:
    """A baseline record: the dependent's tags with their fingerprints in ``site``."""
    prints = tag_fingerprints(site)
    tags = [t for t in dependent["tags"] if t in prints]
    return {
        "kind": dependent["kind"], "id": dependent["id"], "tags": tags,
        "catalogue_version": version, "fingerprints": {t: prints[t] for t in tags},
        "registered_utc": datetime.now(UTC).isoformat(timespec="seconds"), "confirmed": None,
    }


def register(
    root: Path, site: Mapping[str, Any], dependent: Mapping[str, Any], version: int | None
) -> Doc:
    """(Re)baseline one dependent on ``site``: a relearn, a redeploy or a fresh config."""
    key = f"{dependent['kind']}:{dependent['id']}"
    index = load_index(root)
    index["items"][key] = baseline_entry(dependent, site, version)
    index["stale"].pop(key, None)
    _locked_write(root, index)
    return index["items"][key]


def reasons_of(
    entry: Mapping[str, Any], site: Mapping[str, Any], used_now: Any = None
) -> list[dict[str, str]]:
    """Why a baseline record is stale against ``site`` (empty when it is not)."""
    return diff_fingerprints(entry["fingerprints"], tag_fingerprints(site), used_now)


def stale_reasons(
    root: Path, site: Mapping[str, Any], key: str, used_now: Any = None
) -> list[dict[str, str]]:
    """Reasons the dependent ``key`` is stale; empty when it is fine or has no record."""
    entry = load_index(root)["items"].get(key)
    return [] if entry is None else reasons_of(entry, site, used_now)


def on_publish(
    root: Path, previous: Mapping[str, Any] | None, site: Mapping[str, Any], version: int
) -> Doc:
    """After publishing ``version``: baseline unrecorded dependents on the previous catalogue.

    Then record which dependents are now stale and why; returns that stale map.
    """
    index = load_index(root)
    if previous is not None:
        for key, dependent in scan_dependents(root, previous).items():
            before = (version - 1) or None
            index["items"].setdefault(key, baseline_entry(dependent, previous, before))
    current = scan_dependents(root, site)
    stale: Doc = {}
    for key, entry in index["items"].items():
        used = current.get(key, {}).get("tags") if entry["kind"] == "job" else None
        reasons = reasons_of(entry, site, used)
        if reasons:
            since = index["stale"].get(key, {}).get("since_version", version)
            stale[key] = {"since_version": since, "reasons": reasons}
    index["stale"] = stale
    _locked_write(root, index)
    return stale


def _view(key: str, entry: Mapping[str, Any], reasons: list[Any], since: Any, exists: bool) -> Doc:
    """The client view of one stale dependent."""
    model = entry["kind"] in MODEL_KINDS
    actions = ["relearn", "reconfirm"] if model else ["edit_config", "reconfirm"]
    return {
        "key": key, "kind": entry["kind"], "id": entry["id"], "reasons": reasons,
        "built_on_version": entry.get("catalogue_version"), "stale_since_version": since,
        "needs_relearn": model, "actions": actions if exists else ["edit_config"],
    }


def stale_items(root: Path, site: Mapping[str, Any]) -> list[Doc]:
    """Every stale dependent now, with reasons and the engineer's possible actions."""
    index = load_index(root)
    current = scan_dependents(root, site)
    items = []
    for key, entry in sorted(index["items"].items()):
        used = current.get(key, {}).get("tags") if entry["kind"] == "job" else None
        reasons = reasons_of(entry, site, used)
        if reasons:
            since = index["stale"].get(key, {}).get("since_version")
            items.append(_view(key, entry, reasons, since, key in current))
    return items


def confirm(
    root: Path, site: Mapping[str, Any], key: str, version: int | None, by: str, note: str
) -> Doc:
    """An engineer accepts the catalogue as it is now: rebaseline ``key``, record who and why."""
    dependent = scan_dependents(root, site).get(key)
    if dependent is None:
        raise DependencyError(f"unknown dependent {key!r}")
    index = load_index(root)
    entry = baseline_entry(dependent, site, version)
    entry["confirmed"] = {
        "by": by, "note": note, "version": version,
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    index["items"][key] = entry
    index["stale"].pop(key, None)
    _locked_write(root, index)
    return entry


class DependencyView:
    """One pass over the index for the runtime: fingerprints and index are read once per pass.

    A dependent without a stored record (its job predates the index) is baselined in ``memory``
    on first sight, so the runtime never writes the index and a restart cannot hide a change that
    ``on_publish`` already recorded.
    """

    def __init__(self, root: Path, site: Mapping[str, Any], memory: Doc | None = None) -> None:
        """Read the index and fingerprint the catalogue once."""
        self._site, self._index = site, load_index(root)
        self._memory = memory if memory is not None else {}
        self._current = tag_fingerprints(site)

    def reasons(self, key: str, dependent: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
        """Reasons ``key`` is stale; ``dependent`` (a job's tags now) enables rebound detection."""
        entry = self._index["items"].get(key) or self._memory.get(key)
        if entry is None and dependent is not None:
            entry = self._memory.setdefault(key, baseline_entry(dependent, self._site, None))
        if entry is None:
            return []
        used = dependent["tags"] if dependent and entry["kind"] == "job" else None
        return diff_fingerprints(entry["fingerprints"], self._current, used)
