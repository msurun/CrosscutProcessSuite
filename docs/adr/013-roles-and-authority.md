# ADR 013: Roles and authority

Status: **Accepted (implemented; owner questions open)**
Implementation status 2026-11-03: steps 1 and 5 done (d9376e3); steps 2-4, 6-8 in progress.
Date: 2026-11-03
Builds on: ADR 011 (write path) and ADR 012 (writes are a product capability). Tracked as issue #47, owner decision 9.

## Context

ADR 012 makes the Write Gateway the only process that writes to the control system and requires authentication and roles before
`confirm` mode. Today the gateway is a separate process, and the API does not enforce any of it: every API route is open, and any
file in `<root>/_gateway/inbox` commands the gateway. The audit log has no actor, so a write cannot be traced to a person.

Principle: **the gateway holds authority; the API only presents it.** The API authenticates people and forwards their identity
and roles, signed, to the gateway. The gateway decides what is allowed, using its own mode and target state, and never trusts
the API's view of the world.

## Decision

### 1. Roles

Roles are explicit permission sets. There is no inheritance: each role lists every permission it holds. A user may hold several roles.

| Role | Permissions |
|------|-------------|
| `viewer` | `data.view`, `gw.view`, `audit.view`, `gw.kill`, `gw.mode.down`, `gw.reject` |
| `operator` | `viewer` + `analysis.run`, `job.stop`, `gw.approve`, `gw.reject`, `gw.re_enable.hold_off` |
| `engineer` | `operator` + `data.import`, `config.edit`, `connector.use`, `job.manage`, `gw.propose`, `gw.approve.tuning`, `gw.mode.up.advisory`, `gw.mode.up.dry_run`, `gw.mode.up.confirm`, `gw.re_enable.stopped`, `policy.edit` |
| `lead` | `engineer` + `gw.mode.up.supervised`, `gw.kill.reset`, `policy.pin`, `policy.reload` |
| `admin` | `viewer` + `users.manage` (no process authority) |
| `service` | runtime jobs, actor `svc:runtime`: `gw.propose` only |

Small teams may give one person `admin` and `lead`. `admin` carries no process authority by itself.

### 2. Gateway rules

- Mode goes up one step at a time, and never above the policy cap.
- Mode goes down by any jump, for any human role.
- The approver of a write must differ from its proposer.
- Approving a queued PID parameter set (ADR 014) needs `gw.approve.tuning` (`engineer`, `lead`); `gw.approve` alone is not enough. The `service` role (actor `svc:runtime`) may never propose a parameter set (`service_cannot_propose_tuning`). Operators can still reject one (`gw.reject`).
- Kill reset sets the mode to `advisory` and every target to `stopped:kill`. Each target then needs `gw.re_enable.stopped` to re-enable.
- Policy two-person rule: an engineer edits a draft; a lead who is not the author pins it, with a password step-up.
- Policy reload is allowed only in `off` or `advisory` mode.
- An operator can ALWAYS: kill, lower the mode, reject pending proposals, stop jobs, view everything, and take over at the DCS (hold-off).

Code-forced invariants (enforced in code, not configuration):

- `kill`, `mode.down` and `gw.reject` are held by every human role.
- The two-person rule cannot be disabled.
- A roles file that breaks any of these is refused at load, and the shipped default is used instead.
- The shipped `schemas/auth-roles.default.json` already includes `gw.reject` in `viewer`.

### 3. Authentication

Users are stored in `<root>/_auth/users.json`. Each user record has these fields: `username`, `display_name`, `roles[]`, `disabled`,
`must_change_password`, `password` (object: `alg` scrypt, `n`, `r`, `p`, `salt_b64`, `hash_b64`), `created_at`,
`password_changed_at`, `failed_logins`, `locked_until`, and `source` (`local`; LDAP is reserved behind a `UserStore` protocol).

Password hashing:

- `hashlib.scrypt` with `n=2^15`, `r=8`, `p=1`, `dklen=32`, `maxmem=64MiB`.
- 16-byte random salt. The parameters are stored with each hash. Tests use `n=2^10`.
- Minimum length 12 characters.
- Unknown usernames are checked against a dummy hash, so response time does not reveal which usernames exist.
- Comparison uses `hmac.compare_digest`.

Sessions:

- Opaque cookie `cc_session = secrets.token_urlsafe(32)`, flags `HttpOnly`, `SameSite=Strict`, `Path=/`, and `Secure` when served over HTTPS.
- Server-side in-memory store keyed by `sha256(token)`, holding `{user, csrf, created, last_seen, ip, last_stepup}`.
- Idle timeout 60 minutes; absolute timeout 12 hours.
- A restart logs everyone out.
- Roles are re-read from the users file on every request, through an mtime cache, so role changes take effect without a new login.

