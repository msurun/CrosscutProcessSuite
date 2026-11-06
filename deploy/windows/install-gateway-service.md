# Crosscut Write Gateway Windows Service Installation

This guide installs the Crosscut Write Gateway as a Windows service with NSSM (Non-Sucking Service Manager) and locks down the data root with Windows ACLs (`icacls`).

The Write Gateway is the sole process authorized to write setpoints to the plant control system (ADR 011, ADR 012). It runs under its own dedicated service account and verifies all incoming commands with an HMAC key.

Run every command in an elevated (administrator) `cmd` prompt. In `cmd`, `%COMPUTERNAME%` expands to the local machine name; PowerShell users write `$env:COMPUTERNAME` instead.

---

## 1. Prerequisites

1. Download NSSM from [https://nssm.cc](https://nssm.cc) and copy `nssm.exe` into `C:\Windows\System32`.
2. Ensure the Python virtual environment exists at `C:\crosscut\.venv` with the `gateway` package installed.
3. Ensure the data root exists at `C:\crosscut\data` and that `plant-map.json` is in it (see `deploy\examples\plant-map.example.json` and the read-back node section of `docs\GATEWAY_RUNBOOK.md`).

---

## 2. Dedicated Service Accounts

Create two distinct local accounts with standard user privileges:
- `crosscut-api`: runs the FastAPI data API.
- `crosscut-gw`: runs the Write Gateway service.

```cmd
net user crosscut-api <password> /add /comment:"Crosscut API Service Account" /expires:never
net user crosscut-gw <password> /add /comment:"Crosscut Gateway Service Account" /expires:never
```

Both accounts need the **Log on as a service** right (`SeServiceLogonRight`): `secpol.msc` -> *Local Policies* -> *User Rights Assignment*.

---

## 3. Lock Down the Data Root (icacls)

The default ACL of a folder below `C:\` usually contains `BUILTIN\Users` and `NT AUTHORITY\Authenticated Users` with Modify rights. That would let any local user edit the policy, the pin, the plant map and the inbox. Remove all inherited entries and grant explicitly.

**Account syntax.** `icacls` wants `COMPUTERNAME\account` for local accounts (`%COMPUTERNAME%\crosscut-gw`); the form `.\crosscut-gw` is not reliable there. The built-in groups are written as SIDs so the commands also work on non-English Windows: `*S-1-5-32-544` = Administrators, `*S-1-5-18` = SYSTEM. (The NSSM `ObjectName` below does accept `.\account`.)

Apply the steps in this order: a child folder inherits from its parent until its own `/inheritance:r`.

### 3.1 Data root: read-only for the two service accounts

```cmd
icacls "C:\crosscut\data" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "%COMPUTERNAME%\crosscut-gw:(OI)(CI)RX" "%COMPUTERNAME%\crosscut-api:(OI)(CI)RX"
```

The API additionally needs to write whatever it manages itself, at least its auth folder (users, auth audit):

```cmd
icacls "C:\crosscut\data\_auth" /grant:r "%COMPUTERNAME%\crosscut-api:(OI)(CI)M"
```

### 3.2 Secrets: key readable by the two accounts only

The HMAC key `C:\crosscut\data\_secrets\gateway-hmac.key` is read by the gateway (verify) and the API (sign command envelopes). Nobody else.

```cmd
icacls "C:\crosscut\data\_secrets" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "%COMPUTERNAME%\crosscut-gw:(OI)(CI)R" "%COMPUTERNAME%\crosscut-api:(OI)(CI)R"
icacls "C:\crosscut\data\_secrets\gateway-hmac.key" /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" "%COMPUTERNAME%\crosscut-gw:R" "%COMPUTERNAME%\crosscut-api:R"
```

`auth_cli rotate-key` replaces the key file through a temporary file, so the new file may carry the folder ACL instead of the file ACL above. Re-run the second command after every rotation.

### 3.3 Gateway state, policy and inbox

```cmd
mkdir "C:\crosscut\data\_gateway\policy"
mkdir "C:\crosscut\data\_gateway\inbox"

rem Gateway state: the gateway account may modify, the API keeps the inherited read access
icacls "C:\crosscut\data\_gateway" /grant:r "%COMPUTERNAME%\crosscut-gw:(OI)(CI)M"

rem Live policy and its pin (policy.pin.json): the gateway account only, nobody else
icacls "C:\crosscut\data\_gateway\policy" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "%COMPUTERNAME%\crosscut-gw:(OI)(CI)M"

rem Inbox: the API drops command envelopes here; the gateway moves them out again
icacls "C:\crosscut\data\_gateway\inbox" /grant:r "%COMPUTERNAME%\crosscut-api:(OI)(CI)M"
```

### 3.4 Plant map: gateway account only

The plant map holds the OPC UA endpoint and node ids; only the gateway reads it.

```cmd
icacls "C:\crosscut\data\plant-map.json" /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" "%COMPUTERNAME%\crosscut-gw:R"
```

### 3.5 Verify the ACLs

```cmd
icacls "C:\crosscut\data"
icacls "C:\crosscut\data\_secrets\gateway-hmac.key"
icacls "C:\crosscut\data\_gateway\policy"
icacls "C:\crosscut\data\_gateway\inbox"
icacls "C:\crosscut\data\plant-map.json"
icacls "C:\crosscut\data\*" /t | findstr /i "Everyone Users"
```

Expected (account names are shown as `<COMPUTERNAME>\...`):

- `C:\crosscut\data`: `BUILTIN\Administrators:(OI)(CI)(F)`, `NT AUTHORITY\SYSTEM:(OI)(CI)(F)`, `<COMPUTERNAME>\crosscut-gw:(OI)(CI)(RX)`, `<COMPUTERNAME>\crosscut-api:(OI)(CI)(RX)` and nothing else. No `(I)` flag on these lines at the root.
- `gateway-hmac.key`: Administrators `(F)`, SYSTEM `(F)`, `crosscut-gw:(R)`, `crosscut-api:(R)`. Nothing else, no `(I)`.
- `_gateway\policy`: Administrators, SYSTEM and `crosscut-gw:(OI)(CI)(M)` only. In particular no `crosscut-api`.
- `_gateway\inbox`: the inherited entries plus `crosscut-api:(OI)(CI)(M)` (explicit, no `(I)` on that line).
- `plant-map.json`: Administrators `(F)`, SYSTEM `(F)`, `crosscut-gw:(R)` only.
- The last command (`findstr`) must print nothing: no `Everyone`, `BUILTIN\Users` or `NT AUTHORITY\Authenticated Users` entry anywhere below the root. If it prints lines, look at that folder with `icacls <folder>` and repeat its `/inheritance:r` command.

---

## 4. Install the Service with NSSM

NSSM runs `python.exe` directly. There is no wrapper script and no restart loop of our own: NSSM restarts the process, and exit code 2 (configuration error: missing policy, pin, plant map or key, invalid pin) ends the service instead of looping.

```cmd
nssm install CrosscutGateway C:\crosscut\.venv\Scripts\python.exe
nssm set CrosscutGateway AppParameters "-m crosscut_gateway --root C:\crosscut\data --policy C:\crosscut\data\_gateway\policy\write-policy.json --plant-map C:\crosscut\data\plant-map.json --mode advisory"
nssm set CrosscutGateway AppDirectory C:\crosscut
nssm set CrosscutGateway ObjectName .\crosscut-gw <password>
nssm set CrosscutGateway Start SERVICE_AUTO_START
nssm set CrosscutGateway AppExit Default Restart
nssm set CrosscutGateway AppExit 2 Exit
nssm set CrosscutGateway AppRestartDelay 5000
nssm set CrosscutGateway AppStdout C:\crosscut\data\_gateway\service.log
nssm set CrosscutGateway AppStderr C:\crosscut\data\_gateway\service.log
```

`deploy\windows\run-gateway.cmd` is only a console launcher (it sets defaults and runs the same command once, passing on the exit code). Do not put it under NSSM: an extra `cmd /c` layer only adds a place where the exit code can get lost.

Exit codes: 0 = clean stop, 2 = configuration error (NSSM does not restart), anything else (for example 1 after a crash, or a failed audit-chain check at startup) = restart after 5 s. Read `service.log` when the service does not stay up.

Before the first start the policy and its pin must exist in `C:\crosscut\data\_gateway\policy` (runbook section 1), otherwise the gateway exits with code 2. Then run `nssm start CrosscutGateway`.

---

## 5. Verify Service Health

1. Status:
   ```cmd
   nssm status CrosscutGateway
   sc query CrosscutGateway
   ```
2. In `C:\crosscut\data\_gateway\state.json`:
   - `auth`: `"ok"`.
   - `chain_ok`: `true`.
   - `key_acl`: `"unchecked"`. This is by design on Windows: the gateway only checks POSIX file modes (`keyfile.py`). It does NOT warn about a loose key ACL, so the operator must run the `gateway-hmac.key` check from section 3.5 by hand after installation, after every key rotation and after every restore from backup.
3. Stop gracefully: `nssm stop CrosscutGateway` (NSSM sends Ctrl+C, the gateway ends its loop).
