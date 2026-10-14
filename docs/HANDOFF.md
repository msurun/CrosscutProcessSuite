# Handoff (2026-10-14): module 1 closed, what is next

Written for the next session (Claude or the owner). The plan P1-P7 of module 1 is done and pushed
(last commit when written: f7b5bc2). Details per step are in `docs/IMPLEMENTATION_LOG.md`.

## Owner to-do (needs the owner at the physical computer, after coming home)

1. **UaExpert check.** Start a demo (`python opcua/examples/live_demo.py`), connect UaExpert to the
   printed endpoint, follow `docs/LIVE_DEMO.md`. Add one line to the log: UaExpert version, what
   worked, what did not. Until then the OPC UA server is tested with a Python client only.
2. **ADR 008 review** (AGPL-3.0, `docs/adr/`): read the reasons, accept or change.
3. **ABB and Siemens documents for A7.** Give the PID manuals (or names and versions) so the PI
   parameter forms in `loops/tuning_rules.py` (`convert_pi`) can be checked. Scope fixed by the owner:
   ABB and Siemens only. Until then A7 stays open and the forms are marked unverified.
4. **Check CI on GitHub** for the last pushes (no `gh` on this PC): jobs `cpp` and `frontend`.

## Environment (this PC had none)

The gates ran from a throw-away venv in the session scratchpad; it is gone. Recreate:

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pip install uvicorn nodejs-wheel-binaries   # server for the UI check, Node for the frontend
cd frontend; <node from nodejs_wheel> npm ci
```

Gates before every commit: `ruff check .`, `mypy sim loops/src api/src`, `pytest`, in `frontend/`:
`tsc --noEmit`, `vitest run`, `vite build`; style: `foremankit check <new python files>` (function
<= 20 code lines, <= 4 parameters, <= 3 nesting levels; allow-comment only for public signatures).
Browser check: `playwright-core` with the installed Edge (`channel: "msedge"`), API with uvicorn on
:8000, `vite` on :5173 (proxy `/api`).

## Next steps the assistant can do without the owner

Ordered by value. Rule from the owner: delegate tests and bulk code, keep integration, one commit per
step, push main without force, log every step, state limits plainly.

1. **Understand the 8 % stiction band discrepancy (small, do first).** The acceptance run found a band of
   8 % in 8 of 10 seeds with full noise; the demo set-up found it in 2 of 6 (seeds 1-6, 6 h record,
   first 2 h dropped). Find out why (seed set? record length? sampling?), write it into
   `experiments/exp01_stiction_validation/`, and adjust the README claim ("about 8 %, not reliably")
   if needed.
2. **Public benchmarks (V3).** Find one or two public datasets with open licences (flotation quality in
   a mining process, anomaly, degradation), check each licence BEFORE downloading, add the licence row to
   `docs/PROVENANCE.md`, put loaders in `connectors/`, run loop monitoring and stiction on what fits and
   report honestly what does not. Needs network access. This is the first test outside the simulator.
3. **Customer validation kit (V6).** Export guide (which tags, period, length, units), readiness
   checklist, anonymiser (rename tags, shift and scale values, keep dynamics; with a test that the
   result still gives the same loop findings), report template. All can be built and tested on
   synthetic messy exports (`connectors/messy.py`).
4. **Connectors.** CSV: long format, per-column units, DST-ambiguous local times. SQL: other drivers
   behind the same interface (ODBC). OPC UA: subscriptions, reconnect, namespace lookup by URI
   (tests assume `ns=2`). Test with the existing OPC UA test server.
5. **Fault layer V1, rest.** Timestamp jitter and mode flips in `sim/faults.py` (mode flips are `Event`s),
   with tests, then show them in the monitor (does the loop analysis cope?).
6. **Tuning, part 2 (C3).** Derivative term (PID), closed-loop identification (known to give biased gain
   with the operator on, see exp00), cascade order; each with an experiment and acceptance targets
   frozen BEFORE the run, as in exp02/exp03. Derive `std_reduction` for the benefit page from loop
   reports automatically (the measured pair already works through the API).
7. **Screens.** Manual window drag on the trend (tuning page), undo zoom, range presets, modules map page,
   windows for the "poor performance" finding by other means. Check each in Edge.
8. **Fuzzy Studio.** Rule matrix view; backtest of a rule base against operator moves (output
   `feed_change` is a delta of the SP tag). Advisory only.
9. **Later stages (design first, then ask):** V4 lab test bed, V5 virtual DCS with a soft PLC and a
   write-path test suite (must pass before any real write), V7 pilot package. Not before the owner has
   seen V3/V6 results.

## Known limits to keep stating

All data is synthetic. Time constant and delay are poorly identified at full noise (gain is fine).
Stiction needs sampling faster than about 15 s and a band above about 8 % at full noise; a square-wave load
is a known false alarm. Overshoot and settling in exp03 are measured on a 60 s moving average. Tuning is
advisory: nothing writes to a DCS. The "example" window of a whole-record finding is a heuristic.