Step-up: re-entering the password, valid for 5 minutes, is required for `mode.up.supervised`, `policy.pin`, `kill.reset` and `users.manage`.

Lockout and rate limits:

- Five failed logins lock the username for 5 minutes. Each further lock doubles the duration, up to 60 minutes.
- 20 login attempts per minute per IP address.

Bootstrap is by command-line only: `python -m crosscut_api.auth_cli init` creates the first admin, `users.json` and the HMAC key. There is no HTTP setup route. Without `users.json`, protected routes return `503 not initialised`.

Secrets:

- Secrets directory: `CROSSCUT_SECRETS_DIR`, default `<root>/_secrets/`.
- Linux: accounts `crosscut-api` and `crosscut-gw` in group `crosscut-sec`. The key file is mode 0640, `users.json` is 0600. Both processes refuse to start if these files are world-readable.
- Windows: the same restriction is applied with `icacls`.

### 4. Gateway enforcement

Commands travel as a signed envelope, version 2:

```
{ id, cmd, args,
  auth: { actor, roles[], session (first 16 hex of sha256 of the session token),
          source_ip, issued_at_ns, nonce (32 hex) },
  sig }
```

`sig` is HMAC-SHA256 over the canonical bytes of everything except `sig`, reusing `policy_file.canonical_bytes`.

The gateway checks, in this order:

1. Signature, compared with `compare_digest`.
2. `issued_at_ns` within +/- 30 seconds of the gateway clock.
3. Nonce not present in the 120-second nonce cache (ids are unique).
4. Its own `authorize(roles, cmd, args, current_mode, target_state)`, using the gateway's own mode and target state, not the API's.
5. Approver differs from proposer.

Any failure moves the file to `rejected/` with a reason, and writes an audit event `auth_reject`.

Unsigned commands: only `kill` is accepted, and the audited actor is `unsigned`. A file named `<root>/_gateway/KILL` is honoured without a signature, so OS group members (operators) can stop the process without logging in.

Missing, short (under 32 bytes) or unreadable key: fail closed. The gateway accepts only `kill` and `mode.down`, refuses to rise above `advisory`, and `state.json` reports `auth: key_missing`.

Policy pin: `policy.pin.json` with `{digest, author, approver, approved_at, sig}` replaces the `.sha256` sidecar. It is refused unless the signature is valid and `author != approver`.

Roles file: both processes load it at start. The gateway audits a `roles_loaded` event with the file digest.

### 5. Audit

- Engine methods take a keyword argument `actor_ctx`.
- Each audit record gains `actor`, `roles` (comma-joined), `session`, `source_ip` and `cmd_id`.
- Events raised by the gateway itself have actor `gateway`.
- The hash chain and `RESERVED_KEYS` are unchanged.
- The API keeps `<root>/_auth/auth-audit.jsonl` through `AuditLog`. It records login ok and fail, lockout, logout, and user and role changes.

### 6. Schemas

- `schemas/auth-users.schema.json`: `version` const 1; `users[]` with `additionalProperties` false; `username` matches `^[a-z][a-z0-9._-]{2,31}$`; `roles` minItems 1; `password.alg` enum `[scrypt]`, `n` >= 1024; date-time strings; `locked_until` nullable.
- `schemas/auth-roles.schema.json`: `version`; `roles` is a map from role name to `{description, permissions[]}`, where `permissions` is an enum of the permission ids; no `inherits` key; `additionalProperties` false.
- The default table is also shipped in code as `DEFAULT_ROLES`. A test checks that the JSON file matches it.

### 7. API

- `POST /auth/login` (public), `POST /auth/logout`, `GET /auth/me` returning `{user, roles, permissions, csrf}`, `POST /auth/password`, `POST /auth/stepup`.
- `CRUD /auth/users` requires `users.manage`. An admin cannot change their own roles.
- Default deny: a dependency rejects every route unless it is on the allowlist (`login`, `health`).
- Central `ROUTE_PERMISSIONS` table. An inventory test fails for any route missing from it.

Route to permission mapping:

