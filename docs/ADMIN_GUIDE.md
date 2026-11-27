# Crosscut administrator guide

For the person who sets up accounts, roles and policies at one site. Crosscut is a platform: every site decides its own accounts, roles and limits. Nothing in this guide is a product decision; each item is a setting with a safe default. Design background: `docs/adr/013-roles-and-authority.md`. Gateway operation, backups and key rotation: `docs/GATEWAY_RUNBOOK.md`.

## 1. First-time setup order

1. Install and pick the data root (below `<root>`). The gateway and the API must use the same root.
2. Create the first administrator and the signing key on the host (the password is read from a prompt or `--password-file`):
   `python -m crosscut_api.auth_cli init --root <root> --username admin`
3. Optional: write `<root>/_auth/config.json` (section 4) and, if the site needs different duties, `<root>/_auth/roles.json` (section 2). Both are read at start-up only.
4. Set the permissions of the secrets directory and key file as in the runbook (section 2 there).
5. Start the API and the gateway. An invalid `config.json` stops the API with a message naming the field; fix the file and start again.
6. Sign in as `admin`, change the password, and create the real accounts (Users page, or `auth_cli add-user`).
7. Enter the plant map and the write policy (the DCS and controller units are site data, not product settings). Pin the policy with two distinct people (section 3).
8. Test the stop paths before enabling any write mode: header Kill button, and the KILL file if you keep it (section 6).

## 2. Accounts and roles

Accounts are personal: one account per person, no shared logins. A user may hold several roles. Permissions are the union of the roles. `kill`, `mode.down` and `reject` are forced in code for every human role and cannot be removed by any file.

| Role | Can do |
|------|--------|
| `viewer` | View data, gateway status and audit; Kill; lower the mode; reject proposals |
| `operator` | Viewer, plus run analyses, stop jobs, approve ordinary gateway requests, re-enable a held-off target |
| `engineer` | Operator, plus import data, edit configuration, use connectors, manage jobs, propose changes, approve tuning, raise the mode to advisory, dry_run and confirm, re-enable stopped targets, edit the policy draft |
| `lead` | Engineer, plus enable `supervised`, reset a kill, pin and reload the policy |
| `admin` | Viewer, plus manage users. No process authority |
| `service` | Machine account that may only propose (`gw.propose`) |

Admins and process authority are separate on purpose: an admin who also needs to pin a policy needs a second account with the process role.

### Creating a custom role

`<root>/_auth/roles.json` replaces the whole default table (copy `schemas/auth-roles.default.json` and edit it). It must validate against `schemas/auth-roles.schema.json`, and every human role must keep `gw.kill`, `gw.mode.down` and `gw.reject`; `service` may hold only `gw.propose`. A file that breaks a rule is ignored and the defaults are used, with a warning in the start-up log. Check the start-up log after a restart for that warning.

### Example: a site with no `lead`

The site has shift engineers only. Delete the `lead` entry and give its permissions to a role named `shift_engineer`:

```json
{
  "version": 1,
  "roles": {
    "shift_engineer": {
      "description": "Engineer duties plus supervised mode, kill reset and policy pinning.",
      "permissions": ["analysis.run", "audit.view", "config.edit", "connector.use",
        "data.import", "data.view", "gw.approve", "gw.approve.tuning", "gw.kill",
        "gw.kill.reset", "gw.mode.down", "gw.mode.up.advisory", "gw.mode.up.confirm",
        "gw.mode.up.dry_run", "gw.mode.up.supervised", "gw.propose",
        "gw.re_enable.hold_off", "gw.re_enable.stopped", "gw.reject", "gw.view",
        "job.manage", "job.stop", "policy.edit", "policy.pin", "policy.reload"]
    }
  }
}
```

The real file also lists `viewer`, `operator`, `admin` and `service` (copy them unchanged). Restart the API and gateway (the gateway takes `--roles <file>`).

## 3. Two-person rules

