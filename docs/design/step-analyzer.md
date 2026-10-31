# Step analyzer (design, 2026-10-23)

Why: the real plant data contain many tests (OUT steps in manual, SP steps in auto, pump speed steps). Each test must be
found, aligned with the test labels / logbook, and fitted with an honest uncertainty, so a future MPC identification and
every later test reuse one tool. Analysis only: nothing writes to a plant.

## Pipeline (per loop of a dataset)
1. `step_events.find_step_events(t_s, pv, sp, out, mode, dt_s)` -> list of `StepEvent`.
2. `step_fit.fit_step(window, kind)` -> `StepFit` (FOPDT or IPDT with standard errors and a verdict).
3. `step_analyzer.analyze_steps(t_s, pv, sp, out, mode, *, loop_id, process_kind, unit, test_windows, logbook)` -> JSON dict.
4. HTTP: `POST /datasets/{id}/steps` (body: `loop`, optional `logbook`, optional `kind`) -> payload of step 3.
5. GUI: view "Steps" (Kroki).

## Model and method (numpy only, no scipy)
Window = samples `t_s[i0:i1]` around one event; y = PV, u = OUT (measured, whatever moved it), time zero at window start.
- FOPDT (self-regulating): y(t) = y0 + beta*t + K * x(t), where x is the response of a first-order lag with time constant
  tau to the delayed input: x' = (u(t - theta) - u_ref - x)/tau, x(0)=0, u_ref = mean of u over the first `pre` samples
  (pre-event baseline). Exact discretisation per sample (alpha = exp(-dt/tau)), u delayed by linear interpolation.
  For a fixed (theta, tau) the model is LINEAR in (y0, beta, K): variable projection. Scan theta on a grid
  (0..theta_max step dt/2) and tau on a log grid (dt..tau_max, 25 points), pick the best SSE, refine (finer grid around the
  best cell). Report K, tau, theta with standard errors: SE(K) from the linear least-squares covariance at the optimum,
  inflated by sqrt(n/n_eff) for residual autocorrelation (n_eff = n * (1 - r1)/(1 + r1), r1 = lag-1 autocorrelation of the
  residuals, clipped to [0.05, 1] of n); tau and theta get profile-SSE intervals (F-test 95 %, same idea as
  `identification_ipdt._delay_interval`), reported as `se` = half of the 68 % width approx (simply interval / 1.96).
- IPDT (integrating, level): y(t) = y0 + beta*t + k * integral_0^t (u(s - theta) - u_ref) ds, k in PV unit per second per
  OUT unit. Linear in (y0, beta, k) for fixed theta; scan theta. Report k and theta with SEs the same way.
