# Handoff 2026-11-18: unattended work plan (Crosscut + RougherSim)

Written for a fresh Claude session that runs this plan without the owner. Read this file first, then `docs/PRODUCT.md`,
`docs/adr/015-apc-core.md`, and the latest entries of `docs/IMPLEMENTATION_LOG.md`. Do not stop to ask the owner: decide,
record the decision in the PR body and in the log, and continue. Final report to the owner: Polish, at most 5 lines.

## State at hand-off

- Crosscut `main` = `df45893` (all CI green except one transient pybind11 download failure on Windows earlier).
  Merged today: ADR 015 owner decisions (#111), runtime/controller liveness (#112/#114, security-reviewed), frontend
  refactor (#17/#113), Codex project review fixes #115-#128 (PRs #129-#133), exp37 worklist (#108), exp32 TEP/C-MAPSS
  (#109), exp38 PRONTO (#87), exp39 flotation soft sensor (#88/#134).
- RougherSim `main` = `e564819`, tag `rs-v0.13.1`, no open issues.
- Owner decisions today (do not reopen): controller cycle 10-300 s, default 30 s; `max_overruns` configurable, default 5;
  an operator may switch a controller `on`, gateway mode `supervised` is enough; ONE DCS heartbeat (gateway only), the
  gateway monitors runtime and controller liveness; an instrument-fault anomaly finding marks the variable BAD (#120);
  L5-P1-dq targets precision >= 0.9 and recall >= 0.8 (#53); TEP and C-MAPSS licences approved; installs into `.venv`
  approved; #20 suspended; #17 done.
- Key evidence: exp36 (SKAB/3W) and exp38 (PRONTO) missed every anomaly target (quiet-data alarm share 86-100 %; 140 of 153
  PRONTO events from the stuck rule on naturally constant signals); exp39 soft sensor lost to persistence (RMSE 1.13 vs
  0.89). Diagnostic readiness is NOT established; this is the main product risk.

## Plan (in this order; packages 1 and 2 in parallel)

1. **#102 anomaly engine and loop analysis gaps.**
   - Operating-regime aware models: detect the regime from setpoints and the modes stored in the site catalogue; fit and
     score per regime; unknown regime -> no verdict (not an alarm).
   - Stuck rule: do not flag signals that are constant by nature (valve at a limit, quantised level, setpoint-like
     tags); use the tag's resolution and the regime.
   - exp33 items: settling band >= k x detected quantisation step; identification delay below one sample reported as
     a flag, not a value; oscillation check against a reference; review the 20 % saturation default; low confidence of
     `tune_from_history` on closed-loop staircases.
   - Validation: NEW experiments exp40 (SKAB/3W) and exp41 (PRONTO) with NEW protocols frozen and committed BEFORE any
     run, new splits, targets copied from exp36/exp38 unless the README argues otherwise before the run. Never tune on the
     old results. Report honestly; a miss is a result.
2. **#53 row L5-P1-dq: windowed sensor-fault detection in the onboarding report.** Freeze, drift and spikes per time
   window; test on RougherSim scenario `rs.sensor_faults.mix.v1` (LIT311 freeze 5400 s, DIT202 drift 14400 s, FIT401
   spikes); score against the owner targets (precision >= 0.9, recall >= 0.8). Update `docs/L5_FINDINGS.md` and
   `tests/integration_roughersim/matrix.py` + `docs/TESTING_STRATEGY.md` (they must match).
3. **#53 row L5-P6: fuzzy controller in closed loop** on RougherSim `rs.hardness_shift.step_up.v1`: proposals through the
   gateway in `confirm`, then `supervised`; an operator action always wins (hold-off). Add a plant map / RougherSim hook if
   missing (RougherSim change -> new tag rs-v0.13.x, then bump `tests/integration_roughersim/pin.json`). Start after
   package 2 is merged (both touch the L5 harness).
4. **Small fixes (Haiku-sized):** mypy error `runtime/src/crosscut_runtime/history.py:76` (tuple type args); flaky
   KnowledgeEditor vitest under full-suite load; cache or retry the pybind11 FetchContent download in CI (Windows).
5. **Close-out:** `docs/HANDOFF.md` (rewrite the top section to the new state), `docs/IMPLEMENTATION_LOG.md` entry, GitHub
   board 1 (Crosscut) / board 2 (RougherSim) statuses, memory file `project-night-2026-11-17.md`, short Polish report.

Out of scope today: #84 (needs a new dataset), #58 (opencode quota), L5-P4 and L5-P7 (large features), #32 (owner).

## How to work (rules learned the hard way)

- One git worktree per parallel agent, created by the lead under `C:\Users\regiz\AppData\Local\Temp\wt_<name>` from
  `origin/main` (`git worktree add -b <branch> <path> origin/main`). Two agents in one checkout leaked commits across
  branches once. The Agent tool's `isolation: worktree` fails in this repo; create worktrees manually.
- Agents: Sonnet `general-purpose` subagents in the background; give absolute paths, the check commands, and ask for a
  1-3 line report. Python: `CrosscutProcessSuite\.venv\Scripts\python.exe` with `PYTHONPATH` set to the worktree's
  package `src` dirs.
- Never `git commit -a` (the owner keeps a local `CLAUDE.md` edit); stage explicit paths. Never force-push. Commits end
  with the Co-Authored-By line given by the harness; PR bodies with the Claude Code line.
- Merge flow (owner-approved): PR with green CI (Python ubuntu+windows, C++, Frontend, both browser e2e, license/cla) ->
  `git checkout -B integ/<n> origin/main && git merge --no-edit origin/<branch>` -> resolve `docs/IMPLEMENTATION_LOG.md`
  conflicts as a union -> `git push origin integ/<n>:main`. `gh pr merge --admin` is refused by the classifier. After a
  chain of merges, check the CI run on `main`.
- The ForemanKit guard hook blocks `rm -rf`, `Remove-Item -Recurse`, `git branch -D` and force pushes; do not retry,
  work around (leave stale branches/worktrees) or report to the owner.
- Security-relevant changes (gateway, auth, write path): DeepSeek review via `mcp__foremankit__delegate` kind
  `long_context` on the diff of `*.py` without tests, then fix every high/medium finding before merging.
- Locale files (`frontend/src/locales/{en,pl,es}.json`): check for `?` replacing Polish/Spanish diacritics after every
  agent run.
- Data: public datasets only; check the licence, add a row to `docs/PROVENANCE.md`, download outside the repo
  (scratch or `C:\Users\regiz\data\`), never commit data or derived data. Flotation CSV is in
  `C:\Users\regiz\data\kaggle_flotation\`; exp32 data in `C:\Users\regiz\AppData\Local\Temp\exp32data`; PRONTO extract
  in `C:\Users\regiz\AppData\Local\Temp\pronto_x`.
- Experiments: protocol and targets committed and pushed BEFORE any run on held-out data; run once; next free number
  exp40.
- Stale worktrees exist under `C:\Users\regiz\AppData\Local\Temp\wt_*` and `.claude/worktrees/`; `git worktree prune`
  is safe, removal of directories is blocked by the guard hook.
- Follow the repo `CLAUDE.md`: graphify query before code search (and put that rule in every exploring subagent prompt),
  `graphify update .` after code changes, file headers, teaching comments, schema changes with their tests.