- `data.view`: all GETs on the datasets, loops, knowledge, site, catalogue, schemas, config, runtime, onboarding and analysis routers, and the connector source list.
- `analysis.run`: POSTs that only compute: steps, valve-test plan, analyse and analyse-csv, catalogue/suggest, intake preview and check. Classify POSTs in fuzzy, supervisor, anomaly and softsensor are `analysis.run`, except any that save files, which are `config.edit`.
- `data.import`: `/intake/dataset` and `/intake/plant/*`.
- `config.edit`: PUT site, catalogue/mapping, `config/{kind}/{id}`, knowledge.
- `connector.use`: connector source test, browse and read-live.
- `job.manage`: runtime job POST, PATCH, DELETE and start.
- `job.stop`: job stop.
- Gateway: status and pending need `gw.view`; audit needs `audit.view`; approve needs `gw.approve`; reject needs `gw.reject`; kill needs `gw.kill`; re-enable is by target state (`gw.re_enable.stopped` or `gw.re_enable.hold_off`); PUT mode is checked per transition.
- New: `POST /gateway/kill/reset` (`gw.kill.reset`), `GET` and `PUT /gateway/policy/draft` (`policy.edit`), `POST /gateway/policy/pin` (`policy.pin`), `POST /gateway/policy/reload` (`policy.reload`).

CSRF: `SameSite=Strict`, plus the header `X-Crosscut-CSRF` on every non-GET request, which must equal the session's `csrf` value, plus an Origin allowlist.

`FileGatewayClient` signs every command with the request's actor context.

### 8. GUI

- Login page.
- A 401 response triggers an interceptor that returns to the login page.
- Header shows the user, a role badge and a logout control.
- Kill is always visible, to every role.
- `useCan(perm)` hook. Controls the user may not use stay focusable with `aria-disabled`, and the reason is given through `aria-describedby`.
- Step-up modal for the four step-up actions.
- Users page (admin only).

### 9. Tests

- Password hashing.
- Lockout and its expiry, with a fake clock.
- Full role by permission matrix.
- Exhaustive mode transition table (5 modes by roles).
- Envelope: tamper of each field, replay, stale timestamp, missing key.
- Self-approval refused.
- Policy pin with author equal to approver refused.
- Roles file that strips `kill` refused.
- The 12 gateway scenarios rerun with a signing fixture.
- API: 401 on every non-public route, parametrised over `app.routes`; 403 samples; missing CSRF gives 403; rate limit; `/auth/me` response shape.
- End-to-end browser tests with axe.

Testability: injected clock, an `AuthConfig` dataclass, a fake `UserStore`, and a `client_as(role)` pytest fixture.

### 10. Implementation order

1. Gateway `authz.py`, `envelope.py`, the schemas and their tests. Whitelist in guards.
2. `service.py`: envelope check, nonce cache, `authorize`, KILL file, missing-key mode.
3. `engine.py`: `actor_ctx`, `reset_kill`, proposer differs from approver, roles reload.
4. `policy_file.py`: `policy.pin.json`.
5. API `auth/` package: `passwords`, `store`, `sessions`, `deps`; then `auth_routes.py` and `auth_cli.py`.
6. `ROUTE_PERMISSIONS` with the inventory test; signing in `gateway_client`.
7. Users admin routes, auth audit log, policy draft and pin routes.
8. Frontend: login, role badge, disabled-with-reason controls, header Kill, step-up, Users page, end-to-end tests.

### 11. Threat model

Protects against:

- unauthenticated browser users;
- operators exceeding their role;
- forged or replayed inbox files;
- a single person raising authority alone.

Does NOT protect against:

- a compromised API or gateway service account, which can read the key;
- local admin or root, who can edit `users.json`, the roles file and the audit log. The hash chain shows that edits were made but not that records were truncated;
- session theft by someone with network position. Mitigations: HTTPS (self-signed is acceptable) and a firewall to the plant VLAN.

Mitigations in deployment:

- Separate service accounts for API and gateway.
- Secrets directory readable only by those accounts.
- Inbox writable only by `crosscut-api`.
- No interactive logins on those accounts.
- Daily audit copy to write-once media, or the last hash logged on a second machine.

The DCS remains the last line of defence. Operator takeover and plant interlocks do not depend on this software.

## Consequences

- Every write is traceable to an authenticated person, or to the `svc:runtime` service account, in the audit log.
- Raising authority needs two people for policy changes, and a second person for every approval. A single person cannot raise the mode alone; an operator can always lower it.
- A lost signing key locks all writes except `kill`. This is intended. Recovery: `auth_cli rotate-key`.
- Shift work is subject to the session timeouts (60 minutes idle, 12 hours absolute), and any restart logs everyone out.
- The gateway no longer trusts the API's view of modes or targets; it re-authorises every command with its own state.
- The three owner questions below must be answered before this ADR moves from Proposed to Accepted.

## Open owner questions

Defaults below are implemented as configuration and can be changed without code changes.

1. Only `lead` may enable `supervised` and pin the policy. Who holds `lead` on site?
2. Accounts are personal only. Must `kill` work without a login (kiosk)? Default: `kill` works through the KILL file or the OS group.
3. Are 12-hour absolute and 60-minute idle sessions acceptable for shift work?