- `kind="auto"`: fit both; keep the one with the lower BIC unless `process_kind` of the loop says otherwise (then the
  loop's kind wins and the other is reported as `alt_model` with its BIC).
- Closed loop (SP step in AUTO or RSP; CAS is excluded because the master controller moves the SP correlated with disturbances): the same model driven by the measured OUT; flagged `closed_loop` (approximate: the controller
  correlates u with disturbances, so the gain can be biased; the step must be large against noise).

## Event detection (`StepEvent`: kind, i, t_s, size, unit_kind)
- noise: robust sigma of PV from first differences: 1.4826 * MAD(diff(pv)) / sqrt(2).
- OUT events (kind `out_step`, only where mode == 0, i.e. manual): two-sided median difference with window m = max(3, 60 s / dt)
  samples, `d[k] = median(out[k:k+m]) - median(out[k-m:k])`; candidates where |d| >= max(1.0, 3 * robust sigma of OUT) (OUT unit),
  local maxima of |d|, merged when closer than 2 m samples (keep the largest). Records the size `d`.
- SP events (kind `sp_step`, only where mode == 1): changes of SP with |delta| >= max(3 * noise, 1e-9), consecutive changes
  closer than 60 s merged into one event (size = sum).
- Window for an event: from `t - pre_s` (pre_s = 600 s, clipped to the previous event or the segment start) to `t + post_s`
  (post_s = 2400 s, clipped to the next event or the segment end). A segment is a run without gaps (> 5 dt) and without a mode
  change other than the event's own. Need >= 20 pre samples... if fewer than 10 pre or 30 post samples: event dropped with
  reason `window_too_short` (listed in `skipped`).

## Verdict (`ok` | `weak` | `unusable`) and reason codes
- `snr_low` (response amplitude / noise < 5; amplitude = |median(y last 20 % of post) - median(y pre)| for FOPDT, |beta_post - beta_pre| * T for IPDT),
  `gain_se_over_30pct`, `r2_low` (< 0.5), `theta_at_edge`, `tau_at_edge` (within 5 % of the upper bound), `closed_loop`
  (informational), `fit_failed` (unusable), `window_too_short` (unusable). ok = none of the weak reasons.

## Alignment
- `test_windows`: list of `{label, start_utc, end_utc}` (the dataset sidecar `test_windows.json`). A row's `test_label` is the
  label whose interval contains the event time, else null.
- `logbook`: optional list of `{time_utc, text}`; a row's `logbook` = entries within +-5 min of the event time (`time_utc` ISO
  text with Z or an offset; the GUI converts the user's lines).

## Payload (JSON-safe, NaN -> null)
```
{ "loop": id, "process_kind": ..., "unit": ..., "dt_s": float, "noise_sd": float, "n_events": int,
  "rows": [ { "id": "k", "kind": "out_step"|"sp_step", "mode": "manual"|"auto", "closed_loop": bool,
              "start_utc", "event_utc", "end_utc", "size": float, "snr": float|null,
              "model": "fopdt"|"ipdt"|null,
              "params": { "gain": {"value","se"}, "tau_s": {"value","se"}, "theta_s": {"value","se"}, "slope": {"value","se"} } (absent ones omitted),
              "r2": float|null, "rmse": float|null, "n": int,
              "verdict": "ok"|"weak"|"unusable", "reasons": [codes],
              "alt_model": {"model","bic"} | null, "test_label": str|null, "logbook": [ {"time_utc","text"} ],
              "sample": { "t_s": [...], "pv": [...], "out": [...], "fit": [...] } (<= 300 points, seconds from window start) } ],
  "skipped": [ {"event_utc","reason"} ] }
```

## Consistency (added during the build)
`step_consistency.add_consistency(rows)`: for 4+ ok rows of one model a row whose key parameter (gain / slope) is more than
max(3 MAD, 25 % of the median) from the median gets `inconsistent_with_median` and becomes `weak`; a `summary` list (per
model: n_rows, n_consistent, median/MAD of gain or slope, tau, theta) is added to the payload. Reason: on the owner's flow loops
closed-loop SP steps gave a small SE yet a gain differing by a factor 8 between steps, so SE alone is not honest.
Speed: a known `process_kind` fits only that model (a fit takes about 1 s); the HTTP call is per loop.

## HTTP
`POST /datasets/{dataset_id}/steps` body `{ "loop": str, "model": "auto"|"fopdt"|"ipdt" = "auto", "logbook": [ {time_utc, text} ] = [] }`
-> the payload above (404 unknown dataset or loop, 422 for a bad body or ValueError). Loader in app.py supplies a
`StepRecord(t_s, pv, sp, out, mode, origin_utc_s, unit, process_kind, test_windows)`.

## GUI (view `steps`, nav label "Steps"/"Kroki"/"Pasos")
Files (frontend/src): `stepAnalyzer.ts`, `components/StepsPage.tsx`, `components/StepsTable.tsx`, tests `stepAnalyzer.test.ts`,
`components/StepsPage.test.tsx`, `e2e/steps.spec.ts`. `stepAnalyzer.ts` exports the payload types (StepRow, StepParam
{value:number|null; se:number|null}, StepSummary, StepsPayload exactly as the payload above), `analyzeSteps(datasetId, body)`
(POST, errors throw Error(message)), `parseLogbook(text: string, offsetHours: number): {time_utc:string; text:string}[]` (lines
`YYYY-MM-DD HH:MM[:SS] description` or `YYYY-MM-DDTHH:MM description`, local time at the given offset hours east of UTC -> ISO Z;
unreadable lines skipped), `paramText(p: StepParam | undefined, digits?: number): string` ("0.80 ± 0.02" or "–").
`StepsPage({ datasetId, loopNames, initialLoop, t })`: loop select, model select (auto/fopdt/ipdt), logbook textarea +
offset-hours input, Analyze button, summary lines per model (median gain/slope, tau, theta, n consistent / n rows), the rows
table (time, kind (OUT step manual / SP step auto), size, SNR, model, gain or slope ± SE, tau ± SE, theta ± SE, R², verdict chip
with reason texts, test label, logbook), click a row -> chart (PV, fit, OUT over minutes from the window start, via TrendPane
like ImportChart.tsx). i18n keys (en/pl/es): steps.title, steps.note, steps.loop, steps.model, steps.model.auto, steps.model.fopdt,
steps.model.ipdt, steps.logbook.label, steps.logbook.hint, steps.logbook.offset, steps.run, steps.running, steps.empty,
steps.summary.title, steps.summary.line ({model},{gain},{tau},{theta},{ok},{total}), steps.col.time, steps.col.kind, steps.col.size,
steps.col.snr, steps.col.model, steps.col.gain, steps.col.slope, steps.col.tau, steps.col.theta, steps.col.r2, steps.col.verdict,
steps.col.test, steps.col.logbook, steps.kind.out_step, steps.kind.sp_step, steps.verdict.ok, steps.verdict.weak,
steps.verdict.unusable, steps.reason.snr_low, steps.reason.gain_se_over_30pct, steps.reason.r2_low, steps.reason.theta_at_edge,
steps.reason.tau_at_edge, steps.reason.closed_loop, steps.reason.fit_failed, steps.reason.inconsistent_with_median,
steps.reason.window_too_short, steps.skipped ({count}), steps.chart.title, steps.chart.pv, steps.chart.fit, steps.chart.out,
steps.chart.axis, nav.steps.
