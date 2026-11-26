"""Exercise source credentials in the secret store and the PI connector's use of it (#208).

Nothing here talks to the real OS keyring: keyring is always a fake in these tests.
"""

import sys
import types

import pytest
from crosscut_connectors.base import SourceConnectionError
from crosscut_connectors.piwebapi_connector import _headers
from crosscut_connectors.secret_store import (
    KeyringStore,
    MemoryStore,
    SecretStoreError,
    check_ref,
    default_store,
    ref_for_source,
    use_store,
)


@pytest.fixture
def saved_store():
    """Restore the module default store after a test has swapped it."""
    previous = default_store()
    yield
    use_store(previous)


def test_check_ref_accepts_a_plain_name():
    """A source-style reference name passes validation unchanged."""
    assert check_ref("source.pi1") == "source.pi1"


@pytest.mark.parametrize("bad_ref", ["", "a/b", "x" * 65, "has space"])
def test_check_ref_rejects_unsafe_names(bad_ref):
    """Empty, path-like, too long and spaced references raise ValueError."""
    with pytest.raises(ValueError, match="credential_ref"):
        check_ref(bad_ref)


def test_ref_for_source_prefixes_the_source_id():
    """The default reference of a source is ``source.<id>``."""
    assert ref_for_source("pi1") == "source.pi1"


def test_memory_store_round_trips_a_secret():
    """A stored value is returned by the same reference."""
    store = MemoryStore()
    store.set("pi1", "reader:synthetic")
    assert store.get("pi1") == "reader:synthetic"


def test_memory_store_get_of_missing_ref_returns_none():
    """Reading a reference that was never stored yields None."""
    assert MemoryStore().get("pi1") is None


def test_memory_store_refuses_an_empty_value():
    """Storing an empty secret is a configuration mistake and raises ValueError."""
    with pytest.raises(ValueError, match="empty secret"):
        MemoryStore().set("pi1", "")


def test_memory_store_delete_of_missing_ref_is_ok():
    """Deleting a reference that is gone is not an error."""
    MemoryStore().delete("pi1")


class FakeKeyringErrors:
    """Stand-in for ``keyring.errors`` with the exception classes the store catches."""

    class KeyringError(Exception):
        """Base of every keyring failure."""

    class PasswordDeleteError(KeyringError):
        """Raised when deleting a missing password."""


class FakeKeyring:
    """Records password calls and optionally raises a chosen error."""

    def __init__(self, error_factory=None):
        self.error_factory = error_factory
        self.calls = []

    def get_password(self, service, ref):
        """Record the call and return a stored value or raise."""
        self.calls.append(("get", service, ref))
        if self.error_factory:
            raise self.error_factory()
        return "stored-secret"

    def set_password(self, service, ref, value):
        """Record the call and raise if configured; value is never read back."""
        self.calls.append(("set", service, ref))
        if self.error_factory:
            raise self.error_factory()

    def delete_password(self, service, ref):
        """Record the call and raise if configured."""
        self.calls.append(("delete", service, ref))
        if self.error_factory:
            raise self.error_factory()


class FailingStore:
    """Secret store whose every read is refused, used to test PI header errors."""

    def get(self, ref):
        """Simulate a store that refuses every read."""
        raise SecretStoreError("secret store refused the read: KeyringError")

    def set(self, ref, value):
        """Not used by these tests; the protocol requires the method to exist."""

    def delete(self, ref):
        """Not used by these tests; the protocol requires the method to exist."""


def install_fake_keyring(monkeypatch, fake):
    """Point ``_keyring`` at the fake module and the fake errors namespace."""
    fake_module = types.ModuleType("keyring")
    fake_module.get_password = fake.get_password
    fake_module.set_password = fake.set_password
    fake_module.delete_password = fake.delete_password
    errors_module = types.ModuleType("keyring.errors")
    for name in ("KeyringError", "PasswordDeleteError"):
        setattr(errors_module, name, getattr(FakeKeyringErrors, name))
    fake_module.errors = errors_module
    monkeypatch.setattr(
        "crosscut_connectors.secret_store._keyring",
        lambda: (fake_module, errors_module),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_module)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors_module)


