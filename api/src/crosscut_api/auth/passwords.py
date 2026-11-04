"""Password hashing and verification logic for local authentication."""
from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any

# Constants required by the JSON schema and the scrypt algorithm.
# MAXMEM is 64 MiB.
# DKLEN is the derived key length in bytes (32).
# SALT_BYTES is 16 bytes for uniqueness.
# MIN_PASSWORD_LENGTH is 12 characters.
ALG = "scrypt"
DKLEN = 32
SALT_BYTES = 16
MAXMEM = 64 * 1024 * 1024
MIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True)
class ScryptParams:
    """
    Parameters for the scrypt password derivation function.

    n: CPU/memory cost parameter (power of 2).
    r: Scrypt block size parameter.
    p: Scrypt p parameter.
    """
    n: int = 32768
    r: int = 8
    p: int = 1


def hash_password(password: str, params: ScryptParams) -> dict[str, Any]:
    """Hashes a password using scrypt with provided parameters."""
    salt = os.urandom(SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=params.n,
        r=params.r,
        p=params.p,
        dklen=DKLEN,
        maxmem=MAXMEM,
    )

    return {
        "alg": ALG,
        "n": params.n,
        "r": params.r,
        "p": params.p,
        "salt_b64": _encode_base64(salt),
        "hash_b64": _encode_base64(derived),
    }


def verify_password(password: str, record: dict[str, Any]) -> bool:
    """Verifies a password against a stored record; returns False on any error."""
    try:
        if record.get("alg") != ALG:
            return False

        salt = base64.b64decode(record["salt_b64"])
        expected_hash = base64.b64decode(record["hash_b64"])

        computed_hash = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=record["n"],
            r=record["r"],
            p=record["p"],
            dklen=DKLEN,
            maxmem=MAXMEM,
        )
        return hmac.compare_digest(computed_hash, expected_hash)
    except (KeyError, TypeError, ValueError, binascii.Error):
        return False


def dummy_verify(password: str, params: ScryptParams) -> None:
    """Burns execution time to prevent username enumeration."""
    record = _get_dummy_record(params)
    verify_password(password, record)


def password_problem(password: str, min_length: int = MIN_PASSWORD_LENGTH) -> str | None:
    """Returns a validation error message if the password is unsuitable, else None."""
    if not password.strip():
        return "Password cannot be empty or just whitespace."

    if len(password) < min_length:
        return f"Password must be at least {min_length} characters long."

    return None


@functools.lru_cache(maxsize=4)
def _get_dummy_record(params: ScryptParams) -> dict[str, Any]:
    """Generates a cached, throwaway password record for timing attacks protection."""
    # A fixed, arbitrary string used to burn time during dummy verifications.
    dummy_password = "this_is_a_fixed_dummy_password_for_timing_mitigation"
    return hash_password(dummy_password, params)


def _encode_base64(data: bytes) -> str:
    """Converts bytes to a standard base64 string."""
    return base64.b64encode(data).decode("ascii")
