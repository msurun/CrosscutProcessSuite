# Build an offline payload from reviewed upstream runtime and wrapper archives.
# All staging stays below deploy/windows/build; no installer compiler is needed on CI.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PythonArchive,
    [Parameter(Mandatory)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$PythonSha256,
    [Parameter(Mandatory)][string]$NssmExecutable,
    [Parameter(Mandatory)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$NssmSha256,
    [Parameter(Mandatory)][string]$NssmLicense,
    [string]$Python = 'python',
    [string]$Compiler = 'ISCC.exe',
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = '0.0.1'
)
$ErrorActionPreference = 'Stop'
$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$BuildDirectory = Join-Path $PSScriptRoot ('build\' + [guid]::NewGuid().ToString('N'))
$Payload = Join-Path $BuildDirectory 'payload'
$Wheels = Join-Path $Payload 'wheels'
$Packages = @('sim', 'artifacts', 'connectors', 'loops', 'fuzzy', 'supervisor',
    'anomaly', 'softsensor', 'opcua', 'gateway', 'runtime', 'api')

function Invoke-BuildCommand([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed ($LASTEXITCODE). Fix the build and retry." }
}

function Assert-Hash([string]$Path, [string]$ExpectedHash) {
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $ExpectedHash) {
        throw "SHA256 mismatch for $Path. Obtain a reviewed upstream artifact and digest."
    }
}

function Build-Wheels {
    $Sources = Join-Path $BuildDirectory 'sources'
    New-Item -ItemType Directory -Force $Sources, $Wheels | Out-Null
    foreach ($Package in $Packages) {
        Copy-Item -LiteralPath (Join-Path $Repository $Package) -Destination $Sources -Recurse
        Invoke-BuildCommand $Python @('-m', 'pip', 'wheel', '--no-deps', '--wheel-dir',
            $Wheels, (Join-Path $Sources $Package))
    }
    $LocalWheels = @(Get-ChildItem -LiteralPath $Wheels -Filter '*.whl' |
        Select-Object -ExpandProperty FullName)
    Invoke-BuildCommand $Python (@('-m', 'pip', 'wheel', '--wheel-dir', $Wheels,
        '--find-links', $Wheels, 'uvicorn==0.32.0', 'asyncua==2.1.0') + $LocalWheels)
}

function Install-EmbeddedPackages {
    $EmbeddedDirectory = Join-Path $Payload 'python'
    Expand-Archive -LiteralPath $PythonArchive -DestinationPath $EmbeddedDirectory
    $PathFile = Join-Path $EmbeddedDirectory 'python312._pth'
    if (-not (Test-Path -LiteralPath $PathFile)) { throw 'Use the CPython 3.12 x64 embed ZIP.' }
    # The isolated distribution ignores normal Python paths; explicitly enable installed wheels.
    @('python312.zip', '.', 'Lib\site-packages', 'import site') |
        Set-Content -LiteralPath $PathFile -Encoding Ascii
    $PackageWheels = @(Get-ChildItem -LiteralPath $Wheels -Filter '*.whl' |
        Select-Object -ExpandProperty FullName)
    Invoke-BuildCommand $Python (@('-m', 'pip', 'install', '--no-index', '--no-compile',
        '--find-links', $Wheels, '--target', "$EmbeddedDirectory\Lib\site-packages") + $PackageWheels)
    Copy-Item -LiteralPath (Join-Path $Repository 'schemas') -Destination $Payload -Recurse
    # Some existing packages still locate schemas relative to their installed module.
    Copy-Item -LiteralPath (Join-Path $Repository 'schemas') -Destination $EmbeddedDirectory -Recurse
    Invoke-BuildCommand "$EmbeddedDirectory\python.exe" @('-c',
        'import crosscut_api, crosscut_runtime, crosscut_gateway, numpy, pyarrow, uvicorn, asyncua')
}

function Build-Console {
    $Frontend = Join-Path $BuildDirectory 'frontend'
    New-Item -ItemType Directory -Force $Frontend | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $Repository 'frontend') |
        Where-Object { $_.Name -notin @('node_modules', 'dist') } |
        Copy-Item -Destination $Frontend -Recurse
    Push-Location $Frontend
    try {
        Invoke-BuildCommand 'npm.cmd' @('ci', '--no-audit', '--no-fund')
        Invoke-BuildCommand 'npm.cmd' @('run', 'build')
    } finally { Pop-Location }
    Copy-Item -LiteralPath "$Frontend\dist" -Destination "$Payload\console" -Recurse
    Copy-Item -LiteralPath "$PSScriptRoot\installer\console_entrypoint.py" -Destination $Payload
}

function Copy-Notices {
    Copy-Item -LiteralPath $NssmExecutable -Destination "$Payload\nssm.exe"
    New-Item -ItemType Directory -Force "$Payload\notices" | Out-Null
    Copy-Item -LiteralPath $NssmLicense -Destination "$Payload\notices\NSSM.txt"
    Copy-Item -LiteralPath "$Repository\LICENSE", "$Repository\LICENSING.md" `
        -Destination "$Payload\notices"
    # Wheel .dist-info directories and the embedded Python licence remain in the payload.
}

Assert-Hash $PythonArchive $PythonSha256
Assert-Hash $NssmExecutable $NssmSha256
Invoke-BuildCommand $Python @('-c',
    "import sys, struct; assert sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8, 'Use Python 3.12 x64'")
Build-Wheels
Install-EmbeddedPackages
Build-Console
Copy-Notices
if (Get-Command $Compiler -ErrorAction SilentlyContinue) {
    Invoke-BuildCommand $Compiler @("/DPayloadDir=$Payload", "/DAppVersion=$Version",
        "/O$BuildDirectory", "$PSScriptRoot\installer\crosscut.iss")
} else {
    Write-Warning "Inno Setup compiler not found. Payload ready at $Payload; install Inno Setup and rerun."
}
Write-Output "Installer artifacts: $BuildDirectory"

