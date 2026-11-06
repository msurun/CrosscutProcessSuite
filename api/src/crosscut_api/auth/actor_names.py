"""Canonical comparison form of actor names, mirroring the gateway's normalize_actor.

The API cannot import the gateway package, so the algorithm is repeated here. Use
``same_actor`` for every proposer, approver or author comparison; audit records keep the
spelling as claimed.
"""

from __future__ import annotations

import unicodedata


def normalize_actor(name: str) -> str:
    """Return the canonical comparison form of an actor name.

    NFKC-normalised, whitespace collapsed and stripped, case folded, then re-normalised.

    Args:
        name: The actor name as claimed.

    Returns:
        The name in canonical comparison form.
    """
    folded = " ".join(unicodedata.normalize("NFKC", name).split()).casefold()
    return unicodedata.normalize("NFKC", folded)


def same_actor(first: str, second: str) -> bool:
    """Return True when two actor names are the same person after normalisation."""
    return normalize_actor(first) == normalize_actor(second)
