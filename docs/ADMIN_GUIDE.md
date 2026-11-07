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

## 8. What is NOT protected (threat model summary)

Crosscut protects against unauthenticated browser users, operators exceeding their role, forged or replayed inbox files, and one person raising authority alone. It does not protect against:

- a compromised API or gateway service account, which can read the signing key;
- local administrator or root on the host, who can edit users, roles, settings and the audit log (edits are detectable, truncation is not);
- session theft by someone with a network position: use HTTPS and keep the API on a firewalled plant VLAN;
- a person who knows another person's password.

Deployment mitigations: separate service accounts for API and gateway, a secrets directory readable only by them, an inbox writable only by the API account, and no interactive logins on service accounts. These settings are guardrails inside the software; the DCS remains the last line of defence.
