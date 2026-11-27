# Register the three isolated processes with NSSM and apply data ACLs.
# Run elevated; virtual service identities need no stored account passwords.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$InstallDirectory,
    [string]$DataRoot = "$env:ProgramData\Crosscut",
    [switch]$Uninstall,
    [switch]$StopOnly
)
$ErrorActionPreference = 'Stop'
$ServiceNames = @('CrosscutGateway', 'CrosscutRuntime', 'CrosscutApi')
$GatewayAccount = 'NT SERVICE\CrosscutGateway'
$RuntimeAccount = 'NT SERVICE\CrosscutRuntime'
$ApiAccount = 'NT SERVICE\CrosscutApi'
$Wrapper = Join-Path $InstallDirectory 'nssm.exe'

function Invoke-Native([string]$Program, [string[]]$Arguments) {
    # PowerShell 5 does not turn a native exit code into a terminating error.
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed with exit $LASTEXITCODE. Review installer.log before retrying."
    }
}

function Stop-Services {
    # Reverse dependency order prevents a producer from running after its gateway stops.
    foreach ($ServiceName in @('CrosscutApi', 'CrosscutRuntime', 'CrosscutGateway')) {
        $Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($Service) {
            Stop-Service -Name $ServiceName -ErrorAction Stop
            $Service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(60))
        }
    }
}

