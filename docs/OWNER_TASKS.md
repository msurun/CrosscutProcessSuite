# Owner tasks

## Decisions recorded on 2026-11-17

Owner decision 2026-11-17: Crosscut is a framework, not a setup for one plant. Plant data from the owner's site is not used for development or validation. Validation uses public datasets; site facts (tunings, sample metadata, vendor conventions, economic values) are per-site configuration entered by the user. Check the licence before use and add a row to `docs/PROVENANCE.md`; download to a scratch folder outside the repository; never commit or redistribute data. CC BY-SA and unlicensed datasets are used locally only; no derived data is published.

- [x] **2026-11-17, PRODUCT section 10 item 1:** ABB/Siemens validation access is a deployment datum: the site DCS, PidCC unit and access policy belong in the plant map and write policy, not in product decisions.
- [x] **2026-11-17, PRODUCT section 10 item 2:** The step-test assistant MAY propose OUT writes in manual, in `confirm` mode only. Implementation is a separate issue.
- [x] **2026-11-17, PRODUCT section 10 item 3:** RougherSim stays private with no licence, as decided 2026-10-27. Siemens PLCSIM Advanced verification is deferred until a Siemens user appears.
- [x] **2026-11-17, PRODUCT section 10 item 4:** No ABB SoftController for now. The ABB profile stays labelled ASSUMPTION; conventions are checked against public ABB documentation.
- [x] **2026-11-17, PRODUCT section 10 item 5:** ADR 008 (AGPL-3.0-only, with CLA) and ADR 009 accepted (#29).
- [x] **2026-11-17, PRODUCT section 10 item 6:** Blind worklist review is replaced by public-data benchmarks (separate issue).
- [x] **2026-11-17, PRODUCT section 10 item 7:** The real valve stroke test is replaced by public-data benchmarks (separate issue).
- [x] **2026-11-17, PRODUCT section 10 item 8:** The optimisation objective is per-site configuration: the user enters economic value per PV unit and operating limits, like item 9. Phase 8 is no longer blocked by a decision (#35).
- [x] **2026-11-17, PRODUCT section 10 item 9:** Write authority is configurable per site under ADR 013/014 and `docs/ADMIN_GUIDE.md`; no owner decision is pending (#31).
- [x] **2026-11-17, PRODUCT section 10 item 10:** Soft-sensor v1 consists of the presets marked v1 in section 4.2; `backup` mode IS in v1 (separate issue). Validation instruments use public data.
- [x] **2026-11-17, PRODUCT section 10 item 11:** Deferred to Phase 4b: v1 asset templates are those marked in section 4.3; validation uses public data.
- [x] **2026-11-17:** ADR 010 accepted, partly superseded by ADR 015; ADR 012 still supersedes its no-write position.
- [x] **2026-11-17:** ADR 011 owner open points closed by ADR 013/014 configurable defaults (#31).

## Follow-up work

- [ ] Implement the manual step-test assistant OUT proposals in `confirm` only (separate issue; decision 2026-11-17).
- [ ] Replace blind worklist review and real valve stroke testing with public-data benchmarks (separate issues; decision 2026-11-17).
- [ ] Complete the section 4.2 v1 presets, including `backup`, with public-data validation (separate issue; decision 2026-11-17).
- [ ] Phase 4b: validate section 4.3 v1 asset templates on public data (decision 2026-11-17).

## Remaining owner and deployment tasks

- [ ] Check the OPC UA demo with UaExpert; record the browsed nodes and errors (`docs/LIVE_DEMO.md`).
- [ ] Review Polish and Spanish UI strings natively; return corrections or acceptance.
- [ ] Review key protection on Windows/OneDrive.
- [ ] For each deployment, enter tunings, sample metadata, vendor conventions, economic values, access and write policy locally. Do not supply owner-site data for development or validation (decision 2026-11-17).

The former requests for owner-site level tests, PidCC exports, anomaly histories, lab files and untouched exp31 deliveries are retired by the decision of 2026-11-17. Authentication and write authority follow ADR 013/014; they do not await a new owner decision.
