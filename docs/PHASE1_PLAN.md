# Phase 1 plan

Date: 2026-10-27
Purpose: detailed plan required by docs/HANDOFF.md before Phase 1 coding; source of truth is docs/PRODUCT.md.

## Decisions (owner, 2026-10-27)

- New top-level package `runtime/` plus `deploy/` (CLAUDE.md rule 11 approved). GUI start/stop acts on jobs (enable/disable), not on the OS service.
- Default missing codes become empty; -9999 moves to a plant-1 profile kept outside the repo.
- One site file per data root: `<root>/_site/site.json`; loader in `connectors/` (never `loops/`); `jsonschema` becomes a runtime dependency.
- CI guard for plant words (#42): numeric/regex patterns in the repo; the word list lives outside the repo, path in env var `CROSSCUT_PLANT_WORDS_FILE` (guard skips the word check if unset); shrinking allow-list for known hits (sim/, opcua server, flotation_public.py until moved).

## Facts verified in the repo

- loops/readiness.py exists but is not wired to API/GUI.
- plant_import.py:41 HISTORIAN_SENTINEL=-9999.0 default.
- anomaly_routes.py:32-34 RAMP_MIN_HOURS, COUNTER_LIKE_SHARE.
- plant_import_loops.py hard-codes naming regexes (VALVE_TAG_PATTERN, MODE_SUFFIX, prefix->process_kind) that belong in site config.
- connectors/flotation_public.py is dataset-specific.
- tags.schema role enum PV,SP,OUT,MODE,DV,CV,MV,other vs project.variables MV/CV/DV vs DictRow.signal (three vocabularies to reconcile).
- app.py is 623 lines; add routers only as build_*_router modules.
- pytest test basenames must be unique repo-wide.
- loops/ files may be CRLF (use Edit).
- Own OPC UA test server opcua/src/crosscut_opcua/server.py (PlantServer, flat Plant object, no HistoryRead).

## Order

#42 guard+constants -> #41 vendor field -> #45 generic renderer -> #36a site schema -> #36b hierarchy/loops/labs/modes -> #37 mapping wizard -> #43 connector interface -> #39 onboarding -> #44 runtime. #53 harness skeleton in parallel (real rows need RougherSim M5/M6).

## Per issue (files, tests, GUI slice, exit test, size)

### #42 (M)

- Files and tests: tests/test_no_plant_words.py; plant_import.py default missing_codes=(); loops/tests/test_plant_import_settings.py non-default code case; anomaly config.py + schemas/anomaly.schema.json get ramp_min_hours, counter_like_share; api/anomaly_routes.py reads them; move connectors/flotation_public.py and its test to experiments/; tools/analyzer_vs_lab.py and tools/driver_response.py constants become CLI args.
- GUI slice: 'missing codes' field in plant import.
- Exit: guard passes with non-default code; no -9999 in */src.

### #41 (S)

- Files and tests: schemas/project.schema.json loop `vendor` validated against vendor_forms keys; project_loops.py VENDOR_KEY; project_edit.py KNOWLEDGE_KEYS; tuning_view.py picks form per loop; frontend KnowledgeFields.tsx vendor select + en/pl/es keys + KnowledgeEditor.test.tsx + e2e lines.spec.ts.
- Exit: changing vendor in GUI changes parameter names on the Tuning tab.

### #45 (L, split)

- Files and tests: api/schema_routes.py (GET /schemas, GET /schemas/{name}, GET/PUT /config/{kind}/{id}, jsonschema validation, atomic write; schemas/ must be packaged with the API); frontend schemaForm.ts pure (JSON-Schema subset: object, array, enum, number min/max, string, boolean, description as help; no oneOf, $ref only into $defs), SchemaForm.tsx, SchemaField.tsx, ConfigEditorPage.tsx; labels t("schema.<name>.<path>") with title fallback; vitest locale parity.
- First consumers: supervisor, anomaly, softsensor config, site.
- Exit: e2e edits anomaly config via form, scan uses it, axe clean.

### #36 (L, split 36a/36b)

Scope follows PRODUCT.md 3.1 (project catalogue): not only tags and loops.

- Files: schemas/site.schema.json (hand-written, `$defs` per element, schema_version). 36a: site{name,timezone}, defaults{sample_period_s}, import{missing_codes,decimal_comma,delimiter,time_names}, quality{good_codes,bad_codes}, naming{valve_pattern,mode_suffix,...}, sources[{id,driver,endpoint,options; no credentials}], units{conversions}, tags[{id,source,address,description,unit,range,eng_limits,dtype,sampling,compression,missing_codes,quality_map}]. 36b: equipment[{id,level site|area|unit|equipment,parent,tags,criticality,asset_template}], loops[{id,type,pv,sp,out,mode,action,out_limits,links,vendor}], labs[{id,sample_point,variable,stamp start|end|middle+offset,composite_window,latency,missing_codes,valid_range}], modes[{id,name,scope,condition}]. No plant-naming defaults.
- connectors/site.py: load_site, validate_site (JSON Schema + cross-reference check: every tag id used by equipment/loops/labs/modes exists, hierarchy has no cycles, units convertible), read_settings_from_site. api/site_routes.py GET/PUT /site, GET /site/import-settings. Frontend SitePage.tsx via SchemaForm, new `catalogue` view (route.ts, App.tsx, TopBar.tsx), en/pl/es.
- Out of scope here: role detection and mapping wizard (#37), CSV bulk edit and versions with diff (later P1 issue), vendor profile files (#41 follow-up).
- Tests: tests/test_schemas.py (incl. missing code other than -9999, hierarchy with criticality, mode condition, lab stamp), connectors/tests/test_site.py (dangling tag id, cycle), api/tests/test_site_routes.py, vitest.
- Exit: e2e site with missing code -999, import uses it; site with 2-level hierarchy, mode and lab validates and round-trips through the GUI.

### #37 (L)

- Files: signals[{tag, role pv|sp|out|mode|input|target|lab|dv, loop?, module?}] in site/catalogue schema, one table reconciling the three role vocabularies; connectors/role_mapping.py pure suggest_roles(tag_names, naming); api/catalogue_routes.py POST /catalogue/suggest, PUT /catalogue/mapping; refactor intake_routes.suggestions and plant_import_loops.detect_loops onto it; mapped loops served via DatasetStore.loops_of; CatalogueWizard.tsx (steps source, tags, roles, loops, confirm; reuse Stepper.tsx).
- Tests: connectors/tests/test_role_mapping.py with a non-plant-1 naming convention, api/tests/test_catalogue_routes.py, e2e catalogue.spec.ts.
- Exit: one mapping drives a loop in Loops, an input in Anomalies, a target in Soft sensor.

### #43 (L)

- Files: connectors/base.py Protocol Connector (capabilities, browse, metadata, history, read_live, subscribe; NO write method, gateway owns writing); registry.py driver->factory from site.sources; adapters opcua_connector.py (persistent session, reuse resolve_node_id/_read_one/_quality_of), csv_connector.py, sql_connector.py; history raises NotSupported for OPC UA; api/connector_routes.py POST /sources/{id}/test, GET /sources/{id}/browse; SourcesPanel.tsx.
- Tests first against PlantServer: test_connector_contract.py (parametrised, every adapter), test_opcua_connector.py, static guard in gateway/tests/test_gateway_static_guards.py (no write* in connectors Protocol).
- Exit: connect, browse, read live from the test server in the GUI.

### #39 (M)

- Files: move loops/readiness.py constants into site `readiness` block; api/onboarding_routes.py GET /datasets/{id}/readiness (per-module verdicts loops/anomaly/softsensor); OnboardingPage.tsx traffic lights + what-to-fix.
- Tests: api/tests/test_onboarding_routes.py, extend loops/tests/test_readiness.py, use connectors/messy.py corpus.
- Exit: faulty export shows fail/warn per module. sensor_faults precision/recall row waits for RougherSim M5.

### #44 (L)

- Files: schemas/job.schema.json {id, kind loop_kpi|anomaly_scan, source, tags/loops, period_s, window_s, enabled}; state under <root>/_runtime/ (jobs.json, state.json, log.jsonl); runtime/src/crosscut_runtime/{scheduler,jobs,store,service,__main__}.py; jobs/loop_kpi.py reuses loops.health_kpis/metrics on a rolling window from read_live; deploy/ systemd unit + Windows wrapper; api/runtime_routes.py (status, log, start/stop job); RuntimePage.tsx.
- Tests: runtime/tests/test_scheduler.py (fake clock/connector), test_loop_kpi_job.py (live KPI equals offline KPI on same series), test_service_failure.py.
- Exit (Phase 1 exit): run_e2e.mjs starts test OPC UA server, API and runtime; e2e builds site, sources, catalogue, starts a job in the GUI, live KPI appears, no file edited by hand. Own history store needed (OPC UA test server has no HistoryRead): format open (parquet per ADR 002 or SQLite).

### #53 (S)

- Files: tests/integration_roughersim/ conftest.py (marker, skip if absent), roughersim.lock, matrix rows as skipped tests; register marker in pyproject.toml.
- Exit: none stated beyond skipping when RougherSim is absent.

## Today's sequence (single day: steps 1-5, maybe 6 backend)

1. test_no_plant_words guard (hard_code).
2. #41 (hard_code schema/loader, bulk_code GUI/locales/tests).
3. #42 constants (bulk_code; quick for tools/ CLI args).
4. site.schema.json 36a (core) + schema tests (hard_code design, bulk_code tests).
5. connectors/site.py + site_routes.py (bulk_code); 36b follows after #37 role table is agreed.
6. #45 backend, then schemaForm.ts + vitest (hard_code logic).

Next day:

7. Connector base.py + contract tests, CSV then OPC UA adapters.
8. #53 skeleton (quick).
9. /readiness route + onboarding page.

## Risks

- Windows service mechanism open (pywin32 service / NSSM-style wrapper / Task Scheduler).
- Runtime history store format and retention.
- PlantServer has a flat Plant object, so ABB-style browse/naming is untested until RougherSim M6.
- Generic editor scope creep (restrict schema subset).
- Every GUI slice adds en/pl/es keys and axe e2e, so e2e:all grows; keep e2e files per feature.
- Plant 1 workflow needs its profile outside the repo after the missing-code default change.
