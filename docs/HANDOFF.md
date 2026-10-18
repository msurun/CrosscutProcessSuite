# Handoff (2026-10-18): stiction closed as a weak hint, valve KPIs and tuning from history added; next is the guided valve test

Written for the next session (Claude or the owner). Details per step are in `docs/IMPLEMENTATION_LOG.md`
(last three sections) and in `experiments/exp15..exp17`.

## FIRST: git state (nothing from this session is pushed)

Four commits exist only locally on `main`: 2bb08f9 (exp16: G3 generator, LOFO, protocol), e0a545e (exp16 final
result), 9041f58 (PROVENANCE: Horch citation), f1339f2 (valve KPIs, tuning from history, exp17). Claude Code's
auto-mode classifier blocked `git push` twice (reason: results derived from third-party ISDB data). The ISDB label
table `experiments/exp16_stiction_generalise/isdb_labels.csv` is deliberately UNTRACKED and must stay so until the
data providers (see PROVENANCE) are asked; the commits contain counts only. The owner decides: `git push origin main`
by hand, or allow it in the Claude Code permission rules. `experiments/exp10_sacac_stiction/results/` is also
untracked (SACAC-derived, do not commit).

## Direction decision (owner, 2026-10-18, after an Opus strategic review with literature)

Not a rebuild. The package already has the shape of a loop-performance-monitoring product (KPI triage, oscillation,
Harris, modes and saturation, guarded step-test tuning, advisory only). Passive stiction detection from SP/PV/OP is
**closed**: the shipped scorer (C4a) stays frozen as a weak "check the valve" hint; its finding text says periodic
forcing looks the same and asks for a valve test or a gain change (a stiction cycle changes period with the gain, a
forced one does not). Do not start another stiction classifier on passive data.

Reasons, with numbers: exp15/exp16. Shipped scorer: synthetic AUC 0.52-0.75, ISDB AUC 0.67 (6/13 sticking flagged,
1/14 other flagged). A retrained scorer (C7a) gained +0.19 worst-family AUC on three synthetic families (G1 synth14,
G2 shifted, G3 independent generator) but flagged 10/14 non-sticking ISDB loops (AUC 0.32) and 3 non-sticking SACAC
loops, so it was rejected under the frozen rule. ISDB is burned for stiction selection. Literature (Scali 2005,
Choudhury, Jelali & Huang) agrees that no passive detector is reliable and that an on-plant valve test decides.

## What was built this session (all green: ruff, full `loops` pytest)

- `loops/src/crosscut_loops/health_kpis.py`: valve travel and reversals per hour, quantisation step and ratio,
  valve extremes with sizing hint (median output < 15 % oversized, > 85 % undersized), `group_by_period` (loops sharing
  an oscillation period), `kendall_trend`. Wired into `analyze_loop` (LoopReport fields `valve_travel_per_h`,
  `valve_reversals_per_h`, `out_quantisation_ratio`, `valve_sizing_hint`; findings "quantisation:" and
  "valve oversized/undersized:") and into the overview row keys. Grouping and trend are NOT shown anywhere yet.
- `history_windows.py` + `history_tuning.py`: natural setpoint steps in AUTO data, output-error FOPDT fit per window,
  cross-check on the other windows, confidence high/medium/low/none, "no_excitation" and a bump-test recommendation
  when there is no step, `cautious_step` for medium confidence. `tuning_report.py` gained `identify_model` and
  `report_from_model`. Closed-loop IV was tried and rejected (right gain, tau 4 s instead of 60 s on short windows).
- Evidence (exp17): simulation: clean data accurate within 2 % and graded high; disturbed data never high. Real data:
  26 of 86 SACAC/ISDB records have a setpoint step, none reached medium or high. So history tuning rarely applies;
  most loops get "do a bump test".
- exp16 infrastructure kept for reuse: G3 generator (`g3*.py`, written by a delegated model from `G3_SPEC.md`, hashes in
  the README), LOFO harness (`lofo.py`, `build_table.py`), single-use final script `final16.py` (results in
  `results/final16.md`; do not rerun, it refuses). Protocol and its amendments are in `experiments/exp16_*/README.md`.

## Next steps, in the order I would take them (Opus plan, steps 1-3)