def test_keyring_store_get_records_service_and_ref(monkeypatch):
    """A read reaches the OS store with the constant service name."""
    fake = FakeKeyring()
    install_fake_keyring(monkeypatch, fake)
    assert KeyringStore().get("pi1") == "stored-secret"
    assert fake.calls == [("get", "crosscut-process-suite", "pi1")]


def test_keyring_store_maps_failures_to_secret_store_error(monkeypatch):
    """A keyring failure becomes SecretStoreError naming only the action and error type."""
    fake = FakeKeyring(error_factory=FakeKeyringErrors.KeyringError)
    install_fake_keyring(monkeypatch, fake)
    with pytest.raises(SecretStoreError) as raised:
        KeyringStore().set("pi1", "reader:synthetic")
    message = str(raised.value)
    assert "write" in message
    assert "KeyringError" in message
    assert "reader:synthetic" not in message


def test_keyring_store_delete_of_missing_password_is_ok(monkeypatch):
    """PasswordDeleteError is the missing case and must not surface as an error."""
    fake = FakeKeyring(error_factory=FakeKeyringErrors.PasswordDeleteError)
    install_fake_keyring(monkeypatch, fake)
    KeyringStore().delete("pi1")


def test_use_store_returns_the_previous_store(saved_store):
    """Swapping the default returns the store that was in place before."""
    memory = MemoryStore()
    previous = use_store(memory)
    assert default_store() is memory
    assert previous is not memory


def test_pi_headers_resolves_basic_credential_ref(saved_store):
    """``credential_ref`` resolves through the store and base64-encodes a basic value."""
    store = MemoryStore()
    store.set("pi1", "reader:synthetic")
    use_store(store)
    headers = _headers({"kind": "basic", "credential_ref": "pi1"})
    assert headers["Authorization"] == "Basic cmVhZGVyOnN5bnRoZXRpYw=="


def test_pi_headers_resolves_bearer_credential_ref(saved_store):
    """``credential_ref`` resolves through the store as a plain bearer token."""
    store = MemoryStore()
    store.set("pi1", "synthetic-token")
    use_store(store)
    headers = _headers({"kind": "bearer", "credential_ref": "pi1"})
    assert headers["Authorization"] == "Bearer synthetic-token"


def test_pi_headers_missing_secret_raises_source_connection_error(saved_store):
    """An unset reference is a clear configuration error at runtime."""
    use_store(MemoryStore())
    with pytest.raises(SourceConnectionError, match="credential_ref"):
        _headers({"kind": "basic", "credential_ref": "pi1"})


def test_pi_headers_store_error_hides_the_secret(saved_store):
    """A failing store is reported without leaking any stored value."""
    use_store(FailingStore())
    with pytest.raises(SourceConnectionError) as raised:
        _headers({"kind": "basic", "credential_ref": "pi1"})
    message = str(raised.value)
    assert "refused the read" in message
    assert "synthetic" not in message


def test_pi_headers_still_resolves_credential_env(monkeypatch):
    """``credential_env`` keeps reading the environment without touching a store."""
    monkeypatch.setenv("SYNTHETIC_PI_TOKEN", "synthetic-token")
    headers = _headers({"kind": "bearer", "credential_env": "SYNTHETIC_PI_TOKEN"})
    assert headers["Authorization"] == "Bearer synthetic-token"


def test_pi_headers_rejects_unknown_auth_keys():
    """Inline secrets or unknown keys in ``auth`` raise ValueError."""
    with pytest.raises(ValueError, match="remove inline credentials"):
        _headers({"kind": "basic", "credential_env": "PI", "password": "synthetic"})
