# ADR 018: Explicit bumpless controller initialisation

Status: Implemented; independent safety review pending.
Date: 2026-11-26
Builds on: ADR 013-017. Issue #153, PRODUCT section 3, Write Gateway gap.

## Decision

Every controller acquisition starts by tracking the current target read-back. This applies
to switch-on in supervised mode, approval in confirm mode, controller restart or liveness
recovery, and reacquisition after operator takeover and explicit gateway re-enable. Ordinary
beats do not restart initialisation. A controller starting again while its previous hold
remains must initialise again. Failed or refused writes do not complete initialisation.

The fuzzy controller is incremental: `SP_next = SP_read + delta` in target engineering units.
It has no integral accumulator. Initialisation replaces its previous-output map (`base_sp`,
one finite scalar SP per MV), refreshes it on the first proposal cycle, and sets `delta = 0`
for that cycle. Subsequent cycles apply the existing fuzzy rules and limits. The host's
existing state machine calls initialisation on entry to on, including entry from advisory
or recovery after shed; a restart still requires an explicit switch-on. Future controllers
with integral state must implement tracking in their `initialise` method: for an additive
controller `u = P + I + D + FF`, set `I = u_read - P - D - FF`, in output units, and track
previous output at `u_read` before issuing the first proposal.

The gateway independently tracks acquisition per controller and target. It evaluates the
proposal with live SP rather than an old gateway write as its baseline, retaining write
timestamps and all timing restrictions. Immediately before the first write it reads again.
The existing signed target policy's `max_step` is also the configured acquisition bump limit,
in target engineering units: `abs(policy_screened_candidate - fresh_readback) <= max_step`.
Exceeding that limit refuses the write with `bumpless_bump_limit`; it is not repaired by
another clamp. Nonfinite or out-of-range final read-back refuses with
`bumpless_readback_invalid`. These refusals use the normal audited decision and idempotency
path. A different proposal is required to retry.

An accepted acquisition writes exactly that fresh read-back, records
`bumpless_initialisation` before write intent, and returns the actual value in the decision.
Its first physical move is therefore zero. An unchanged first proposal is allowed only
after all preceding policy checks pass; ordinary unchanged proposals remain refused.
Confirm mode repeats screening and live reads at approval, and rechecks controller/runtime
liveness. Queueing alone never completes initialisation.

## Boundaries and consequences

Authentication, two-person confirmation, kill, mode/source guards, engineering limits,
minimum interval, rate/step clamps, watchdogs, read-back monitoring, liveness and operator
hold-off remain mandatory. Initialisation grants no remote-taking authority under ADR 016.
The adapter remains the only writer. Transport and audit failures prevent acquisition.

Current runtime controllers target SP only. OUT writes remain the distinct human-confirmed
bounded MAN tests of ADR 017: their live OUT baseline and restoration intent must not be
replaced by a controller tracking operation. This change introduces no controller OUT path
and no PID tuning algorithm. A future controller OUT target must apply the same tracking
rule to OUT read-back before control moves; it cannot reuse the manual test permission.

Separate read and write operations cannot guarantee atomicity against a simultaneous DCS
operator edit. Existing adapter handover guards and subsequent read-back checks remain the
defence; no real-DCS conformance is claimed. Tests use synthetic plants and snapshots.

No schema change or published numerical method is introduced. Policy configuration reuses
`max_step`; no extra policy field or unpinned runtime option is added.
