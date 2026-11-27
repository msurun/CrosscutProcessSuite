; Crosscut Windows installer packages an offline, staged application.
; Service and ACL operations are checked by configure-services.ps1.
#ifndef PayloadDir
  #define PayloadDir "payload"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.1"
#endif
[Setup]
AppId=CrosscutProcessSuite
AppName=Crosscut Process Suite
AppVersion={#AppVersion}
DefaultDirName={autopf}\Crosscut
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=Crosscut-{#AppVersion}-win64
Compression=lzma2
SolidCompression=yes
CloseApplications=no

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "configure-services.ps1"; DestDir: "{app}"

; No [UninstallDelete] entry: ProgramData survives unattended uninstall.
[Code]
procedure StopServices;
var ResultCode: Integer;
begin
  if FileExists(ExpandConstant('{app}\configure-services.ps1')) then
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\configure-services.ps1') +
      '" -InstallDirectory "' + ExpandConstant('{app}') + '" -StopOnly',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      RaiseException('Could not stop Crosscut services. Stop them before retrying.');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopServices;
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var ResultCode: Integer;
begin
  if CurStep <> ssPostInstall then Exit;
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\configure-services.ps1') +
    '" -InstallDirectory "' + ExpandConstant('{app}') + '" -DataRoot "' + ExpandConstant('{commonappdata}\Crosscut') + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
    RaiseException('Service setup failed. Read ProgramData\Crosscut\installer.log and rerun setup.');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    if MsgBox('Permanently delete all Crosscut data, keys and logs?', mbConfirmation,
      MB_YESNO or MB_DEFBUTTON2) = IDYES then
      if not DelTree(ExpandConstant('{commonappdata}\Crosscut'), True, True, True) then
        MsgBox('Data removal failed. Remove ProgramData\Crosscut manually.', mbError, MB_OK);
end;

function InitializeUninstall(): Boolean;
var ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\configure-services.ps1') +
    '" -InstallDirectory "' + ExpandConstant('{app}') + '" -Uninstall',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := Result and (ResultCode = 0);
  if not Result then
    MsgBox('Services could not be removed. Check permissions and retry uninstall.', mbError, MB_OK);
end;
