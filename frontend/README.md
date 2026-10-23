# Crosscut web UI

React + TypeScript + Vite. Checks: `npm run typecheck`, `npm test` (vitest, jsdom), `npm run build`,
`npm run lint` (ESLint size limits as warnings on the files rewritten on 2026-10-20).

## End-to-end tests (Playwright, real Chromium)

`e2e/smoke.spec.ts` opens every main view in Polish at 1440 and 390 px and checks: no console or HTTP
errors, heading visible, no horizontal page scroll at 390 px, axe-core without serious/critical violations.

1. Make demo datasets in one folder, one directory per dataset (names are used by the spec):
   `python -m crosscut_sim.run --plant mill_circuit --scenario stiction --duration 6h --sample-period 10 --out <tmp>`
   and the same for `step_test`; move the `mill_circuit_<scenario>_seed42` folders into one data root.
   For `e2e/level.spec.ts` (integrating loops) add the generated level dataset to the same root:
   `python e2e/support/make_level_dataset.py <data root>` (creates `level_integrating_demo`).
   `advisory.spec.ts` writes to the data root (`_supervisor`, `_advisory`): use a scratch copy and set
   `E2E_DATA_ROOT=<data root>` for `npm run e2e`; the spec resets the supervisor state before each test.
   `softsensor.spec.ts` writes `_softsensor` to the data root (reset before each test) and makes its lab CSV with
   `e2e/support/make_lab_csv.py` (numpy, pyarrow); `E2E_PYTHON=<python.exe>` selects the interpreter (default `python`).
2. API: `uvicorn` serving `create_app(Path("<data root>"))` on port 8000.
3. UI: `npm run dev` (port 5173). Other ports: `CROSSCUT_API=http://127.0.0.1:8010 npx vite --port 5183`
   and `E2E_BASE_URL=http://127.0.0.1:5183`.
4. `npm run e2e`. `E2E_SHOTS=<folder>` also saves a full-page screenshot per view at 1440 px;
   `E2E_CHROMIUM=<path to chrome.exe>` overrides the Chromium found in `%LOCALAPPDATA%\ms-playwright`.
