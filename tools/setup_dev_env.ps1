# Sets up the Windows dev environment for Crosscut: vswhere on PATH (needed by tools\msvc_env.cmd),
# a portable VS Code workspace settings file (no machine paths: it uses ${workspaceFolder}) and a
# check of every tool. Idempotent. Run: powershell -File tools\setup_dev_env.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$installer = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer"

function Add-UserPath([string]$dir) {
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($user -split ";") -notcontains $dir) {
        [Environment]::SetEnvironmentVariable("Path", "$user;$dir".Trim(";"), "User")
        Write-Host "PATH (user) += $dir"
    }
}

if (Test-Path $installer) { Add-UserPath $installer }

# VS Code: terminal profile with the MSVC environment, and the repo venv as the Python interpreter.
$vscodeDir = Join-Path $root ".vscode"
New-Item -ItemType Directory -Force $vscodeDir | Out-Null
$settingsPath = Join-Path $vscodeDir "settings.json"
$settings = if (Test-Path $settingsPath) { Get-Content $settingsPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
$profile = [pscustomobject]@{ path = "cmd.exe"; args = @("/k", '${workspaceFolder}\tools\msvc_env.cmd'); icon = "tools" }
$settings | Add-Member -NotePropertyName "terminal.integrated.profiles.windows" -NotePropertyValue ([pscustomobject]@{ "MSVC x64" = $profile }) -Force
$settings | Add-Member -NotePropertyName "python.defaultInterpreterPath" -NotePropertyValue '${workspaceFolder}/.venv/Scripts/python.exe' -Force
$settings | ConvertTo-Json -Depth 6 | Set-Content $settingsPath -Encoding utf8
Write-Host "wrote .vscode\settings.json (portable)"

# Verify in the environment a freshly started VS Code will see.
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
foreach ($tool in "node", "npm", "cmake", "ninja", "winget") {
    $found = Get-Command $tool -ErrorAction SilentlyContinue
    Write-Host ("{0,-7} {1}" -f $tool, $(if ($found) { "OK" } else { "MISSING" }))
}
cmd /c "`"$PSScriptRoot\msvc_env.cmd`" && where cl >nul 2>&1"
Write-Host ("cl      " + $(if ($LASTEXITCODE -eq 0) { "OK (via tools\msvc_env.cmd)" } else { "MISSING" }))
Write-Host ("venv    " + $(if (Test-Path (Join-Path $root ".venv\Scripts\python.exe")) { "OK" } else { "MISSING" }))
