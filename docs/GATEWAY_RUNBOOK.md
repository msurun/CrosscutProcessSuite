# Crosscut Write Gateway Operator Runbook

Operational manual for commissioning, running, and recovering the Crosscut Write Gateway (ADR 011, ADR 012, ADR 013). The Write Gateway is the sole process authorized to write setpoints to the plant control system.

Paths below use the Linux layout (data root `/var/lib/crosscut`, shortened to `<root>`). For Windows use `deploy/windows/install-gateway-service.md`, which sets the same permissions with `icacls`.

---

## 1. First-Time Setup Order

Follow this sequence strictly on initial deployment. Any missing prerequisite prevents the gateway from starting (exit code 2).

1. **Accounts and groups** (Linux):
   ```bash
   groupadd --system crosscut-sec
   useradd --system -U --no-create-home --shell /usr/sbin/nologin crosscut-gw
   usermod -aG crosscut-sec crosscut-gw
   usermod -aG crosscut-sec crosscut-api      # the account that runs the API
   ```
   `crosscut-sec` must contain exactly these two accounts. Note: `deploy/crosscut-api.service` currently runs the API as `crosscut`; put whichever account runs the API into `crosscut-sec` and use that name below.
2. **Initialize Auth and Gateway HMAC Key**:
   Create the first administrator account, `_auth/users.json`, and the HMAC signing key `_secrets/gateway-hmac.key`:
   ```bash
   python -m crosscut_api.auth_cli init --root /var/lib/crosscut --username admin
   ```
   The CLI writes the key with mode 0640 in a 0750 folder, owned by whoever ran it. Give the group to `crosscut-sec` so the gateway (Group=crosscut-sec) and the API can read it:
   ```bash
   chown root:crosscut-sec /var/lib/crosscut/_secrets /var/lib/crosscut/_secrets/gateway-hmac.key
   chmod 0750 /var/lib/crosscut/_secrets
   chmod 0640 /var/lib/crosscut/_secrets/gateway-hmac.key
   ```
   The gateway refuses a key file that is group- or world-writable or world-readable (`keyfile.py`), so never go looser than 0640. Repeat the `chown` after every `rotate-key` (the new file is created by the CLI user).
3. **Provision Process Roles**:
   The `admin` role manages users but carries no process authority. Create user accounts for operational personnel:
   ```bash
   python -m crosscut_api.auth_cli add-user --root /var/lib/crosscut --username j.doe --roles lead
   python -m crosscut_api.auth_cli add-user --root /var/lib/crosscut --username m.smith --roles engineer
   python -m crosscut_api.auth_cli add-user --root /var/lib/crosscut --username op1 --roles operator
   ```
4. **Create the gateway folders with their permissions**:
   ```bash
   install -d -o crosscut-gw -g crosscut-sec -m 0750 /var/lib/crosscut/_gateway
   # live policy + policy.pin.json: policy_pin writes both here, the gateway account only
   install -d -o crosscut-gw -g crosscut-gw  -m 0700 /var/lib/crosscut/_gateway/policy
   # inbox: the API account may write, nobody else (except the gateway itself)
   install -d -o crosscut-gw -g crosscut-sec -m 0750 /var/lib/crosscut/_gateway/inbox
   setfacl -m u:crosscut-api:rwx -m d:u:crosscut-api:rwx -m d:u:crosscut-gw:rwx /var/lib/crosscut/_gateway/inbox
   ```
   The policy folder must be writable by the gateway service because `policy_pin` creates a temporary file in it and replaces both `write-policy.json` and `policy.pin.json` when a policy is pinned from the GUI. `deploy/crosscut-gateway.service` allows writes below `<root>/_gateway` only (`ReadWritePaths`) and starts with `--policy <root>/_gateway/policy/write-policy.json`; the flag, the unit and these folders must agree. The data root itself must be traversable (`x`) for `crosscut-gw`.
