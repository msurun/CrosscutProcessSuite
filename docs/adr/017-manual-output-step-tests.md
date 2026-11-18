# ADR 017: Bounded OUT tests in MAN

Status: Implemented for simulator validation; owner decision 2026-11-17, issue #81.
Amends ADR 011, ADR 012 and ADR 014 for this target kind only. ADR 016 handover is unchanged.

The Write Gateway accepts `out_step` targets with explicit loop identity, OUT limits,
PV trip limits, maximum absolute amplitude, maximum duration in seconds and read-back
tolerance. Values outside site bounds are refused, never clamped. Schema descriptions
suggest conservative initial settings of one output engineering unit and ten seconds;
the site must supply every safety bound. Schemas contain no `default` keywords.

The operator puts the loop in MAN at the DCS. Crosscut never changes the loop mode.
Starting a test is an explicit human confirmation requiring `gw.approve.tuning`, through
`POST /gateway/output-tests` and the authenticated `start_output` gateway command.
The global gateway mode must be exactly `confirm`; even `supervised` is refused.
Service actors cannot start tests. Cancellation requires `gw.reject` and uses
`POST /gateway/output-tests/{target}/cancel` and `cancel_output`.

The baseline is live OUT, not a value supplied by the browser. The requested value is
`baseline + signed amplitude`, in the site's OUT engineering units. Before the first
possible write, the gateway atomically persists an open intent in `out-intents.json`.
The intent records both baseline and intended OUT. A second live mode/PV check precedes
the write. Each write is verified using the configured read-back node and tolerance.

Every gateway cycle monitors live MAN mode and PV. PV reaching either trip boundary,
deadline expiry, communication loss, mode change, kill or operator cancellation aborts
the test and attempts to return OUT to its pre-test value. Restoration is verified by
read-back before the intent closes. A disconnected DCS cannot acknowledge restoration:
the target remains `reconcile_required`, raises a check-DCS alarm, retains its baseline,
and retries on later cycles. No success is reported merely because a write was attempted.

A crash leaves the durable intent open and blocks new tests on that loop. Startup never
silently resumes a test or clears its baseline. An explicit cancel/restore action can
restore a crash intent; the same read-back and audit requirements apply. The gateway
audits refusals, intent creation, verified writes, abort reasons, restoration failures,
restoration success and open intents found at startup. An audit-storage failure must
not prevent a physical restoration attempt; it prevents claiming a closed intent.

The Steps view keeps historical analysis and the live confirmation separate. It explains
MAN, site bounds and abort behaviour in English, Polish and Spanish. Unit tests cover
each trip, reconnect and restart. The pinned L5 OUT row exercises live RougherSim OUT
read-back and restoration; browser tests cover confirmation/cancel and axe accessibility.
Simulator evidence does not replace the owner's site commissioning procedure.
