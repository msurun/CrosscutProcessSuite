"""What a configuration backup contains and what it leaves out (issue #167).

One place states the scope: configuration, models, policies, users and the audit logs are in;
history (Parquet datasets, runtime records), caches, queues and every secret are out. The backup
and restore code only asks this module whether a path belongs to the backup.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

KIND_CONFIG = "config"  # replaced on restore
KIND_EVIDENCE = "evidence"  # audit logs: stored and verified, never replaced on restore

# Folders restored as a whole (files below them that match no exclusion rule).
CONFIG_TREES = (
    "_site",
    "_anomaly",
    "_softsensor",
    "_fuzzy",
    "_supervisor",
    "_trends",
    "_gateway/policy",
)
CONFIG_FILES = (
    "plant-map.json",
    "_auth/users.json",
    "_auth/roles.json",
    "_auth/config.json",
    "_gateway/policy-draft.json",
)
# Append-only hash chains: an older copy must never overwrite the live chain.
EVIDENCE_FILES = ("_auth/auth-audit.jsonl", "_gateway/audit.jsonl")
EXCLUDED_SUFFIXES = (".parquet", ".tmp", ".lock", ".pyc", ".cache")

# Shown in the manifest, the GUI and the admin guide so nobody expects them in the backup.
EXCLUDED_NOTES = (
    "datasets: every <root>/<dataset>/ folder (Parquet history stays in the source historian)",
    "_runtime: KPI history, equipment events, shelved list",
    "_advisory: advisory logs",
    "_uploads: uploaded import files",
    "_gateway/state.json, inbox, outbox, rejected: live gateway queues",
    "_tuning: tuning proposals in flight",
    "_secrets and the OS secret store: keys and passwords are never exported",
    "_backup: earlier backups and safety copies",
)


def is_excluded(relative: str) -> bool:
    """True for a cache, temporary or history file that must never enter a backup."""
    path = PurePosixPath(relative)
    return path.suffix in EXCLUDED_SUFFIXES or "__pycache__" in path.parts


def kind_of(relative: str) -> str | None:
    """KIND_CONFIG or KIND_EVIDENCE when the relative path belongs to a backup, else None."""
    if is_excluded(relative):
        return None
    if relative in EVIDENCE_FILES:
        return KIND_EVIDENCE
    if relative in CONFIG_FILES or any(relative.startswith(f"{tree}/") for tree in CONFIG_TREES):
        return KIND_CONFIG
    return None


def is_safe_path(relative: str) -> bool:
    """True for a plain relative POSIX path with no parent, drive, empty or backslash part."""
    if not relative or "\\" in relative or ":" in relative or relative.startswith("/"):
        return False
    return all(part not in ("", ".", "..") for part in relative.split("/"))


def _tree_files(root: Path, tree: str) -> list[str]:
    """Relative paths of the regular files below one scope folder."""
    base = root / tree
    if not base.is_dir():
        return []
    return [
        p.relative_to(root).as_posix()
        for p in base.rglob("*")
        if p.is_file() and not p.is_symlink()
    ]


def scope_files(root: Path) -> dict[str, str]:
    """Every file of the data root that belongs to a backup, mapped to its kind; sorted by path."""
    found = [rel for tree in CONFIG_TREES for rel in _tree_files(root, tree)]
    found += [rel for rel in (*CONFIG_FILES, *EVIDENCE_FILES) if (root / rel).is_file()]
    kinds = {rel: kind_of(rel) for rel in found}
    return {rel: kind for rel, kind in sorted(kinds.items()) if kind is not None}