5. **Configure the Plant Map**:
   Write `/var/lib/crosscut/plant-map.json` (start from `deploy/examples/plant-map.example.json`) using vendor DCS documentation. Confirm OPC UA NodeIds for setpoint, readback, mode, source, and `take_remote` handover; read section 7 about the read-back node. Permissions: `chown root:crosscut-gw` and `chmod 0640`.
6. **Author and Pin the Write Policy**:
   Write the initial `/var/lib/crosscut/_gateway/policy/write-policy.json` (start from `deploy/examples/write-policy.example.json`) with mode `advisory` and conservative limits. `crosscut_gateway` requires a signed pin on startup (`policy.pin.json` beside the policy), so pin it once offline with two distinct signers (author and approver must be different people), running as the gateway account so that the files have the right owner:
   ```python
   # sudo -u crosscut-gw -g crosscut-sec /opt/crosscut/.venv/bin/python this_script.py
   from datetime import datetime, UTC
   from pathlib import Path
   from crosscut_gateway.keyfile import default_key_path, read_key
   from crosscut_gateway.policy_pin import create_pin, PinSigners

   root = Path("/var/lib/crosscut")
   key = read_key(default_key_path(root))
   policy = root / "_gateway" / "policy" / "write-policy.json"
   create_pin(policy, key, PinSigners("m.smith", "j.doe"), datetime.now(UTC))
   ```
   Later changes go through the GUI: an engineer saves a draft (`policy_draft`), a different person with the `lead` role pins it (`policy_pin`, step-up password) and a lead reloads it (`policy_reload`, only in mode `off` or `advisory`).
7. **Start the Gateway in Advisory Mode**:
   Start the service: `systemctl enable --now crosscut-gateway` (Linux) or `nssm start CrosscutGateway` (Windows). Verify initial state in `_gateway/state.json` (`auth: "ok"`, `key_acl: "ok"`, `chain_ok: true`).

Exit codes of `python -m crosscut_gateway`: 0 clean stop; 2 configuration error (policy, pin, plant map or key file missing or invalid, policy or pin rejected, plant map invalid); the unit and the NSSM service do not restart on 2. Any other code (for example 1 after a crash or a failed audit chain check, see section 8) is restarted after 5 s.

---

## 2. Mode Ladder and Authority

The gateway operates along a strict 5-step mode ladder:
`off` -> `advisory` -> `dry_run` -> `confirm` -> `supervised`

- **Raising Mode**: Mode may only be raised **one step at a time** (e.g. `advisory` -> `dry_run`), and cannot exceed the cap defined in `write-policy.json`.
- **Lowering Mode**: Mode may be lowered to any lower mode immediately in a single step by any human role.

### Permission Table (ADR 013)

| Role | Permissions |
|---|---|
| `viewer` | `data.view`, `gw.view`, `audit.view`, `gw.kill`, `gw.mode.down`, `gw.reject` |
| `operator` | `viewer` + `analysis.run`, `job.stop`, `gw.approve`, `gw.reject`, `gw.re_enable.hold_off` |
| `engineer` | `operator` + `data.import`, `config.edit`, `connector.use`, `job.manage`, `gw.propose`, `gw.approve.tuning`, `gw.mode.up.advisory`, `gw.mode.up.dry_run`, `gw.mode.up.confirm`, `gw.re_enable.stopped`, `policy.edit` |
| `lead` | `engineer` + `gw.mode.up.supervised`, `gw.kill.reset`, `policy.pin`, `policy.reload` |
| `admin` | `viewer` + `users.manage` (no process authority) |
| `service` | runtime jobs, actor `svc:runtime`: `gw.propose` only |

*Note: Raising to `supervised`, pinning a policy, resetting a kill, and managing users require password step-up authentication (valid for 5 minutes).*

---

## 3. What the Operator Can Always Do

The system guarantees that an operator can intervene at any moment without administrative escalation:

- **Kill from GUI**: The red Kill button in the GUI header invokes `gw.kill` (held by all human roles) and halts writes within 1 gateway cycle (polling interval, default 1 s).
- **Filesystem Emergency Kill**: Placing an empty or arbitrary file at `<root>/_gateway/KILL` kills the gateway on its next cycle without login credentials or an HMAC signature. The gateway renames the file to `KILL.handled-<timestamp>` and persists the kill latch.
- **Lower the Mode**: Jump down to `advisory` or `off` instantly (`gw.mode.down`).
- **Reject Proposals**: Reject any pending write proposals in `confirm` mode (`gw.reject`).
- **DCS Operator Takeover (Hold-Off)**: Any manual setpoint-source or loop-mode change at the DCS console is detected while the gateway holds the setpoint. The gateway releases the target, puts it into `hold_off` for `hold_off_s` and stops writing to it. After `hold_off_s` an operator re-enables it (`gw.re_enable.hold_off`); an earlier re-enable is refused ("hold-off not over").

---

## 4. How to Recover After Kill

A kill moves every target to the state `killed`, flushes pending proposals and writes the persistent latch `<root>/_gateway/KILLED`. The latch survives restarts: after a restart the gateway comes up killed again. A target in state `killed` cannot be re-enabled.

Recovery requires a two-stage procedure:

1. **Reset the Kill Latch (`kill_reset`)**:
   A user with the `lead` role executes `kill_reset` with step-up password confirmation. This deletes the `KILLED` latch file, resets the operating mode to `advisory` (never above the policy cap) and moves every target from `killed` to `stopped:kill`.
2. **Re-Enable Targets Individually (`re_enable`)**:
   Every target is now in `stopped:kill`. An `engineer` or `lead` inspects each target loop and issues a `re_enable` command per tag (`gw.re_enable.stopped`). Targets cannot be batch re-enabled.

---

## 5. What `state.json` Fields Mean

The gateway writes `<root>/_gateway/state.json` (temp file, then replace) on every poll cycle. Key fields:

- `updated_at_utc`: ISO-8601 UTC timestamp of the last gateway cycle. If stagnant, the service is hung or stopped.
- `mode`: Current operating mode (`off`, `advisory`, `dry_run`, `confirm`, `supervised`).
- `targets`: Object mapping each configured tag to one state string, nothing else (no setpoint or read-back values). The states are `enabled`, `hold_off`, `killed`, and `stopped:<reason>` (for example `stopped:kill`, `stopped:comm`, `stopped:rejected`).
- `pending`: Queue of proposals awaiting approval in `confirm` mode (contains proposal key, target tag, value, proposer, and reason).
- `audit_tail`: The latest 200 audit records of `audit.jsonl`.
- `chain_ok`: Boolean. `true` when the audit hash chain verifies with the gateway key currently loaded; `false` when a record was edited, inserted or signed with another key (for example after a key rotation, section 8).
- `auth`: `"ok"` when a usable HMAC key (at least 32 bytes) is loaded; `"key_missing"` when it is absent, too short or unreadable. In that state the gateway accepts only `kill` and `set_mode` downgrades and refuses every other command.
- `roles_digest`: SHA-256 hex digest of the currently loaded roles table.
- `key_acl`: `"ok"` on POSIX when the key file is neither group/world-writable nor world-readable (0600 or 0640); `"insecure"` when it is looser; `"unchecked"` on Windows, where the gateway does not look at ACLs. On Windows the operator verifies the key ACL by hand (`deploy/windows/install-gateway-service.md`, section 3.5).

---

## 6. How to Read the Audit Log and Verify the Chain