- **Policy pin.** The author of a policy draft cannot pin it. A second, distinct person with `policy.pin` must do it, and the gateway checks the signature.
- **Approvals.** A person cannot approve their own proposal.
- **Privileged administration** (setting `require_second_admin_for_password_reset`, default on). An admin cannot reset another user's password, or grant a role that carries `policy.pin`, `gw.kill.reset` or `gw.mode.up.supervised`, on their own. `POST /auth/users/{u}/password-reset` (or `PATCH` with such roles) creates a pending change (HTTP 202). A different admin approves it with `POST /auth/pending/{id}/approve` after a step-up. `GET /auth/pending` lists open changes. Pending changes live in memory for 24 hours and vanish on restart. Users cannot be created directly with such roles; create them, then grant.

### A site with one engineer

Be honest about what the software can enforce. The policy pin and every approval need two distinct people, so one person alone cannot enable a write path. Options, in order of preference:

1. Name a second qualified person (a colleague, a contractor, the plant manager's delegate) with their own account and the `engineer` or pin role. This is the intended setup.
2. Stay in `advisory` or `dry_run`, which never write to the DCS and need no second person.
3. Do not share one login between two "people". It defeats the audit trail and the pin check; the software cannot tell.

If the site has only one admin, set `require_second_admin_for_password_reset` to `false` (a schema-allowed value) and accept that admin actions are then single-person; the audit log still records them. Local `auth_cli` commands on the host are not covered by the rule: whoever has shell access has full control (section 8).

## 4. Settings reference

Edit `<root>/_auth/config.json`, then restart. All keys are optional; unknown keys and out-of-range values stop start-up. There is no write route: `GET /auth/settings` (permission `users.manage`) shows the effective values, `GET /auth/config` (public) shows only whether auth is on and initialised.

| Key | Default | Allowed |
|-----|---------|---------|
| `session_idle_minutes` | 60 | 5..1440 |
| `session_absolute_hours` | 12 | 1..72 |
| `stepup_valid_minutes` | 5 | 1..30 |
| `lockout_failures` | 5 | 3..20 failures per lock level |
| `lockout_base_minutes` | 5 | 1..60 (doubles each level) |
| `lockout_max_minutes` | 60 | 1..1440, not below base |
| `login_rate_per_ip_per_min` | 20 | 5..600 |
| `password_min_length` | 12 | 12..128 |
| `require_second_admin_for_password_reset` | true | true / false |
| `kill_file_enabled` | true | true / false |
| `allowed_origins` | [] | up to 32 origins such as `https://crosscut.plant.local` |
| `secure_cookie` | auto | auto (secure on HTTPS), true, false |

Example for a three-shift plant with a proxy on another name:

```json
{ "session_idle_minutes": 120, "session_absolute_hours": 14,
  "allowed_origins": ["https://crosscut.plant.local"], "secure_cookie": "true" }
```

Use `secure_cookie: "true"` whenever the browser reaches the API over HTTPS through a proxy that terminates TLS, because `auto` only sees the proxy hop.

## 5. Sessions for shift work

A session ends after the idle time or the absolute time, whichever comes first, and every restart signs everybody out. For 8 or 12 hour shifts keep `session_absolute_hours` at 12 or set it to the shift length plus handover (for example 14) so nobody is cut off mid-shift. Raising idle time keeps a control-room workstation signed in but also leaves it open when unattended; prefer a screen lock. Handover: the leaving person signs out, the arriving person signs in with their own account. Step-up (a password re-entry) is required for sensitive actions and lasts `stepup_valid_minutes`; do not raise it for convenience.

## 6. Kill without login (kiosk)

Kill is always visible to every signed-in role. Where an operator station has no personal login, two other stop paths exist:

- **KILL file.** Creating an empty file `<root>/_gateway/KILL` kills the gateway in every mode within one cycle. It is unauthenticated by design; the control is who may create files in `<root>/_gateway`. Restrict that folder to a small OS group (the operators' kiosk account and the service account) and keep it out of shared drives.
- **Trade-off.** The file trigger is fast and survives a broken API, but anyone who can write the folder can stop writes (a nuisance, not a danger: kill only removes authority). If the site cannot protect the folder, switch it off with `"kill_file_enabled": false` or start the gateway with `--no-kill-file` (`--allow-kill-file` forces it on and wins over the file). Then Kill needs a signed-in session or direct DCS action.

The DCS and plant interlocks never depend on this software.

## 7. Backup and key rotation

Back up `<root>/_auth/` (`users.json`, `roles.json`, `config.json`, `auth-audit.jsonl`), the `_gateway` audit and policy files, and the secrets directory with the HMAC key, as listed in runbook section 9. Keep the audit copy on a second machine or write-once media: the hash chain shows edits but not truncation. Rotate the key as described in runbook section 8 (the gateway must be stopped, the policy re-pinned, the old audit log archived); a lost key blocks all writes except kill.

### Backup and restore in the console (#167)

Administration > Backup (permission `users.manage`, so administrators only). The backup holds configuration, not history.

| In the backup | Left out |
|---------------|----------|
| Site catalogue (`_site`), module configurations and models (`_anomaly`, `_softsensor`, `_fuzzy`, `_supervisor`), saved trend charts (`_trends`), gateway policy, pin and draft (`_gateway/policy`, `policy-draft.json`), `plant-map.json`, users, roles and settings (`_auth/users.json`, `roles.json`, `config.json`) | Datasets and every Parquet file (history stays in the source historian), `_runtime`, `_advisory`, `_uploads`, live gateway queues, `_tuning` proposals, caches and temporary files, earlier backups (`_backup`) |
| A copy of the audit logs (`_auth/auth-audit.jsonl`, `_gateway/audit.jsonl`) as evidence | Secrets: the OS secret store (source passwords and tokens) and `_secrets` (gateway key) are never exported |

- **Secrets must be re-entered.** The manifest and the dry-run report list the source credentials (by reference name) and the gateway key file to enter or copy again on a new machine. Backup files contain the password hashes of the accounts: store them like the data root.
- **Download.** The zip has `manifest.json` (format version, creation time, a sha256 per file, the exclusions and the secrets list). Download needs a fresh password confirmation and writes `backup_created` to the audit.
- **Restore.** Upload the zip and press Check backup: the dry run verifies the manifest, every hash and the layout version of versioned files, and lists each file as add, replace, remove or unchanged without touching anything. A tampered or damaged archive, a path outside the scope, and a backup written by a newer format or newer file layout are refused. Restore needs the confirmation box, a fresh password confirmation, and restores exactly the archive that was checked. Audit logs are never replaced: the live chains stay intact and the audit gets `backup_restored` before the first file changes.
- **Safety net.** Before any file changes the current configuration is saved as `<root>/_backup/pre-restore-<time>.zip` (the newest five are kept). Files are staged first and swapped in one by one with atomic replaces; a failure during the swap puts the safety copy back. To undo a restore, restore that safety copy.
- **After a restore.** Reload the gateway policy (`policy_reload`, only in `off` or `advisory`) and restart the API and gateway if `roles.json` or `config.json` changed (they are read at start-up). A policy pin is signed with the gateway key: on a machine with a different key, pin the policy again with two distinct people.
- **What the confirmation binds.** The restore request carries `confirm=<sha256 of the zip>`: the server refuses it unless the uploaded bytes are exactly the archive whose dry run you saw, and it runs every validation again before touching a file. Download, check and restore are all audited (`backup_created`, `backup_inspected`, `backup_restored`) and need the fresh password confirmation. Archives with an unpacked size above 512 MiB, or a member (1 MiB or more) compressed more than 200 times, are refused.
- **A killed process can leave a partial restore.** The swap replaces files one by one. A failure inside the process is rolled back, but a hard kill (power loss, `kill -9`) in the middle is not. To recover: (1) stop the API and the gateway; (2) take the newest `<root>/_backup/pre-restore-<time>.zip`, made just before that restore; (3) unzip it to a scratch folder and copy its files over `<root>` with the same relative paths (skip `manifest.json` and the audit logs), or start the API and restore that zip in Administration > Backup; (4) delete leftover `<root>/_backup/staging-*` folders. If the automatic rollback itself fails, the API answers `rollback_failed` and audits `backup_rollback_failed`: use the same steps. On POSIX systems the restored `_auth` files and the audit file get mode 0600.
- **No lock-out.** Check that the restored `users.json` contains an administrator you can sign in as; the dry run lists `_auth/users.json` as replaced.

## 8. What is NOT protected (threat model summary)

Crosscut protects against unauthenticated browser users, operators exceeding their role, forged or replayed inbox files, and one person raising authority alone. It does not protect against:

- a compromised API or gateway service account, which can read the signing key;
- local administrator or root on the host, who can edit users, roles, settings and the audit log (edits are detectable, truncation is not);
- session theft by someone with a network position: use HTTPS and keep the API on a firewalled plant VLAN;
- a person who knows another person's password.

Deployment mitigations: separate service accounts for API and gateway, a secrets directory readable only by them, an inbox writable only by the API account, and no interactive logins on service accounts. These settings are guardrails inside the software; the DCS remains the last line of defence.

## 9. Parameter write intents and reconciliation

Before the gateway writes PID parameters to the DCS, it records an intent file on disk (`<root>/_gateway/param_intents.json`). If the gateway process or host crashes mid-write, the intent stays open on restart.

- **What an open intent means:** The gateway may have written some, all, or none of the intended parameter values to the DCS before interruption. To prevent conflicting or inconsistent writes, any subsequent parameter write to that loop is blocked with `reconcile_required`.
- **How to resolve an open intent:** A qualified engineer or lead inspects the current parameter values directly at the DCS console and compares them with the intended values listed in the Tuning view or gateway status. Once the physical controller state is verified or corrected, the operator resolves the intent via the Tuning view (or `POST /tuning/intents/{key}/resolve`), which requires `gw.approve.tuning` authority plus password step-up confirmation. Resolving the intent removes the block and allows new parameter proposals; it never writes to the plant.
- **Damaged intent file:** If `param_intents.json` is corrupted, truncated, or unreadable, the intent store enters the `damaged` state. A damaged intent file blocks all parameter writes across all loops to prevent writing over an unreadable intent. The gateway and API report this state rather than crashing. To recover, an administrator must check the DCS controller states first, and then either repair the JSON syntax or remove the damaged file.

## Docker Compose deployment (Linux on-prem, #169)

The Compose stack runs the same three processes as the systemd units, each in its own container and
from one image: `api` (console and JSON API), `runtime` (scheduler and jobs) and `gateway` (the only
process with authority to write to the plant, ADR 012). The files live in `deploy/docker/`.

| Container | Writes | Reads |
|-----------|--------|-------|
| `api` | data root, gateway mailbox (`_gateway`) | everything in the data root |
| `runtime` | data root, gateway mailbox (`_gateway`) | everything in the data root |
| `gateway` | only its own `crosscut-gateway` volume (`_gateway`: policy, audit, state, inbox/outbox, key) | data root **read-only** (plant map, `_auth/config.json`) |

Two named volumes hold the state: `crosscut-data` is the data root and `crosscut-gateway` is the
gateway folder. Docker copies the image's ownership into an empty volume: the data root belongs to
the API account (`10001:10000`), the gateway folder to the gateway account (`10002:10000`).

### Install and first start

1. Install Docker Engine 24 or newer with Compose v2 on the Linux host, then check out the repository.
2. Create the site env file **outside the repository**. It holds settings, never a committed secret:
   `sudo install -d -m 0750 /etc/crosscut`,
   `sudo cp deploy/docker/.env.example /etc/crosscut/crosscut.env`,
   `sudo chmod 0600 /etc/crosscut/crosscut.env`, then edit it. Every variable is documented in the
   example; the defaults are safe for a first start.
3. Build and start the stack:
   `docker compose -f deploy/docker/docker-compose.yml --env-file /etc/crosscut/crosscut.env up -d --build`
4. Create the first administrator and the gateway HMAC key in one step. The command writes the key to
   `<secrets dir>/gateway-hmac.key` with mode 0640, readable by the gateway through the shared group:
   `docker compose -f deploy/docker/docker-compose.yml --env-file /etc/crosscut/crosscut.env run --rm -it --user 10001:10000 api python -m crosscut_api.auth_cli init --root /var/lib/crosscut --username admin`
5. Put the site plant map into the data root and make it group-readable:
   `docker compose -f deploy/docker/docker-compose.yml --env-file /etc/crosscut/crosscut.env cp deploy/examples/plant-map.example.json api:/var/lib/crosscut/plant-map.json`,
   then `docker compose -f deploy/docker/docker-compose.yml --env-file /etc/crosscut/crosscut.env exec --user 0 api sh -c 'chown 10001:10000 /var/lib/crosscut/plant-map.json && chmod 0640 /var/lib/crosscut/plant-map.json'`.
6. Enter the write policy in the console and pin it with two distinct people (section 3). The gateway
   starts in `advisory`; change `CROSSCUT_GATEWAY_MODE` only after the policy is pinned and tested.
7. Open `http://<host>:8000/` for the console. The JSON API is under `/api` on the same port; the
   gateway has no published port. Put a TLS reverse proxy in front for remote access.

The gateway container starts with `restart: on-failure:5`: a configuration error (missing policy,
pin, plant map or key) is not retried forever, matching `RestartPreventExitStatus=2` in the systemd
unit. Fix the cause and run
`docker compose -f deploy/docker/docker-compose.yml --env-file /etc/crosscut/crosscut.env up -d gateway`
again.

### Upgrade

Back up first (below), then rebuild or pull and recreate the containers. Volumes are kept:

```
docker compose -f deploy/docker/docker-compose.yml --env-file /etc/crosscut/crosscut.env build --pull
docker compose -f deploy/docker/docker-compose.yml --env-file /etc/crosscut/crosscut.env up -d
```

With a registry image, replace `build --pull` by `pull`. Restarting the API signs everybody out
(section 5). If `roles.json` or `config.json` changed, restart the gateway too. After a restore or a
key change, reload and re-pin the policy as described in section 7 and the runbook.

### Backup the volumes

Stop the stack for a consistent copy, archive both volumes, then start it again:

```
docker compose -f deploy/docker/docker-compose.yml --env-file /etc/crosscut/crosscut.env stop
docker run --rm -v crosscut-data:/data:ro -v "$PWD":/backup alpine:3.20 tar czf /backup/crosscut-data-$(date +%F).tgz -C /data .
docker run --rm -v crosscut-gateway:/data:ro -v "$PWD":/backup alpine:3.20 tar czf /backup/crosscut-gateway-$(date +%F).tgz -C /data .
docker compose -f deploy/docker/docker-compose.yml --env-file /etc/crosscut/crosscut.env start
```

The gateway archive contains the HMAC key, the audit log and the policy. Store it like the data root
and keep a second copy off the machine; section 7 and the runbook explain what a backup holds and
what must be re-entered. Restoring is the reverse: stop the stack, unpack into the volume with a
temporary `alpine` container, fix ownership (`10001:10000` for `crosscut-data`, `10002:10000` for
`crosscut-gateway`), then start.

### Logs and health

`docker compose -f deploy/docker/docker-compose.yml --env-file /etc/crosscut/crosscut.env ps` shows
the health state of all three containers; each has a healthcheck (the API probes `/healthz`, the
runtime and gateway check that their `state.json` is fresh). Follow the container logs with:

```
docker compose -f deploy/docker/docker-compose.yml --env-file /etc/crosscut/crosscut.env logs -f --tail=200 api runtime gateway
```

Application evidence stays in the volumes: `_runtime/log.jsonl` for job runs and
`_gateway/audit.jsonl` for every gateway decision and write. The Compose logging driver keeps five
10 MiB files per container; copy the audit log off the machine daily as the runbook requires.

### Secrets

- **Never commit a secret.** The site env file lives outside the repository (`/etc/crosscut/crosscut.env`,
  mode 0600). `deploy/docker/.env.example` is a template with empty values.
- **Gateway HMAC key.** It is created by `auth_cli init` or `auth_cli rotate-key` inside the
  `crosscut-gateway` volume at `_gateway/secrets/gateway-hmac.key`, owner `10001:10000`, mode 0640.
  It must stay a file: the gateway refuses a key that is world-readable, which is how Docker secrets
  are mounted (0444), so a Docker secret cannot replace it. The API and gateway share it through the
  `crosscut-sec` group.
- **Other credentials** (for example `PI_READ_TOKEN` for the PI Web API connector) go into the env
  file outside the repository or a Docker secret mounted under `/run/secrets`. The gateway container
  does not receive the env file, so source credentials never reach the write path.

## PI Web API connector (Phase 5, issue #49)

PI reads use `pi` (or `piwebapi`) and point WebIds as tag addresses. Example source:

```json
{
  "id": "historian",
  "driver": "pi",
  "base_url": "https://pi.example.invalid/piwebapi",
  "data_server": "SYNTHETIC",
  "auth": {"kind": "bearer", "credential_env": "PI_READ_TOKEN"}
}
```

Set the named environment variable in the service environment. Never put credentials in a
site file, endpoint URL or options. Basic authentication uses the same `credential_env`
field; its environment value is `username:password`. Use HTTPS. Kerberos requires an injected
GET transport that implements Negotiate using the service identity; the stdlib transport
fails clearly when Kerberos is selected rather than silently sending unauthenticated requests.

`web_id` selects a data server directly; otherwise `data_server` is resolved through
`GET /dataservers`. With neither selector, root browsing lists servers. Optional driver
`options.name_filter` filters point browsing; `options.max_count` sets recorded page size
(default 1000 events, minimum 2). Recorded requests continue at the last timestamp and discard
the repeated boundary event. A stalled timestamp raises an error rather than losing data.
A positive `period_s` requests interpolated history with an interval in seconds.

History returns a mapping from point WebId to sample dictionaries (`timestamp_utc`, `value`,
`quality`, `reason`). PI Good=false and system digital states are bad (2); Questionable or
Substituted is uncertain (1), otherwise numeric values are good (0). System states preserve
their name in history reasons and snapshot reasons, with a null numeric value. Snapshot
communication failures return all requested values bad with `comm_ok=false` and a reason;
explicit browse/history/live reads raise `SourceConnectionError`. Snapshot reasons can also
identify bad values when communication succeeds. Writes remain exclusively in the gateway.

Protocol reference: [AVEVA PI Web API](https://docs.aveva.com/bundle/pi-web-api-reference/page/help/getting-started.html).
Real-server authentication and performance checks remain owner tasks; tests use synthetic fixtures.

## Health and log export (issue #170)

**Administration > Health** shows one read-only table, refreshed every 10 s, each row ok, warning or error with a reason:

- **Runtime:** running, stopped, never started or stale (its state file older than 30 s), with uptime. Jobs: one row per enabled job with last run, last success, last error, overrun count and lag. A job is *late* (warning) after 2 periods without a run, *overdue* (error) after 5, and an *overrun* is counted when a run starts more than 2 periods after the previous one.
- **Gateway:** state file fresh (10 s), mode (mode `off` is a warning), and the beats of the runtime and of each controller as the gateway sees them (a lost beat is an error).
- **Audit:** time of the last audit write (gateway chain and sign-in log) and the gateway chain check.
- **System:** free space on the data root (warning below 10 % or 5 GiB, error below 5 % or 1 GiB) and the installed package versions (warning when they differ).

Everyone who may open the Runtime page (`data.view`) may read it; the API route is `GET /admin/health`.

**Log export** (`GET /admin/logs/export?start=<ISO>&end=<ISO>`, button on the Health page) needs `users.manage`. It returns a zip with the lines of the chosen range (default: the last 24 h) of every log file that exists, and writes a `log_export` record (who, range, files) to the sign-in audit chain. Passwords, tokens, API keys, cookies, `Authorization` headers, URL credentials and private key blocks are replaced by `[redacted]`; the scrubbing is pattern based, so still read an export before sending it outside the site.

Where the logs are: each process writes `<root>/_logs/<api|runtime|gateway>.log` (rotating, UTC time stamps) when it is started with its entry point (`python -m crosscut_api --root <root>`, `python -m crosscut_runtime`, `python -m crosscut_gateway`; the Windows and systemd wrappers in `deploy/` already do). The runtime job log `<root>/_runtime/log.jsonl` is exported too. Defaults, changed by environment variables of the process: `CROSSCUT_LOG_LEVEL=INFO`, `CROSSCUT_LOG_MAX_BYTES=5000000` per file, `CROSSCUT_LOG_BACKUPS=5` rotated files. An API started another way (for example `uvicorn` directly) writes no `api.log`, and the export then holds only what the other processes wrote. Each component log file assumes **one writer process**: do not start the API with `uvicorn --workers` or `--reload` in production (rotation would corrupt the file). A plain `uvicorn` start writes no `api.log` at all. The export refuses a range longer than 31 days or more than 100 MB of log text (422 with the reason) and needs a fresh step-up (password re-entry). The systemd unit of the API needs write access to `_logs` and `_auth` (the unit in `deploy/` grants both).
