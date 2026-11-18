# Handoff (updated 2026-11-18): Phase 2.5 APC core merged, night run over the kanban board

Written for the next session (Claude or the owner). Start with `docs/PRODUCT.md`, then this file, then `docs/IMPLEMENTATION_LOG.md` (entry 2026-11-17..18 lists every merged PR and the decisions taken without the owner).

## Owner decisions - 2026-11-17 (issue #80)

Owner decision 2026-11-17: Crosscut is a framework, not a setup for one plant. Plant data from the owner's site is not used for development or validation. Validation uses public datasets; site facts (tunings, sample metadata, vendor conventions, economic values) are per-site configuration entered by the user. Check the licence before use and add a row to `docs/PROVENANCE.md`; download to a scratch folder outside the repository; never commit or redistribute data. CC BY-SA and unlicensed datasets are used locally only; no derived data is published.

- **2026-11-17, PRODUCT section 10 item 1:** ABB/Siemens validation access is a deployment datum: the site DCS, PidCC unit and access policy belong in the plant map and write policy, not in product decisions.
- **2026-11-17, PRODUCT section 10 item 2:** The step-test assistant MAY propose OUT writes in manual, in `confirm` mode only. Implementation is a separate issue.
- **2026-11-17, PRODUCT section 10 item 3:** RougherSim stays private with no licence, as decided 2026-10-27. Siemens PLCSIM Advanced verification is deferred until a Siemens user appears.
- **2026-11-17, PRODUCT section 10 item 4:** No ABB SoftController for now. The ABB profile stays labelled ASSUMPTION; conventions are checked against public ABB documentation.
- **2026-11-17, PRODUCT section 10 item 5:** ADR 008 (AGPL-3.0-only, with CLA) and ADR 009 accepted (#29).
- **2026-11-17, PRODUCT section 10 item 6:** Blind worklist review is replaced by public-data benchmarks (separate issue).
- **2026-11-17, PRODUCT section 10 item 7:** The real valve stroke test is replaced by public-data benchmarks (separate issue).
- **2026-11-17, PRODUCT section 10 item 8:** The optimisation objective is per-site configuration: the user enters economic value per PV unit and operating limits, like item 9. Phase 8 is no longer blocked by a decision (#35).
- **2026-11-17, PRODUCT section 10 item 9:** Write authority is configurable per site under ADR 013/014 and `docs/ADMIN_GUIDE.md`; no owner decision is pending (#31).
- **2026-11-17, PRODUCT section 10 item 10:** Soft-sensor v1 consists of the presets marked v1 in section 4.2; `backup` mode IS in v1 (separate issue). Validation instruments use public data.
- **2026-11-17, PRODUCT section 10 item 11:** Deferred to Phase 4b: v1 asset templates are those marked in section 4.3; validation uses public data.
- **2026-11-17:** ADR 010 accepted, partly superseded by ADR 015 (and ADR 012 for writes); ADR 011 owner open points closed by ADR 013/014 defaults (#31).

## State on 2026-11-18

- main holds Phase 2.5 (variable model, live status, MV readiness, controller host, fuzzy controller, operator console, L5 C rows), ADR 016 handover, security follow-ups, delayed read-back verification, PI Web API and SQL historian connectors, one site-settings function for all importers, soft-sensor reference input and lab alignment scan. RougherSim is pinned at rs-v0.13.1 (pv_fault hooks).
- Open PRs: #94 validation report generator (#40), #95 public benchmarks (#21, experiments/exp32 needs owner approval as a new experiment line), #97 L5 matrix executors (#53), and the #96 tuning-live e2e fix. #94/#95 wait for #96 (same e2e job fails).
- Owner decisions waiting: ADR 015 defaults (cycle 30 s, 3 overruns -> shed, who may switch on); L5-P1-dq targets; TEP/C-MAPSS licences; #17; #20; the items below from 2026-11-06.

---


Written for the next session (Claude or the owner). Start with `docs/PRODUCT.md` (product definition, phases 0-8, owner decisions), then this file, then `docs/IMPLEMENTATION_LOG.md` for per-step detail.

## What changed on 2026-10-27

- The owner reset the product direction. `docs/PRODUCT.md` is now the single product definition; `docs/PROJECT_DESIGN.md` is kept as history only.
- ADR 012 ("Writes are a product capability") replaces the earlier no-write position; the safety rules of ADR 011 remain in force. All writing goes through one separate Write Gateway, in modes `advisory` → `confirm` → `supervised`; `confirm` and `supervised` are in v1. Nothing writes to a plant yet: `gateway/` is still a skeleton with strict-xfail scenarios.
- First complete product: loop monitoring plus PID tuning, from data intake to online work with writes (Phase 3).
- Connector order: OPC UA → PI → SQL/ODBC → the rest. Deployment: on-prem server plus browser, no cloud.
- A DCS simulator imitating ABB 800xA is a separate project, Phase 1a; Crosscut sees it as a black box. It is called RougherSim.
- The virtual-sensor and analyser work on plant 1 is a validation case, to be absorbed into a generic configurable engine in Phase 4a, not a feature in itself.
- Closed experiment lines stay where they are and are indexed in `experiments/README.md`; one-off plans moved to `docs/archive/`; developer tools moved to `dev/`.
- The anti-drift rule (every task names its module and phase; no plant constants in code; no new top-level element without owner approval) is item 11 in `CLAUDE.md`.

## State of the modules

| Module | What ships (short) | Evidence / claim limit | Phase in PRODUCT.md |
| --- | --- | --- | --- |
| 1 Loop monitoring and tuning | KPI triage, ACF and oscillation test, valve checks and stroke test, worklist, SIMC/AMIGO and history tuning, integrating-loop tuning (experimental), Steps view, whole-file plant import | exp18-26, exp28; simulation only; real level data refused by the wizard (correct); worklist public-data benchmarks pending (decision 2026-11-17) | 3 |
| 2 Advisory supervisor | Fuzzy gates from module 1, advice, hash-chained log, Advisor view | exp27 E1-E5 met; ADR 010 accepted 2026-11-17, partly superseded by ADR 015; simulated operator; `who` not authenticated | 6 |
| 3 Anomaly detection | PCA T2 and SPE, lagged columns, stuck-sensor rule, possible-ramp warning, Anomalies view | exp29 round 3: B1-B6 met; simulation only; spikes and bad-quality rows not detected; false-alarm rate unknown on real data | 1 (online job) / 3 (product view) |
| 4 Soft sensor | PLS on lagged tags, validity flags, bias tracker, Soft sensor view | exp30 beats last lab value 31/34; simulation only; drift flag not reliable; exp31 (plant 1) not blind | 4 |
| ADR 011/012 write path | `gateway/` interfaces, 12 strict-xfail scenarios, static no-write guards (now mean "only the gateway writes") | design only; not implemented | 2 |

Web UI views: Trends, Loops, Fuzzy, Advisor, Anomalies, Soft sensor, Import, Steps, Catalogue (with Mapping Wizard and Data Sources), Onboarding. Gates: `ruff`, whole-repo `pytest`, `vitest`, `tsc`, `build`, `npm run e2e:all` in `frontend/` (60 Playwright tests with axe). All green.

## Next steps (updated 2026-11-06)

State: Phase 0 and Phase 1 done. Phase 2 done against the simulator (gateway engine, OPC UA adapter, roles and authority, API console, policy panel, file-mailbox boundary, e2e on real processes). Phase 3 tuning write path implemented against simulators (ADR 014). Nothing is connected to a real DCS.

Owner to-do:
- Pilot DCS and PidCC unit are deployment data entered in the plant map and policy (not a product decision).
- Who approves tuning, lead role holder, kiosk kill, session lengths, admin password reset: now site settings with safe defaults (`<root>/_auth/config.json`, `roles.json`; `docs/ADMIN_GUIDE.md`, ADR 013 "Configurable defaults").
- Step-test assistant OUT proposals: permitted in manual, `confirm` only; implementation in a separate issue (decision 2026-11-17).
- Key protection on Windows/OneDrive.
- Follow-up implementation and deployment tasks: see `docs/PRODUCT.md` section 10 and `docs/OWNER_TASKS.md` (decisions 2026-11-17).

Next engineering steps:
1. L5 rows against RougherSim M7 (tuning hooks; RougherSim L5 rows still pending).
2. Per-site deployment verification of `take_remote` and PidCC units; public ABB documentation for development, with the ABB profile labelled ASSUMPTION (decision 2026-11-17).
3. Rollback exemption of min_interval/max_ratio (done: verified rollback restores audited baseline without interval/ratio blocks).
4. Operator escape for `applying` records with no ledger evidence (done: POST /tuning/proposals/{id}/escape unblocks stalled applying records when no write evidence exists in gateway audit).
5. Supervisor advice as proposals (#51) (done: supervisor advice flows to Write Gateway in confirm and supervised modes per ADR 014 sec 7; operator action always wins).
6. Module 1 release (P3).

## Data policy - owner decision 2026-11-17

Owner decision 2026-11-17: Crosscut is a framework, not a setup for one plant. Plant data from the owner's site is not used for development or validation. Validation uses public datasets; site facts (tunings, sample metadata, vendor conventions, economic values) are per-site configuration entered by the user. Check the licence before use and add a row to `docs/PROVENANCE.md`; download to a scratch folder outside the repository; never commit or redistribute data. CC BY-SA and unlicensed datasets are used locally only; no derived data is published.

Earlier exp31 owner-site findings are historical evidence only, not a development or validation input. No next owner-site delivery is requested. Historical module summaries below the current state do not create new owner-data requirements.

Seeds spent: 1-20, 27001-27120, 28001-28999, 29001-29060, 29201-29399, 29401-29600, 29601-29899, 30001-30788, 33001-33060, 33101-33199 (plant seeds 33001-35199). Next unused: 35200 and up (exp29), 30801 and up (exp30). A new round needs a new frozen protocol first.

## Owner to-do

Full decision record (2026-11-17) and remaining follow-ups: `docs/PRODUCT.md` section 10 and `docs/OWNER_TASKS.md`. Owner-site validation requests are retired; site facts remain user-entered deployment configuration.

## Working rules that held

- Every experiment: protocol frozen and committed before any run, generator written by a different model than the detector, one run on test seeds, amendments only before the first development seed and written down. Misses ship visibly; thresholds are not moved. Watch for seed collisions between derived plant seeds.
- The lead orchestrates and does not write code: foremankit `delegate` for bulk code, tests and documents; Haiku agents for small mechanical edits; Opus advisor for architecture and safety review.
- Gates before every commit: `.venv\Scripts\python -m ruff check .`, `-m pytest` (whole repo collects: test file basenames must be unique), `npx vitest run`, `npx tsc --noEmit`, `npm run build`, `npm run e2e:all`.
- Files in `loops/` may use CRLF in the working tree; use the Edit tool, not shell replace. JSON written by shell heredocs loses backslashes: use the Write or Edit tool for schemas.
- Third-party data and the owner's plant data: never committed; see `docs/PROVENANCE.md`.
