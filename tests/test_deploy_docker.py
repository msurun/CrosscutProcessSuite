"""Tests for the Docker Compose deployment under ``deploy/docker``.

They parse the compose file, Dockerfile and env template without a daemon and
guard the owner decision that the gateway stays a separate, non-root writer.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKER_DIR = REPO_ROOT / "deploy" / "docker"
COMPOSE_FILE = DOCKER_DIR / "docker-compose.yml"
DOCKERFILE = DOCKER_DIR / "Dockerfile"
ENV_EXAMPLE = DOCKER_DIR / ".env.example"
API_ENTRYPOINT = DOCKER_DIR / "api_entrypoint.py"
ADMIN_GUIDE = REPO_ROOT / "docs" / "ADMIN_GUIDE.md"

SERVICES = ("api", "runtime", "gateway")
DATA_ROOT = "/var/lib/crosscut"
GATEWAY_DIR = DATA_ROOT + "/_gateway"
ROOT_USERS = {"root", "0", "0:0", "0:root", "root:root"}
COMPOSE_VARIABLE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
)


def _compose() -> dict[str, Any]:
    """Load docker-compose.yml as a mapping."""
    loaded = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise AssertionError(f"{COMPOSE_FILE} is not a YAML mapping")
    return loaded


def _services() -> dict[str, Any]:
    """Return the compose ``services`` mapping."""
    return _compose()["services"]


def _mount_for(service_name: str, target: str) -> dict[str, Any]:
    """Return the one volume mount of a service with ``target``, else raise."""
    mounts = [m for m in _services()[service_name].get("volumes", []) if m["target"] == target]
    if len(mounts) != 1:
        raise AssertionError(f"{service_name} must mount {target} exactly once, got {mounts}")
    return mounts[0]


def _writable_targets(service_name: str) -> list[str]:
    """Return the mount targets a service may write to."""
    mounts = _services()[service_name].get("volumes", [])
    return sorted(mount["target"] for mount in mounts if not mount.get("read_only", False))


def _dockerfile_instructions(keyword: str) -> list[str]:
    """Return the arguments of every non-comment Dockerfile instruction."""
    prefix = keyword.upper() + " "
    return [
        line.strip()[len(prefix):].strip()
        for line in DOCKERFILE.read_text(encoding="utf-8").splitlines()
        if line.strip().upper().startswith(prefix)
    ]


def _env_example_values() -> dict[str, str]:
    """Parse the KEY=VALUE lines of .env.example into a mapping."""
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def _compose_variables() -> set[str]:
    """Return every ``${NAME...}`` variable referenced by the compose file."""
    return set(COMPOSE_VARIABLE.findall(COMPOSE_FILE.read_text(encoding="utf-8")))


def _secret_values() -> dict[str, str]:
    """Return env entries whose name marks a credential, with their values."""
    return {
        key: value
        for key, value in _env_example_values().items()
        if key.endswith(("_TOKEN", "_PASSWORD", "_SECRET"))
    }


def _secret_markers(text: str) -> list[str]:
    """Return the secret-looking patterns found in text."""
    return [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(text)]


def test_compose_defines_the_three_required_services() -> None:
    """The stack has exactly the api, runtime and gateway services."""
    assert set(_services()) == set(SERVICES)


def test_gateway_is_a_separate_service_with_its_own_entry_point() -> None:
    """The gateway starts its own module, not an api or runtime command."""
    command = " ".join(_services()["gateway"]["command"])
    api_command = " ".join(_services()["api"]["command"])

    assert "gateway_entrypoint.py" in command
    assert "crosscut_gateway" not in api_command


def test_every_service_runs_as_a_non_root_user() -> None:
    """No service may run as root, even if the image user changes later."""
    users = {name: str(service["user"]) for name, service in _services().items()}

    assert all(user not in ROOT_USERS for user in users.values())


def test_gateway_uses_a_different_account_from_the_api() -> None:
    """Separate service accounts keep the write authority apart from the API."""
    api_user = str(_services()["api"]["user"])
    gateway_user = str(_services()["gateway"]["user"])

    assert gateway_user != api_user
    assert gateway_user not in ROOT_USERS


def test_gateway_mounts_the_data_root_read_only() -> None:
    """The gateway may read the plant map but must not write the data root."""
    mount = _mount_for("gateway", DATA_ROOT)

    assert mount["source"] == "crosscut-data"
    assert mount["read_only"] is True


def test_gateway_can_write_only_its_own_volume_under_the_data_root() -> None:
    """The only writable gateway path is its own _gateway volume."""
    assert _writable_targets("gateway") == [GATEWAY_DIR]


def test_gateway_volume_holds_the_policy_mailbox_and_key() -> None:
    """The gateway volume carries the policy and the secrets folder it needs."""
    mount = _mount_for("gateway", GATEWAY_DIR)
    environment = _services()["gateway"]["environment"]

    assert mount["source"] == "crosscut-gateway"
    assert mount.get("read_only", False) is False
    assert GATEWAY_DIR + "/policy/write-policy.json" in environment["CROSSCUT_POLICY"]
    assert GATEWAY_DIR + "/secrets" in environment["CROSSCUT_SECRETS_DIR"]


def test_api_and_runtime_share_the_named_data_volume() -> None:
    """Both read-write services use the one crosscut-data volume."""
    data_mounts = [_mount_for(name, DATA_ROOT) for name in ("api", "runtime")]

    assert all(mount["source"] == "crosscut-data" for mount in data_mounts)
    assert all(mount.get("read_only", False) is False for mount in data_mounts)


def test_api_and_runtime_reach_the_gateway_mailbox() -> None:
    """The mailbox producers mount the same gateway volume as the gateway."""
    gateway_mounts = [_mount_for(name, GATEWAY_DIR) for name in ("api", "runtime")]

    assert all(mount["source"] == "crosscut-gateway" for mount in gateway_mounts)
    assert all(mount.get("read_only", False) is False for mount in gateway_mounts)


def test_gateway_does_not_receive_the_api_env_file() -> None:
    """Source credentials from the env file must not reach the write path."""
    assert "env_file" not in _services()["gateway"]


def test_every_service_has_a_healthcheck() -> None:
    """Compose can report the state of every process, not only a running container."""
    healthchecks = {name: service.get("healthcheck") for name, service in _services().items()}

    assert all(check and check.get("test") for check in healthchecks.values())
    assert all(check.get("interval") and check.get("retries") for check in healthchecks.values())


def test_every_service_has_a_restart_policy() -> None:
    """A crashed process is restarted without an operator typing docker start."""
    policies = {name: service.get("restart") for name, service in _services().items()}

    assert all(policy and policy != "no" for policy in policies.values())


def test_only_the_api_publishes_a_port() -> None:
    """The gateway and runtime have no inbound network listener."""
    ports = {name: service.get("ports") for name, service in _services().items()}

    assert ports["api"]
    assert not ports["runtime"]
    assert not ports["gateway"]


def test_compose_declares_both_named_volumes() -> None:
    """Stable volume names make the documented backup commands work."""
    volumes = _compose()["volumes"]

    assert set(volumes) == {"crosscut-data", "crosscut-gateway"}
    assert volumes["crosscut-data"]["name"] == "crosscut-data"
    assert volumes["crosscut-gateway"]["name"] == "crosscut-gateway"


def test_every_compose_variable_is_documented_in_the_env_example() -> None:
    """An operator can set every compose knob from the documented template."""
    assert _compose_variables() <= set(_env_example_values())


def test_env_example_has_no_secret_values() -> None:
    """The committed template carries names only, never credentials."""
    assert all(value == "" for value in _secret_values().values())


def test_deploy_files_contain_no_private_key_material() -> None:
    """No file in deploy/docker contains a private key or a known token format."""
    texts = {
        path.name: path.read_text(encoding="utf-8")
        for path in DOCKER_DIR.rglob("*")
        if path.is_file()
    }

    assert all(not _secret_markers(text) for text in texts.values())


def test_dockerfile_pins_every_base_image() -> None:
    """Every FROM names a version tag or digest, never a floating latest."""
    images = [instruction.split()[0] for instruction in _dockerfile_instructions("FROM")]

    assert images
    assert all(":" in image or "@sha256:" in image for image in images)
    assert not any(image.endswith(":latest") for image in images)
    assert all(not image.endswith(":latest") for image in images)


def test_dockerfile_ends_with_a_non_root_user() -> None:
    """The last USER instruction selects an unprivileged Crosscut account."""
    users = _dockerfile_instructions("USER")

    assert users
    assert users[-1].split()[0] not in ROOT_USERS
    assert users[-1].startswith("crosscut-")


def test_dockerfile_creates_dedicated_api_and_gateway_accounts() -> None:
    """The image defines both uids, a shared group and no login shells."""
    content = DOCKERFILE.read_text(encoding="utf-8")

    for expected in ("--uid 10001", "--uid 10002", "--gid 10000", "/usr/sbin/nologin"):
        assert expected in content, expected


def test_dockerfile_builds_the_console_and_copies_it_into_the_image() -> None:
    """The node stage runs the real frontend build and the python stage uses it."""
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert "AS frontend-build" in content
    assert "npm ci" in content and "npm run build" in content
    assert "COPY --from=frontend-build" in content
    assert "/opt/crosscut/frontend/dist" in content


def test_api_entrypoint_serves_the_console_and_mounts_the_api_under_api() -> None:
    """The browser uses /api for the backend and / for the single-page console."""
    content = API_ENTRYPOINT.read_text(encoding="utf-8")

    assert 'app.mount("/api"' in content
    assert "StaticFiles" in content
    assert "index.html" in content


def test_admin_guide_documents_the_docker_operations() -> None:
    """The operator guide covers install, upgrade, backup, logs and secrets."""
    guide = ADMIN_GUIDE.read_text(encoding="utf-8")

    for phrase in (
        "Docker Compose deployment",
        "up -d --build",
        "Backup the volumes",
        "crosscut-data",
        "crosscut-gateway",
        "Logs and health",
        "Secrets",
        "Docker secret",
    ):
        assert phrase in guide, phrase
