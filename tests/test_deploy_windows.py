"""Check the offline Windows installer contract without an installer compiler.

Text checks cover service isolation; launcher tests exercise the installed routes.
"""

import re
import runpy
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPOSITORY = Path(__file__).resolve().parents[1]
WINDOWS = REPOSITORY / "deploy" / "windows"
INSTALLER = (WINDOWS / "installer" / "crosscut.iss").read_text(encoding="utf-8")
SERVICES = (WINDOWS / "installer" / "configure-services.ps1").read_text(encoding="utf-8")
BUILD = (WINDOWS / "build-installer.ps1").read_text(encoding="utf-8")


def test_installer_registers_exactly_three_processes() -> None:
    """The installer delegates to the checked service script for all three units."""
    assert "configure-services.ps1" in INSTALLER
    assert "ResultCode <> 0" in INSTALLER
    assert re.findall(r"Register-ServiceProcess '(\w+)'", SERVICES) == [
        "CrosscutGateway", "CrosscutRuntime", "CrosscutApi"
    ]
    assert "-m crosscut_gateway" in SERVICES
    assert "-m crosscut_runtime" in SERVICES
    assert "console_entrypoint.py" in SERVICES


def test_gateway_has_a_passwordless_service_identity() -> None:
    """Gateway never shares the API or runtime Windows identity."""
    assert "$GatewayAccount = 'NT SERVICE\\CrosscutGateway'" in SERVICES
    assert "$ApiAccount = 'NT SERVICE\\CrosscutApi'" in SERVICES
    assert "$RuntimeAccount = 'NT SERVICE\\CrosscutRuntime'" in SERVICES
    assert "'ObjectName', \"NT SERVICE\\$Name\"" in SERVICES


def test_gateway_policy_and_private_folders_exclude_signers() -> None:
    """Fresh protected ACLs reserve private data for the gateway and administrators."""
    assert "SetAccessRuleProtection($true, $false)" in SERVICES
    assert "$GatewayOnly = $Trusted.Clone(); $GatewayOnly[$GatewayAccount] = 'Modify'" in SERVICES
    assert 'Set-FolderAccess "$DataRoot\\_gateway\\policy" $GatewayOnly' in SERVICES
    assert 'Set-FolderAccess "$DataRoot\\_gateway\\private" $GatewayOnly' in SERVICES
    assert "'icacls.exe' @($Child.FullName, '/reset', '/T', '/Q')" in SERVICES
    assert "Assert-DataTree" in SERVICES


def test_shared_signing_key_is_read_only_for_service_accounts() -> None:
    """HMAC signers must read the common key without modifying it."""
    assert "$Signers[$ApiAccount] = 'ReadAndExecute'" in SERVICES
    assert "$Signers[$RuntimeAccount] = 'ReadAndExecute'" in SERVICES
    assert "$Signers[$GatewayAccount] = 'ReadAndExecute'" in SERVICES
    assert 'Set-FolderAccess "$DataRoot\\_secrets" $Signers' in SERVICES


def test_recovery_distinguishes_configuration_failure_from_crash() -> None:
    """Both process and wrapper crashes recover, while invalid configuration stops."""
    assert "'AppExit', 'Default', 'Restart'" in SERVICES
    assert "'AppExit', '2', 'Exit'" in SERVICES
    assert "'AppRestartDelay', '10000'" in SERVICES
    assert "'restart/10000/restart/30000/restart/60000'" in SERVICES
    assert "'AppStopMethodConsole', '30000'" in SERVICES


def test_services_have_dependency_order_and_wait_for_commissioning() -> None:
    """Automatic services are ordered but not started with unprovisioned policy."""
    assert "'CrosscutRuntime', 'DependOnService', 'CrosscutGateway'" in SERVICES
    assert "'CrosscutApi', 'DependOnService', 'CrosscutRuntime'" in SERVICES
    assert "'SERVICE_AUTO_START'" in SERVICES
    assert "Start-Service" not in SERVICES
    assert "PrepareToInstall" in INSTALLER
    assert "WaitForStatus('Stopped'" in SERVICES


