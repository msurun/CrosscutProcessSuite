# Module 2 plan: advisory supervisor (2026-10-21)

Written by the opus advisor from the repo state, kept here as the working plan. Decisions are in `docs/adr/010-advisory-supervisor.md`.
Every step must end with ruff, mypy and pytest green, and the lead reads every delegated file before committing.

## Finding

The fuzzy engine, backtest, versions and API exist (`fuzzy/`, `api/.../fuzzy_routes.py`). Missing is the supervisor: a rule-base
output turned into gated, explained, logged advice that an operator acknowledges. Risk: easy to build, hard to beat a crisp rule
(`docs/archive/NEXT_MODULE_OPTIONS.md`); exp09 left 43 % of operator moves facing a silent rule base.

## Contracts

New package `supervisor/src/crosscut_supervisor/` depends on `crosscut_fuzzy` and `crosscut_loops`, never on `opcua` or `connectors`.

- `schemas/supervisor.schema.json` (config): `id`, `fuzzy_system_id`, `fuzzy_version_id`, `output_id`, `target_loop`,
  `gates: [{loop, block_on: [manual|saturated|flatline|unknown], warn_on: [oscillating]}]`, `silent_band`, `min_activation` (0..1),
  `min_interval_s`, `display_clamp` [lo, hi], `mode` in [off, advisory].
- `schemas/advisory-record.schema.json`: kind `advice` (`advice_id` = sha256 of supervisor id + rule-base hash + t_ns, `t_ns`,
  `target_loop`, `direction` increase|decrease|hold, `magnitude` clamped, `activation`, `explanation[]` (rule id, sentence,
  strength), `inputs{}`, `gate{state open|degraded|blocked, reasons[]}`, `rulebase_sha256`, `prev_sha256`) and kind `ack`
  (`advice_id`, `decision` accepted|rejected|deferred, `reason_code`, `note`, `who`, `t_ns`, `prev_sha256`).
- Python: `load_config(doc) -> SupervisorConfig` (SupervisorConfigError), `gate_state(rows, config) -> GateResult`,
  `advise(system, config, snapshot, gate, t_ns) -> Advice | None` (None = silent), `advise_series(...) -> list[Advice]`,
  `AuditLog(path).append(record) -> sha`, `.verify() -> ChainReport`, `ack(log, advice_id, decision, reason_code, who, note, t_ns)`.
- Fail closed: missing loop row, not-assessed gate, NaN or out-of-range input gives `blocked`.

## Steps

| Step | What | Who | Depends |
|---|---|---|---|
| S1 | ADR 010, PROVENANCE row, ASSUMPTIONS A18/A19 | lead | none |
| S2 | the two schemas + contract tests (example validates, `closed_loop` rejected, ack without `advice_id` rejected) | lead schemas, delegate tests | S1 |
| S3 | `config.py`: `load_config`, output id exists in the fuzzy system, gate loops unique, about 8 tests | delegate | S2 |
| S4 | `gates.py` from module 1 rows (manual: classification or service < 50 %; saturated; flatline; oscillating warn only); a missing row blocks; `health_percent None` alone does not block | delegate | S3 |
| S5 | `advise.py`: `evaluate`, explanation from dominant rules, silent below band or `min_activation`, blocked gate gives a record without magnitude, deterministic `advice_id` | lead or hard_code with review | S3, S4 |
| S6 | `audit.py`: JSONL under `_advisory/<sid>/log.jsonl`, hash chain; any edited byte makes `verify()` name the first broken index; ack for an unknown id raises; two quick appends both survive | delegate with review | S2 |
| S7 | `replay.py`: rolling module 1 analysis per window plus `min_interval_s` debounce; 0 advices in injected MAN/flatline windows | delegate | S4, S5 |
| S8 | no-write guard tests: import graph has no `opcua`/`connectors`; filesystem writes only under `_advisory/` or `_supervisor/` | lead | S3-S7 |
| S9 | API `supervisor_routes.py`: GET/PUT `/supervisors/{sid}`, POST advise, POST replay, GET log, POST ack; 422/404 tests | delegate | S5-S8 |
| S10 | exp27 protocol frozen and committed before any run | lead; harness and operator model by a different model | S7 |
| S11 | exp27 run: dev once, amend only before test seeds, test once, README with hashes | lead | S10 |
| S12 | frontend AdvisoryPage (advice list, gate badges, Accept/Reject/Defer with reason, log chain status), vitest + Playwright/axe | delegate | S9 |
| S13 | README "Module 2" with claim limits, HANDOFF, IMPLEMENTATION_LOG | lead | all |

## exp27 (frozen criteria)

Mill circuit closed loop. A simulated operator applies the advised SP move after D = 300 s with probability 0.8. Arms: (a) scripted
operator, (b) crisp baseline rule base, (c) fuzzy v2. Dev seeds 10, test seeds 20 run once (read spent ranges in the experiment READMEs).

- E1: 0 advices in gated windows across all fault scenarios.
- E2: median advice rate <= 4 per hour and no two advices closer than `min_interval_s`.
- E3: P80 time on target for (c) >= (b) + 5 pp on at least 14 of 20 test seeds.
- E4: mill-power-high time for (c) <= (b) + 1 pp.
- E5: silent share at operator moves <= 30 % (exp09 B5 retried on the v2 rule base; tune on dev seeds only).

If E3 fails the module ships with "pipeline and gating verified; no benefit over a crisp rule shown". Do not iterate on test seeds.

## Definition of done

S1-S11 merged, CI green with the S8 guard; exp27 README with frozen criteria and results (pass or documented miss); audit chain
verified in a test; module files pass the project code check; README states the claim limits; UI done or deferred and logged.

## Risks

Rolling analysis may be slow (measure S7 on 24 h data; cache per window above 60 s). Gate false blocks from ACF false alarms are the
reason oscillation only warns; report the gate-open share in no-fault runs (>= 90 %). Same-model bias: the harness and the supervisor
come from different model families, recorded in the exp27 README. Add a contract test that API responses validate against
`advisory-record.schema.json`.
