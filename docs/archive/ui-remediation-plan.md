# UI remediation plan (advisor review, 2026-10-20)

Status: accepted by the owner for implementation ("wdrożysz"); owner decisions below use the advisor's defaults until
the owner overrides them. Each phase ends with every gate green (ruff, mypy, pytest, tsc, vitest, build) and a commit.
Progress is tracked in `docs/IMPLEMENTATION_LOG.md` (section "UI remediation").

## Verdict: top problems by user impact
1. Loops that were not really checked read "OK, 70 %": `overview.py` returns `ok` when the only checks that could fire were
   withheld, and a missing Harris index is imputed as `HARRIS_NEUTRAL=0.5` (0.4 + 0.6 * 0.5 = 70 %). False reassurance.
2. The detail page contradicts itself ("No action needed" under a "next action: enter loop data" card).
3. No screen for the valve stroke test (the main stiction follow-up).
4. Fuzzy membership chart ticks are wrong: `toPrecision(4).replace(/\.?0+$/, "")` turns 2600 into "26".
5. Mixed number formats: uPlot axes use the locale decimal comma, text uses `toFixed` (dot). Dangerous for values copied to a DCS.
6. Tuning wizard: gain without unit, PV and OUT on one axis, no free window, no recommendation sentence.
7. No dataset context (period, sample period, analysis time).
8. Benefit page: English "assumed" badges, defaulted limit shown red like an error, "value per hour" shows a dash without reason.
9. Trends tab does not follow S2 (no time ranges, no undo, raw tags, one pane for all).
10. Fuzzy Studio: English content in the PL UI, very long page, no backtest view.

Corrections to the first list: CI already runs typecheck, test and build (`.github/workflows/ci.yml`); a CSV upload is not the main
need for the valve test (analyse a dataset window first); `valve_test.procedure_text` and `StrokeResult.reason` are English
strings and need codes plus parameters; there is no router, so deep links and the back button do not work.

## Phases
- **P0 Truth fixes.** P0.1 status `not_assessed` (additive string value; worklist order warning < not_assessed < ok).
  P0.2 `health_percent` is null when Harris is NaN (no imputation in the score path), UI shows "not scored (missing: ...)".
  P0.3 detail page coherence ("No problem in the checks that ran", next steps list the missing inputs, never "No action needed").
  P0.4 one number formatter `frontend/src/format.ts` (Intl, locale decimal), replace every `toFixed/toPrecision`; DCS blocks keep
  the dot and say so. P0.5 i18n leaks (`assumed`, fuzzy example text; example rule bases get `label_i18n`), a vitest scanning the
  PL DOM for English words.
- **P1 Shell and context.** Hash router `#/d/{dataset}/{view}/{loop?}/{sub?}` (no dependency), breadcrumb, context bar (dataset,
  period, sample period, tags, analysed at / took), `/loops` wrapped as an object with `analysed_at, duration_s` (frontend in the
  same commit), ErrorBoundary, API-offline banner, 404 view, skeleton rows, focus to h1 on route change, skip link, S1 datasets list
  (no import).
- **P2 Tuning wizard.** Real stepper (todo/active/done/blocked(reason)), free window picker on a PV/OUT/MODE trend with suggested
  windows shaded, gain unit `{pv_unit}/% OUT`, theta/tau hint, predicted response in two panes, recommendation sentence from a
  template, full-width "nothing is written to the plant" banner.
- **P3 Valve stroke test.** P3.0 refactor `procedure_text` into `procedure_steps` (codes + params) and `reason_code`; then
  `valve_routes.py`: `POST /loops/valve-test/plan`, `POST /datasets/{id}/loops/{loop}/valve-test/analyse` (window of the dataset),
  `POST /valve-test/analyse-csv` (multipart, in memory, size cap). UI state machine setup -> plan_ready -> awaiting_record ->
  analysing -> result | error with a first-run checklist gate (operator informed, loop may be in MANUAL, abort band agreed).
- **P4 Loop detail trends and knowledge.** TrendPane: MODE band, range buttons + undo, role labels in the legend, last value when
  not hovering. Knowledge editor: OUT/PV engineering ranges as project.json overrides (precedence documented), "how to measure"
  help, post-save diff of what changed.
- **P5 Trends tab.** Tags grouped by loop and unit, at most 3 automatic panes, range buttons, undo, cursor readout.
- **P6 Fuzzy Studio.** Tabs Variables | Rules | Replay | Backtest; rule row as a two-line card; backtest view with an
  "illustrative, not validated" banner; matrix UI deferred.
- **P7 Quality.** Playwright + axe devDependency (one smoke spec per view at 1440/390, PL), `manualChunks`, ESLint
  `max-lines-per-function: 40`/`max-params: 4` on touched files, print CSS for reports.

## Owner decisions (defaults in force)
1. Unassessed loop: separate `not_assessed` status, no health number.
2. DCS blocks keep a dot decimal, labelled; a per-DCS setting comes later.
3. Oscillation period without an amplitude limit is shown as info ("cycle observed, size not judged"), no status change.
4. Worklist order kept, with the visible caption "rule-of-thumb order, not validated".
5. Stroke test default steps 1 % and 0.25 %, dwell at least 3 * (theta + tau) when a model exists.
6. Benefit page hides the money until both value and limit are entered by the user.

## Not now
S1 import wizard, bulk knowledge editing, drag-and-drop panes, left-rail rewrite, fuzzy matrix UI, any plant write path, a
router or state library dependency.

## Verification protocol per phase
`ruff check . && mypy && pytest`; `cd frontend && npm run typecheck && npm test && npm run build`; from P7 `npx playwright test`.
Screenshots at PL 1440, 390 and dark: no English words, no dot decimals outside DCS blocks, no OK on the stiction fixture,
fuzzy ticks 2600-3400. A11y: axe 0 serious violations, Tab reaches skip link then h1, every chart has aria-label and a readout
alternative, touch targets >= 44 px at 390, `prefers-reduced-motion` respected.