The audit trail is `<root>/_gateway/audit.jsonl`, one JSON object per line. Every record has `seq`, `t_ns`, `event`, `prev_hash`, `hash` plus the event fields (`tag`, `value`, `proposer`, `mode`, `reason_code` and the acting principal's fields). `prev_hash` is the `hash` of the previous record (zeros for the first); `hash` is an HMAC-SHA256 under the gateway key over the record without `hash`. Proposals, approvals, rejections, writes, mode changes, kills, hold-offs, policy reloads and service errors are logged.

There is no `read_records` function. Ways to read it:

- **GUI / API**: `GET /gateway/audit?limit=N` returns the newest records from `state.json` (`audit_tail`, at most 200) and `chain_ok`.
- **State file**: `audit_tail` and `chain_ok` in `state.json` directly.
- **Whole file, offline** (read-only; use a copy for long investigations):
  ```python
  import json
  from pathlib import Path
  from crosscut_gateway.audit import verify_chain
  from crosscut_gateway.keyfile import default_key_path, read_key

  root = Path("/var/lib/crosscut")
  lines = (root / "_gateway" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
  records = [json.loads(line) for line in lines if line.strip()]
  key = read_key(default_key_path(root))
  print("Audit chain valid:", verify_chain(records, key))
  ```
  `verify_chain` returns `False` for a broken link, an edited record or a record signed with another key. It does not detect removal of the last records or replacement of the whole file; keep the backups of section 9.

---

## 7. Plant Map: the Read-Back Node

The plant map schema has no comment or description field, so this is documented here.

Every cycle the gateway reads `readback_node` for each target it holds and compares the value with the **setpoint it last wrote** (`engine._check_readback`, `opcua_plant.read`). If they differ by more than `readback_tolerance`, the target goes into `hold_off` (reason `readback_mismatch`).

Therefore `readback_node` must show the **setpoint as the DCS holds it**: use the setpoint node itself (as in `deploy/examples/plant-map.example.json`, where `readback_node` equals `setpoint_node`) or a distinct SP read-back tag, in the same engineering units. Do **not** point it at the process value (PV): the PV follows the setpoint with lag and offset, so the comparison would fail constantly and the target would sit in `hold_off`.

---

## 7a. Tuning Parameters (Phase 3)

PID parameters (gain, `ti`, `td`, `tf`) are separate `pid_param` targets in `write-policy.json` and the plant map (ADR 014). The example files carry one, `FIC101.KP`. The policy target is only half of it: the plant map needs a `pid_param` target (`param_node`, `data_type`, `mode_node`) with the same tag. At start-up (exit 2) and at `policy_reload` (reply with the error) the gateway refuses any mismatch: a policy parameter target the plant cannot read and write, one missing from the plant map, a plant-map `pid_param` target without a policy, or a tag that is a setpoint on one side and a parameter on the other. Nothing is dropped silently.

- **Confirm only.** A parameter set is never written directly. `supervised` behaves as `confirm` for parameters (cap `confirm`); `advisory` and `dry_run` only record. Every set waits in `pending_params` for a person.
- **Who approves.** An engineer or lead with `gw.approve.tuning` approves, and never the proposer (`self_approval`). An operator may reject but not approve. The `service` principal cannot propose tuning.
- **`from_mismatch`.** At approval the gateway reads each parameter again. If a live value differs from the proposal's `from` by more than `readback_tolerance`, the loop was retuned since the proposal: the set is refused, nothing is written, and the values read are in the audit record. Propose again from the current values.
- **Refusal, not clamping.** A value outside `limits`, a change larger than `max_ratio` times the current value, a wrong sign or a wrong unit refuses the whole set. The gateway never writes a reduced value.
- **External change gives `hold_off`.** Each cycle the gateway reads back every applied parameter. A value that moved (an operator retuned at the DCS) puts the target in `hold_off` with an audit record `param_changed_externally`; the gateway never writes it back and never releases anything. The target is enabled again with `re_enable` (permission `gw.re_enable.hold_off`), and the next set starts from a new baseline.
- **State after a failure.** A transport error or a failed write or read-back sets the target `stopped:comm` or `stopped:readback`, and values already written in the set are reverted in detune order. If a revert fails too, the audit shows `alarm_check_dcs`: check the loop at the DCS first. Only then `re_enable` (permission `gw.re_enable.stopped`, engineer or lead). A kill drops every queued set and leaves all targets `stopped:kill` after the reset until each is re-enabled.
- **Reload.** `policy_reload` swaps setpoint and parameter policies together, only in `off` or `advisory`, and is refused with `reload_blocked_param_pending` while a parameter set is queued: approve or reject it first. A swap that is refused changes nothing.

---

## 8. Key Rotation and Lost Key Impact

The HMAC key signs command envelopes, the policy pin and the audit chain. Changing it has consequences.

### Rotation procedure

1. **Stop** the gateway and the API.
2. **Archive** `<root>/_gateway/audit.jsonl` (move it away to secure storage) together with a copy of the old key. Records signed with the old key cannot be verified with the new one: if the old file stays, the gateway fails at startup with an audit chain error (uncaught `AuditError`, exit code 1, which the service manager retries every 5 s) and `chain_ok` is `false` for it. With the file moved away a new chain starts.
3. **Rotate**:
   ```bash
   python -m crosscut_api.auth_cli rotate-key --root /var/lib/crosscut
   chown root:crosscut-sec /var/lib/crosscut/_secrets/gateway-hmac.key   # Windows: re-apply the icacls of install-gateway-service.md 3.2
   ```
   This atomically writes 32 fresh random bytes. Commands and sessions signed with the old key are rejected.
4. **Re-pin the policy.** The pin is an HMAC under the key, so the old `policy.pin.json` is now invalid (`bad_signature`) and the gateway exits with code 2 at startup. A gateway that cannot load its policy starts only when the kill latch exists; it then runs as a "safe gateway" (no targets, mode `off`) and accepts the policy commands. So:
   1. Create the latch: `sudo -u crosscut-gw touch /var/lib/crosscut/_gateway/KILLED` (Windows: create an empty file `_gateway\KILLED`).
   2. Start the API and the gateway. The log says "policy not loaded, kill latch set; safe gateway only".
   3. Re-pin with two different people: an engineer saves the draft (`policy_draft`), a different lead pins it (`policy_pin`, step-up), then a lead runs `policy_reload`. The author and the approver must be different persons.
   4. `kill_reset` (lead), then `re_enable` every target (section 4).
   Verify this path on the simulator before you need it in production.
5. Check `state.json`: `auth: "ok"`, `chain_ok: true`.

Rotating while the gateway runs is not supported: it reloads the key on every poll, so `chain_ok` turns `false` at once and the running process keeps writing audit records signed with the old key.

### Lost or corrupted key

- **At startup the gateway does not start.** A key file that is missing, unreadable, shorter than 32 bytes, or (POSIX) too loose in mode is reported on stderr and the process exits with code 2 (`__main__._load_key`). There is no kill-only mode at startup, and a set kill latch does not change that: no process is running, so no command, KILL file or `set_mode` is processed. Targets that were held stop receiving writes and the DCS-side watchdog/handover applies.
- **While running**, if the key file disappears or becomes unusable, the gateway reloads it on the next poll and then reports `auth: "key_missing"` in `state.json`. It accepts only `kill` and `set_mode` downgrades; everything else is refused with `key_missing`. A restart in that state fails as above.
- **Recovery**: restore the key file from backup (section 9) with the right owner and mode (`chown root:crosscut-sec`, `chmod 0640`); the pin and the audit chain stay valid. Only if there is no backup, rotate (`auth_cli rotate-key` creates a fresh key) and follow the rotation procedure above, including archiving the old audit log and re-pinning.

---

## 9. Backup List

Back up the following files regularly to secure, off-host or write-once storage:

- `<root>/_secrets/gateway-hmac.key` (HMAC signing key)
- `<root>/_auth/users.json` (user accounts and password hashes)
- `<root>/_auth/auth-audit.jsonl` (authentication audit log)
- `<root>/_gateway/policy/write-policy.json` (active write policy)
- `<root>/_gateway/policy/policy.pin.json` (signed policy pin)
- `<root>/plant-map.json` (OPC UA plant mapping)
- `<root>/_gateway/audit.jsonl` (gateway hash-chained audit log)

*Do NOT back up transient directories: `<root>/_gateway/inbox/`, `<root>/_gateway/outbox/`, `<root>/_gateway/rejected/`, `<root>/_gateway/nonce-cache.json`, or `<root>/_gateway/state.json`.*

---

## 10. Pre-Commissioning Checklist

Complete and sign off every item before switching any loop to `confirm` or `supervised`:

- [ ] **Read-back tested on the simulator**: Verified that setpoint writes match read-back values within `readback_tolerance`, that `readback_node` shows the setpoint (not the PV, section 7), and that an intentional read-back discrepancy puts the target into `hold_off` (not a permanent stop; it needs a re-enable after `hold_off_s`).
- [ ] **Watchdog tested**: Verified that when no new write arrives within `watchdog_s` the gateway releases the target to local control, and that stopping the gateway heartbeat makes the DCS watchdog logic hand the loops back to local control (DCS side: confirm with the vendor).
- [ ] **`take_remote` verified with vendor**: Confirmed whether writing `source_node` before setpoint is required by DCS logic, and verified bumpless transfer behavior with the plant automation engineer.
- [ ] **Kill tested**: Triggered both the GUI Kill button and the `<root>/_gateway/KILL` file; confirmed all writes halt within 1 cycle, every target shows `killed`, the `KILLED` latch is written and survives a gateway restart, and recovery by `kill_reset` plus per-tag `re_enable` works.
- [ ] **KILL file tested** (skip if the site runs the gateway with `--no-kill-file` or `kill_file_enabled: false`; see `docs/ADMIN_GUIDE.md` section 6): Created an empty file `<root>/_gateway/KILL` on the host; confirmed that within one cycle it is renamed to `KILL.handled-<timestamp>` and that the targets show `killed`.
- [ ] **Operator takeover tested**: Changed setpoint source and loop mode manually at the DCS console; verified the gateway detects it, enters `hold_off` for `hold_off_s`, and stops automated writing.
- [ ] **Lowering mode tested**: Lowered the mode from `confirm` to `advisory` and to `off` with each human role; confirmed writes stop immediately.
- [ ] **Policy pin location verified**: `<root>/_gateway/policy/` is owned by the gateway account only (mode 0700, or the `icacls` result of the Windows guide) and is writable by the service (the unit's `ReadWritePaths` covers it). A GUI draft -> pin -> reload cycle by two different people succeeds in `advisory`, and a pin by the author of the draft is refused.
- [ ] **Inbox permissions verified**: Only the API account (and the gateway account itself) can write `<root>/_gateway/inbox/` (`getfacl` on Linux, `icacls` on Windows); the permission listing (`ls -l`, `getfacl`, `icacls`) shows no write right for any other account, and a test file created in the inbox by an unrelated account is refused by the operating system.
- [ ] **Key permissions verified**: `gateway-hmac.key` is `root:crosscut-sec` mode 0640 (`key_acl: "ok"`); on Windows the manual `icacls` check passed (`key_acl` stays `"unchecked"`).

---

## 11. "Never Do" List

1. **NEVER** share user accounts or use generic logins. Every action must trace to an identifiable individual.
2. **NEVER** self-approve a policy or write proposal; the proposer and approver must always be distinct persons.
3. **NEVER** grant the `crosscut-gw` OS account write permissions outside `<root>/_gateway/`.
4. **NEVER** grant any account other than the API and the gateway write access to `<root>/_gateway/inbox/` or `<root>/_gateway/policy/`.
5. **NEVER** loosen file permissions on `gateway-hmac.key` (must remain 0640 `root:crosscut-sec` or stricter on POSIX, restricted ACLs on Windows).
6. **NEVER** edit `policy.pin.json` or `write-policy.json` by hand; any digest mismatch or invalid HMAC stops the gateway at the next start (exit 2).
7. **NEVER** raise the mode to `supervised` during commissioning or without a verified site test in `confirm` mode.
8. **NEVER** configure write policy limits wider than DCS safety interlock trips or equipment design limits.
9. **NEVER** delete or truncate `audit.jsonl` except as the archived step of a key rotation (section 8); doing so otherwise destroys the hash chain and violates compliance.
