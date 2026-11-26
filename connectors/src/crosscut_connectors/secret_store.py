"""Source credentials in the operating-system secret store, never in the site catalogue (#208).

PRODUCT 3.1: a source names its secret by reference (``auth.credential_ref``); the value lives in
the OS store (Windows Credential Manager, macOS Keychain, Secret Service on Linux) through the
``keyring`` library under one service name. Nothing here logs, returns or echoes a secret value.
"""

from __future__ import annotations

import re
from types import ModuleType
from typing import Protocol

SERVICE = "crosscut-process-suite"
# A reference is a plain name so it can never smuggle a path, URL or value into the catalogue.
REF_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class SecretStoreError(Exception):
    """The OS secret store is unavailable or refused the operation (no value in the message)."""


class SecretStore(Protocol):
    """Where source credentials are kept; tests pass an in-memory store."""

    def get(self, ref: str) -> str | None:
        """The secret of ``ref``, or None when none is stored."""
        ...

    def set(self, ref: str, value: str) -> None:
        """Store or replace the secret of ``ref``."""
        ...

    def delete(self, ref: str) -> None:
        """Remove the secret of ``ref``; a missing one is not an error."""
        ...


def check_ref(ref: str) -> str:
    """Return ``ref`` when it is a valid reference name; ValueError otherwise."""
    if not REF_PATTERN.fullmatch(ref):
        raise ValueError("credential_ref must be 1-64 letters, digits, '.', '_' or '-'")
    return ref


def ref_for_source(source_id: str) -> str:
    """The default reference of a source's credential: ``source.<id>``."""
    return check_ref(f"source.{source_id}")


class KeyringStore:
    """The OS secret store through ``keyring``; every failure becomes SecretStoreError."""

    def get(self, ref: str) -> str | None:
        """Read one secret from the OS store."""
        keyring, errors = _keyring()
        try:
            value = keyring.get_password(SERVICE, check_ref(ref))
            return None if value is None else str(value)
        except errors.KeyringError as error:
            raise SecretStoreError(_refused("read", error)) from None

    def set(self, ref: str, value: str) -> None:
        """Write one secret to the OS store; an empty value is refused."""
        if not value:
            raise ValueError("an empty secret is not stored")
        keyring, errors = _keyring()
        try:
            keyring.set_password(SERVICE, check_ref(ref), value)
        except errors.KeyringError as error:
            raise SecretStoreError(_refused("write", error)) from None

    def delete(self, ref: str) -> None:
        """Delete one secret from the OS store, ignoring a missing one."""
        keyring, errors = _keyring()
        try:
            keyring.delete_password(SERVICE, check_ref(ref))
        except errors.PasswordDeleteError:
            return
        except errors.KeyringError as error:
            raise SecretStoreError(_refused("delete", error)) from None


def _refused(action: str, error: Exception) -> str:
    """Error text naming the action and the error type only; backend messages may echo input."""
    return f"secret store refused the {action}: {type(error).__name__}"


def _keyring() -> tuple[ModuleType, ModuleType]:
    """Import keyring lazily so modules that never touch secrets do not need an OS backend."""
    try:
        import keyring
        import keyring.errors
    except ImportError as error:
        raise SecretStoreError("the keyring package is not installed") from error
    return keyring, keyring.errors


class MemoryStore:
    """In-memory secret store for tests and for runs without an OS store."""

    def __init__(self) -> None:
        """Start empty."""
        self._values: dict[str, str] = {}

    def get(self, ref: str) -> str | None:
        """The stored secret or None."""
        return self._values.get(check_ref(ref))

    def set(self, ref: str, value: str) -> None:
        """Store a non-empty secret."""
        if not value:
            raise ValueError("an empty secret is not stored")
        self._values[check_ref(ref)] = value

    def delete(self, ref: str) -> None:
        """Forget a secret."""
        self._values.pop(check_ref(ref), None)


_default: SecretStore = KeyringStore()


def default_store() -> SecretStore:
    """The store connectors use when none is passed (the OS store unless replaced)."""
    return _default


def use_store(store: SecretStore) -> SecretStore:
    """Replace the default store (tests, deployments without an OS store); returns the old one."""
    global _default
    previous, _default = _default, store
    return previous
