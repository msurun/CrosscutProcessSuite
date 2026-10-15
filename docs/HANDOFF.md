# Handoff (2026-10-14, night): steps 1-4 done, what is next

Written for the next session (Claude or the owner). The plan P1-P7 of module 1 is done and pushed
(last commit when written: f7b5bc2). Details per step are in `docs/IMPLEMENTATION_LOG.md`.

## Owner to-do (needs the owner at the physical computer, after coming home)

1. **UaExpert check.** Start a demo (`python opcua/examples/live_demo.py`), connect UaExpert to the
   printed endpoint, follow `docs/LIVE_DEMO.md`. Add one line to the log: UaExpert version, what
   worked, what did not. Until then the OPC UA server is tested with a Python client only.
2. **ADR 008 review** (AGPL-3.0, `docs/adr/`): read the reasons, accept or change.
3. **ABB and Siemens documents for A7 (now optional: the assistant starts from the public manuals, see next steps item 0).** Give the PID manuals (or names and versions) so the PI
   parameter forms in `loops/tuning_rules.py` (`convert_pi`) can be checked. Scope fixed by the owner:
   ABB and Siemens only. Until then A7 stays open and the forms are marked unverified.
4. **Install the tools permanently** (so any session can run all gates; this PC had none of them).
   The assistant cannot make permanent installs without you at the computer:
   - Python 3.12 (already installed) and a repo venv (`.venv/` is git-ignored): `py -3.12 -m venv .venv`, then
     `.venv\Scripts\python -m pip install -r requirements-dev.txt` (now includes `uvicorn`).
   - Node.js LTS (the frontend needs it): `winget install OpenJS.NodeJS.LTS`, then in `frontend/`: `npm ci`
     (brings Vite, Vitest, TypeScript and `playwright-core`).
   - Microsoft Edge (already present; used for the browser checks through `playwright-core`).
   - GitHub CLI to read CI results: `winget install GitHub.cli`, then `gh auth login`.
   - Git (present). Optional, only for the C++ core in `core/`: CMake, Ninja and a compiler; the earlier
     local route was the pip packages `cmake`, `ninja`, `ziglang`, `pybind11` (see the log, T0.11).
   - UaExpert (for item 1), free download from the vendor.
   - Add the venv `Scripts` folder and Node to the user PATH, or tell the assistant the paths.
5. **Check CI on GitHub** for the last pushes (no `gh` on this PC): jobs `cpp` and `frontend`.

## Environment

`.venv/` exists on this PC (Python 3.12, `requirements-dev.txt` installed; git-ignored). If it is gone:
`py -3.12 -m venv .venv`, then `.venv\Scripts\python -m pip install -r requirements-dev.txt`.
There is NO Node.js here, so the frontend gates (`tsc --noEmit`, `vitest run`, `vite build`) and the Edge
browser check cannot run until the owner installs Node (item 4 above). Do not claim frontend changes verified.

Gates before every commit: `.venv\Scripts\python -m ruff check .`, `-m mypy sim loops/src api/src connectors/src`,
`-m pytest`. Style: functions <= 20 code lines, <= 4 parameters, <= 3 nesting levels. `foremankit check` is not
installed in the venv. MCP `delegate`: give ABSOLUTE `context_files`; its `verify` runs from the parent folder and
rejects absolute interpreter paths, so install the returned file by hand and check it yourself. Read delegated
code critically: `readiness.py` and `anonymise.py` came back with real bugs. In shell heredocs write regexes with
`chr(92)` or a raw file edit: a backslash-b inside a normal Python string became a backspace character once.

## Done in the last session (details: `docs/IMPLEMENTATION_LOG.md`, last two sections)

Steps 1-4 of the earlier list: stiction band discrepancy explained (seed noise, 14/20), public flotation benchmark
(`exp04_public_flotation`), customer validation kit (`docs/customer_kit/`, anonymiser, readiness check), connectors
(DST fall-back repeats, header units, long-format CSV, SQL over any DB-API connection, OPC UA namespace URI and
reconnect), and a code review with 10 fixes. Last commit c05615f, everything pushed.

## Next steps the assistant can do without the owner

Rule from the owner: delegate tests and bulk code, keep integration, one commit per step, push main without force,
log every step, state limits plainly. Suggested order (the owner asked for the whole list in a fresh session):

0. **A7: DONE 2026-10-14 (see `docs/VENDOR_PID_FORMS.md`); open: ABB TI/TD unit, wiring into `tuning_report.py`.** Original task: The manuals are public, the owner's documents are not needed for this. Siemens: PID_Compact (all times in seconds, S7-200 used minutes; https://support.industry.siemens.com/cs/attachments/109481448/109481448_S7200-S71200_PID_Compact_en.pdf, exact equation is in the S7-1200/1500 PID Control function manual). ABB: AC 800M PidCC in the Control Libraries manuals (e.g. 3BSE035981-510 on library.e.abb.com); the AC 500 CtrlPidParallel page is another product line and is NOT evidence for AC 800M. Fetch the PDFs, extract equation, parameter names and units, compare with `convert_pi` in `loops/src/crosscut_loops/tuning_rules.py`, add tests, mark each form verified or still unverified (quote page and version, do not copy text), add PROVENANCE rows, update A7 in the log. Owner documents are only needed for the exact system versions used at the plant.
1. **Fault layer V1, rest.** Timestamp jitter and mode flips in `sim/faults.py` (mode flips are `Event`s), with
   tests; then show whether the loop analysis (`loops/monitor.py`, `readiness.py`) copes with them.
2. **Connector gaps.** DST fall-back for naive timestamps in `sql_import` (the CSV fix in `csv_import._resolve_instant`
   is the model), units in the long-format CSV (optional `unit` column into the tags document), OPC UA
   subscriptions (the importer only polls). ODBC was never tried with a real driver: say so if it comes up.
3. **(DONE 2026-10-14, see the log: exp06-exp08)** **Tuning, part 2 (C3).** Derivative term (PID), closed-loop identification (biased gain with the operator on,
   see exp00), cascade order; each with an experiment and acceptance targets frozen BEFORE the run, as in
   exp02/exp03. Derive `std_reduction` for the benefit page from loop reports automatically.
4. **(DONE 2026-10-15 except the matrix screen, see the log: exp09)** **Fuzzy Studio.** Rule matrix view; backtest of a rule base against operator moves (output `feed_change` is a
   delta of the SP tag). Advisory only.
5. **Public data, round two.** The flotation data has no SP/OUT. Look for an open dataset WITH controller output
   (stiction/oscillation benchmarks); check the licence before downloading and add the PROVENANCE row first.
   `exp04` notes why the flotation run says little about oscillation (no setpoint, untuned amplitude limit).
6. **Screens (needs Node.js, so only after the owner installed it).** Manual window drag on the trend, undo zoom,
   range presets, modules map page. Check each in Edge.
7. **Later stages (design first, then ask the owner):** V4 lab test bed, V5 virtual DCS with a soft PLC and a
   write-path test suite (must pass before any real write), V7 pilot package. Not before the owner has seen the
   V3/V6 results.

## Known limits to keep stating

All data is synthetic. Time constant and delay are poorly identified at full noise (gain is fine).
Stiction needs sampling faster than about 15 s and a band above about 8 % at full noise; a square-wave load
is a known false alarm. Overshoot and settling in exp03 are measured on a 60 s moving average. Tuning is
advisory: nothing writes to a DCS. The "example" window of a whole-record finding is a heuristic.