def test_uninstall_keeps_data_unless_interactively_confirmed() -> None:
    """Silent uninstall retains site data and interactive removal defaults to No."""
    assert "\n[UninstallDelete]" not in INSTALLER
    assert "and not UninstallSilent" in INSTALLER
    assert "MB_YESNO or MB_DEFBUTTON2" in INSTALLER
    assert "InitializeUninstall" in INSTALLER
    assert "Result := Result and (ResultCode = 0)" in INSTALLER
    assert "Remove-Item -LiteralPath $DataRoot" not in SERVICES


def test_build_stages_wheels_console_and_isolated_python() -> None:
    """Build produces offline dependencies and the compiled console before Inno Setup."""
    assert "'pip', 'wheel'" in BUILD
    assert "'--no-index'" in BUILD
    assert "'Lib\\site-packages', 'import site'" in BUILD
    assert "'ci', '--no-audit'" in BUILD
    assert "'run', 'build'" in BUILD
    assert '"/DPayloadDir=$Payload"' in BUILD
    assert "Get-Command $Compiler" in BUILD
    assert "Assert-Hash $PythonArchive $PythonSha256" in BUILD
    assert "Assert-Hash $NssmExecutable $NssmSha256" in BUILD


def test_payload_has_no_credentials_or_site_seed_files() -> None:
    """Only paths to keys are allowed; installer sources contain no secret values."""
    combined = INSTALLER + SERVICES + BUILD
    assert not re.search(r"(?i)(password|token|api_key|hmac_key)\s*=\s*['\"][^'\"]+", combined)
    assert "BEGIN PRIVATE KEY" not in combined
    assert "net user" not in combined.lower()
    assert "deploy\\examples" not in BUILD
    assert "'AppStdout'" in SERVICES
    assert "'AppStderr'" in SERVICES
    assert "'AppRotateOnline', '1'" in SERVICES


@pytest.fixture
def console_namespace(tmp_path: Path) -> dict[str, Any]:
    """Load the installed launcher with an isolated static build and synthetic API."""
    namespace = runpy.run_path(str(WINDOWS / "installer" / "console_entrypoint.py"))
    console_directory = tmp_path / "console"
    (console_directory / "assets").mkdir(parents=True)
    (console_directory / "index.html").write_text("console shell", encoding="utf-8")
    (console_directory / "assets" / "app.js").write_text("built asset", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("private file", encoding="utf-8")
    namespace["build_app"].__globals__["CONSOLE_DIRECTORY"] = console_directory
    namespace["build_app"].__globals__["create_app"] = lambda root: FastAPI()
    return namespace


def test_console_serves_built_assets(console_namespace: dict[str, Any], tmp_path: Path) -> None:
    """The API service exposes the installed console assets."""
    client = TestClient(console_namespace["build_app"](tmp_path))
    assert client.get("/assets/app.js").text == "built asset"


def test_console_client_routes_use_the_shell(
    console_namespace: dict[str, Any], tmp_path: Path
) -> None:
    """An SPA route is served from index.html."""
    client = TestClient(console_namespace["build_app"](tmp_path))
    assert client.get("/controllers/example").text == "console shell"


def test_console_cannot_read_outside_the_build(
    console_namespace: dict[str, Any], tmp_path: Path
) -> None:
    """Encoded parent traversal cannot expose adjacent private files."""
    client = TestClient(console_namespace["build_app"](tmp_path))
    assert client.get("/%2e%2e/outside.txt").text == "console shell"


def test_api_routes_do_not_fall_through_to_the_console(
    console_namespace: dict[str, Any], tmp_path: Path
) -> None:
    """The API remains a separate mount instead of an SPA fallback."""
    client = TestClient(console_namespace["build_app"](tmp_path))
    assert client.get("/api/missing").status_code == 404