function Set-FolderAccess([string]$Path, [hashtable]$Accounts) {
    # A fresh protected DACL removes stale explicit grants as well as inheritance.
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    $Access = New-Object System.Security.AccessControl.DirectorySecurity
    $Access.SetAccessRuleProtection($true, $false)
    $Access.SetOwner([System.Security.Principal.SecurityIdentifier]'S-1-5-32-544')
    foreach ($Principal in $Accounts.Keys) {
        $Identity = New-Object System.Security.Principal.NTAccount($Principal)
        if ($Principal.StartsWith('S-1-')) {
            $Identity = [System.Security.Principal.SecurityIdentifier]$Principal
        }
        $Rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $Identity, $Accounts[$Principal], 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $Access.AddAccessRule($Rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $Access
    # Reset existing descendants too: restored files can carry obsolete explicit grants.
    foreach ($Child in Get-ChildItem -LiteralPath $Path -Force) {
        Invoke-Native 'icacls.exe' @($Child.FullName, '/reset', '/T', '/Q')
    }
}

function Set-DataAccess {
    $Trusted = @{'S-1-5-32-544' = 'FullControl'; 'S-1-5-18' = 'FullControl'}
    $Shared = $Trusted.Clone()
    $Shared[$ApiAccount] = 'Modify'; $Shared[$RuntimeAccount] = 'Modify'
    $Shared[$GatewayAccount] = 'ReadAndExecute'
    Set-FolderAccess $DataRoot $Shared
    $Mailbox = $Trusted.Clone()
    $Mailbox[$ApiAccount] = 'ReadAndExecute'; $Mailbox[$RuntimeAccount] = 'ReadAndExecute'
    $Mailbox[$GatewayAccount] = 'Modify'
    Set-FolderAccess "$DataRoot\_gateway" $Mailbox
    Set-SharedFolders $Shared $Mailbox
    $GatewayOnly = $Trusted.Clone(); $GatewayOnly[$GatewayAccount] = 'Modify'
    Set-FolderAccess "$DataRoot\_gateway\policy" $GatewayOnly
    Set-FolderAccess "$DataRoot\_gateway\private" $GatewayOnly
    $Signers = $Trusted.Clone()
    $Signers[$GatewayAccount] = 'ReadAndExecute'
    $Signers[$ApiAccount] = 'ReadAndExecute'; $Signers[$RuntimeAccount] = 'ReadAndExecute'
    Set-FolderAccess "$DataRoot\_secrets" $Signers
}

function Set-SharedFolders([hashtable]$Shared, [hashtable]$Mailbox) {
    $WritableMailbox = $Mailbox.Clone()
    $WritableMailbox[$ApiAccount] = 'Modify'; $WritableMailbox[$RuntimeAccount] = 'Modify'
    Set-FolderAccess "$DataRoot\_gateway\inbox" $WritableMailbox
    Set-FolderAccess "$DataRoot\_gateway\outbox" $WritableMailbox
    Set-FolderAccess "$DataRoot\_gateway\rejected" $Mailbox
    $Logs = $Shared.Clone(); $Logs[$GatewayAccount] = 'Modify'
    Set-FolderAccess "$DataRoot\_logs" $Logs
}

function Register-ServiceProcess([string]$Name, [string]$Arguments) {
    $Python = Join-Path $InstallDirectory 'python\python.exe'
    if (-not (Get-Service -Name $Name -ErrorAction SilentlyContinue)) {
        Invoke-Native $Wrapper @('install', $Name, $Python)
    }
    Invoke-Native $Wrapper @('set', $Name, 'Application', $Python)
    Invoke-Native $Wrapper @('set', $Name, 'AppDirectory', $InstallDirectory)
    Invoke-Native $Wrapper @('set', $Name, 'AppParameters', $Arguments)
    Invoke-Native $Wrapper @('set', $Name, 'ObjectName', "NT SERVICE\$Name")
    Invoke-Native $Wrapper @('set', $Name, 'Start', 'SERVICE_AUTO_START')
    Invoke-Native $Wrapper @('set', $Name, 'AppEnvironmentExtra',
        "CROSSCUT_SCHEMAS_DIR=$InstallDirectory\schemas", 'PYTHONUNBUFFERED=1')
    Set-ServiceRecovery $Name
}

function Set-ServiceRecovery([string]$Name) {
    Invoke-Native $Wrapper @('set', $Name, 'AppExit', 'Default', 'Restart')
    # Exit 2 means missing/invalid gateway configuration; do not restart forever.
    Invoke-Native $Wrapper @('set', $Name, 'AppExit', '2', 'Exit')
    Invoke-Native $Wrapper @('set', $Name, 'AppRestartDelay', '10000')
    Invoke-Native $Wrapper @('set', $Name, 'AppStopMethodConsole', '30000')
    Invoke-Native $Wrapper @('set', $Name, 'AppStdout', "$DataRoot\_logs\$Name.stdout.log")
    Invoke-Native $Wrapper @('set', $Name, 'AppStderr', "$DataRoot\_logs\$Name.stderr.log")
    Invoke-Native $Wrapper @('set', $Name, 'AppRotateFiles', '1')
    Invoke-Native $Wrapper @('set', $Name, 'AppRotateOnline', '1')
    Invoke-Native $Wrapper @('set', $Name, 'AppRotateBytes', '5000000')
    Invoke-Native 'sc.exe' @('failure', $Name, 'reset=', '86400',
        'actions=', 'restart/10000/restart/30000/restart/60000')
    Invoke-Native 'sc.exe' @('failureflag', $Name, '0')
}

function Register-AllServices {
    $RootArgument = '--root "' + $DataRoot + '"'
    $GatewayArguments = '-m crosscut_gateway ' + $RootArgument +
        ' --policy "' + $DataRoot + '\_gateway\policy\write-policy.json"' +
        ' --plant-map "' + $DataRoot + '\plant-map.json" --mode advisory'
    Register-ServiceProcess 'CrosscutGateway' $GatewayArguments
    Register-ServiceProcess 'CrosscutRuntime' ('-m crosscut_runtime ' + $RootArgument)
    Register-ServiceProcess 'CrosscutApi' ('"' + $InstallDirectory +
        '\console_entrypoint.py" ' + $RootArgument)
    Invoke-Native $Wrapper @('set', 'CrosscutRuntime', 'DependOnService', 'CrosscutGateway')
    Invoke-Native $Wrapper @('set', 'CrosscutApi', 'DependOnService', 'CrosscutRuntime')
}

function Assert-DataTree {
    $Entries = @(Get-Item -LiteralPath $DataRoot) +
        @(Get-ChildItem -LiteralPath $DataRoot -Recurse -Force)
    if ($Entries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
        throw 'Data root contains a reparse point. Remove links before applying service ACLs.'
    }
}

function Install-Services {
    Stop-Services
    Assert-DataTree
    Register-AllServices
    Set-DataAccess
    # Installer registers automatic services but commissioning must precede first start.
}

if ($StopOnly) { Stop-Services; exit 0 }
if ($Uninstall) {
    Stop-Services
    foreach ($ServiceName in $ServiceNames) {
        if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
            Invoke-Native $Wrapper @('remove', $ServiceName, 'confirm')
        }
    }
    # Keep data by default; only the interactive uninstaller offers explicit deletion.
    exit 0
}
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
Start-Transcript -Path (Join-Path $DataRoot 'installer.log') -Append | Out-Null
try { Install-Services } finally { Stop-Transcript | Out-Null }