1. **KPI triage validation on real loops.** Thresholds from published defaults, frozen BEFORE any run. Score the
   oscillation/KPI findings on SACAC (17 loops) and ISDB against the providers' comments (oscillating or not);
   pass = at least 80 % agreement with Wilson intervals; say that ISDB was already seen for stiction. Still to add:
   idle index, a data-driven oscillation detector (ACF regularity; Hagglund needs per-loop limits), show
   `group_by_period` and trend in the overview, a priority score (severity x `benefit.py` value) with the next action.
2. **Guided valve stroke test** (the only definitive stiction check). Specify from ANSI/ISA-75.25.01 and ISA-TR75.25.02
   (small steps up and down, dwell times, abort limits on PV and OP, rate limit) and compute apparent deadband and
   resolution from the OP-PV steps. Validate on a valve simulator written by a different model from the standard's
   definitions (the G3 rule): deadband error <= 0.25 % of span across noise and load steps; 100 % aborts in a
   limit-breach suite. Claim nothing for plants until one real test record exists. Read-only stance stays until the
   V5 write-path suite passes; the test must be a procedure for the operator, not an automatic write.
3. **Prioritised worklist reviewed blind** by an independent control engineer on about 20 loops (Kendall tau >= 0.5,
   >= 80 % agreement on the next action). No simulator can fake this.
4. Frontend: types and locale strings for the new LoopReport fields (`stiction_suspicion`, `stiction_advice`,
   `valve_*`, `out_quantisation_ratio`) are NOT updated (no Node.js on this PC).
5. Tuning from history: ramp and rate-limited setpoint changes, cascade secondary loops and level loops are untested.

## Working with the third-party data (rules that held this session)

Unzipped data lives in the session scratchpad, NOT in the repo: SACAC (`sacac/`), ISDB (`isdb/isdb10.mat`, converted
to `isdb_npz/` by `exp16_*/isdb_to_npz.py` using a scratch venv with scipy, run with `python -I`). Scratchpad paths are
session-specific and may be gone: re-download SACAC from https://sacac.org.za/resources/ and ISDB.zip from
https://sites.ualberta.ca/~bhuang/Stiction-Book.htm (sha256 of the zip and of `isdb10.mat` are in PROVENANCE). Neither
has a stated licence; ISDB's manual says it was published so other researchers can test methods and asks for citation.
Research use only, never commit the data or loop-level derived tables, ask piddata@sacac.org.za and the ISDB providers
before publishing derived tables. The Horch citation (Control Eng. Practice 7 (1999) 1221-1231) is confirmed from
citing papers; the paper itself was not read.

## Owner to-do (unchanged from 2026-10-15, still open)

1. **UaExpert check** (`python opcua/examples/live_demo.py`, `docs/LIVE_DEMO.md`), add one line to the log.
2. **ADR 008 review** (AGPL-3.0, `docs/adr/`).
3. ABB and Siemens documents for A7 are optional (forms already derived from public manuals; ABB TI/TD unit still open).
4. **Install Node.js LTS** (`winget install OpenJS.NodeJS.LTS`, then `npm ci` in `frontend/`), GitHub CLI, optional C++
   tools; see the 2026-10-15 text in git history for details. Until Node exists no frontend change can be claimed verified.
5. Check CI on GitHub after the owner pushes.
6. New: decide the push (see top) and whether to ask SACAC/ISDB providers about publishing derived tables.

## Environment and gates

`.venv/` (Python 3.12, `requirements-dev.txt`). Gates before every commit: `.venv\Scripts\python -m ruff check .`,
`-m mypy sim loops/src api/src connectors/src` (not run this session on the new modules: run it), `-m pytest`.
Style: functions <= 20 lines, <= 4 parameters, <= 3 nesting levels. `ruff format` over `loops` touches unrelated
files: format only the files you edited. MCP `delegate`: `verify` only accepts a few prefixes and runs from the parent
folder (`foremankit check` is not on PATH), results land in `<Python Scripts>/.agent-out/` (the PARENT folder), install
them by hand and read them critically (this session: tests had wrong expectations, a generated simulator had a physics
bug and a double integration). Files in `loops/` use CRLF; edit with CRLF-aware scripts.

## Known limits to keep stating

All validation of tuning and KPIs is on synthetic loops plus 17 SACAC and 27 counted ISDB loops without tuning ground
truth. Stiction suspicion is a weak ranking, confusable with periodic forcing, near chance for half-cycles < 18 samples,
weak for level loops, never a diagnosis. Time constant and delay are poorly identified at full noise. Tuning is
advisory: nothing writes to a DCS. KPI thresholds other than quantisation >= 1 and the 15/85 % sizing medians are not
validated on real loops.
