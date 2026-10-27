# Handoff (2026-10-27): product reset, Phase 0 cleanup

Written for the next session (Claude or the owner). Start with `docs/PRODUCT.md` (product definition, phases 0-8, owner decisions), then this file, then `docs/IMPLEMENTATION_LOG.md` for per-step detail.

## What changed on 2026-10-27

- The owner reset the product direction. `docs/PRODUCT.md` is now the single product definition; `docs/PROJECT_DESIGN.md` is kept as history only.
- ADR 012 ("Writes are a product capability") replaces the earlier no-write position; the safety rules of ADR 011 remain in force. All writing goes through one separate Write Gateway, in modes `advisory` → `confirm` → `supervised`; `confirm` and `supervised` are in v1. Nothing writes to a plant yet: `gateway/` is still a skeleton with strict-xfail scenarios.
- First complete product: loop monitoring plus PID tuning, from data intake to online work with writes (Phase 3).
- Connector order: OPC UA → PI → SQL/ODBC → the rest. Deployment: on-prem server plus browser, no cloud.
- A DCS simulator imitating ABB 800xA is a separate project, Phase 1a; Crosscut sees it as a black box. It is called RougherSim.
- The virtual-sensor and analyser work on plant 1 is a validation case, to be absorbed into a generic configurable engine in Phase 4, not a feature in itself.
- Closed experiment lines stay where they are and are indexed in `experiments/README.md`; one-off plans moved to `docs/archive/`; developer tools moved to `dev/`.
- The anti-drift rule (every task names its module and phase; no plant constants in code; no new top-level element without owner approval) is item 11 in `CLAUDE.md`.

## State of the modules

| Module | What ships (short) | Evidence / claim limit | Phase in PRODUCT.md |
| --- | --- | --- | --- |
| 1 Loop monitoring and tuning | KPI triage, ACF and oscillation test, valve checks and stroke test, worklist, SIMC/AMIGO and history tuning, integrating-loop tuning (experimental), Steps view, whole-file plant import | exp18-26, exp28; simulation only; real level data refused by the wizard (correct); worklist needs blind review | 3 |
| 2 Advisory supervisor | Fuzzy gates from module 1, advice, hash-chained log, Advisor view | exp27 E1-E5 met; ADR 010 proposed; simulated operator; `who` not authenticated | 6 |
| 3 Anomaly detection | PCA T2 and SPE, lagged columns, stuck-sensor rule, possible-ramp warning, Anomalies view | exp29 round 3: B1-B6 met; simulation only; spikes and bad-quality rows not detected; false-alarm rate unknown on real data | 1 (online job) / 3 (product view) |
| 4 Soft sensor | PLS on lagged tags, validity flags, bias tracker, Soft sensor view | exp30 beats last lab value 31/34; simulation only; drift flag not reliable; exp31 (plant 1) not blind | 4 |
| ADR 011/012 write path | `gateway/` interfaces, 12 strict-xfail scenarios, static no-write guards (now mean "only the gateway writes") | design only; not implemented | 2 |

Web UI views: Trends, Loops, Fuzzy, Advisor, Anomalies, Soft sensor, Import, Steps. Gates: `ruff`, whole-repo `pytest`, `vitest`, `tsc`, `build`, `npm run e2e:all` in `frontend/` (44 Playwright tests with axe). All green.

## Next steps

1. Phase 0 remainder: create GitHub milestones P0-P8 and re-map existing issues onto them; owner review of the Polish companion `docs/PRODUCT.pl.md`.
2. Phase 1 detailed plan (write it before coding). Detailed plan: docs/PHASE1_PLAN.md (approved decisions listed there).
3. Phase 1a: RougherSim exists as a private repo with an approved plan (M0-M7). Work it milestone by milestone in its own sessions; licence is still an owner decision. Crosscut side: build the integration harness `tests/integration_roughersim/` (issue on the board, milestone P1a) and keep the L5 acceptance matrix in docs/TESTING_STRATEGY.md current.

## Real plant data

- Confidential, stored outside the repository (owner's Drive), never sent to external services. Reports may quote numbers, not bulk data.
- Timestamps are local plant time without a zone. Level signals in cm; mode flags numeric.
- Traps already handled: exact `-9999` read as missing (not blended into means); interpolation across archive gaps fools detectors; PI compression shrinks small moves; valve dead band is a few percent.
- Validation finding, not a product rule: a process-only soft sensor was not achievable from four weeks of data (negative blocked-CV R2); using an online analyser as an input worked (exp31, not blind). A true test needs the next delivery kept untouched.

Seeds spent: 1-20, 27001-27120, 28001-28999, 29001-29060, 29201-29399, 29401-29600, 29601-29899, 30001-30788, 33001-33060, 33101-33199 (plant seeds 33001-35199). Next unused: 35200 and up (exp29), 30801 and up (exp30). A new round needs a new frozen protocol first.

## Owner to-do

Full list and open decisions: `docs/PRODUCT.md` section 10 and `docs/OWNER_TASKS.md`. Short form: first pilot DCS choice; whether the step-test assistant may propose OUT writes in `confirm`; who may enable `confirm`/`supervised` and change policy; simulator licence; ADR 008 licence review; blind worklist review; one real valve stroke test; controller tunings and one open-loop level step test; lab-stamp and analyser-latency answers; real anomaly data (≥ 2 weeks quiet plus labelled events).

## Working rules that held

- Every experiment: protocol frozen and committed before any run, generator written by a different model than the detector, one run on test seeds, amendments only before the first development seed and written down. Misses ship visibly; thresholds are not moved. Watch for seed collisions between derived plant seeds.
- The lead orchestrates and does not write code: foremankit `delegate` for bulk code, tests and documents; Haiku agents for small mechanical edits; Opus advisor for architecture and safety review.
- Gates before every commit: `.venv\Scripts\python -m ruff check .`, `-m pytest` (whole repo collects: test file basenames must be unique), `npx vitest run`, `npx tsc --noEmit`, `npm run build`, `npm run e2e:all`.
- Files in `loops/` may use CRLF in the working tree; use the Edit tool, not shell replace. JSON written by shell heredocs loses backslashes: use the Write or Edit tool for schemas.
- Third-party data and the owner's plant data: never committed; see `docs/PROVENANCE.md`.