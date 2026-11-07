# Running the graph-vs-grep experiment

Pinned commit 890c3ef. Worktrees (outside OneDrive):

- A (graph): `C:\Users\regiz\AppData\Local\Temp\graphify-exp-A` (graph in `graphify-out/`, `.graphifyignore` excluded via `info/exclude`)
- B (grep): `C:\Users\regiz\AppData\Local\Temp\graphify-exp-B` (no graph)

Task files: `python docs/experiments/graphify/make_tasks.py` writes 35 files per arm to `C:\Users\regiz\AppData\Local\Temp\graphify-tasks\{A,B}`.

## 1. Run the arms (from ForemanKit)

    cd "C:\Users\regiz\OneDrive\Documents\Python Scripts\ForemanKit"
    .venv\Scripts\foremankit agent-ask-batch --tasks-dir C:\Users\regiz\AppData\Local\Temp\graphify-tasks\A --out-dir C:\Users\regiz\AppData\Local\Temp\graphify-results\A --runner opencode --project C:\Users\regiz\AppData\Local\Temp\graphify-exp-A
    .venv\Scripts\foremankit agent-ask-batch --tasks-dir C:\Users\regiz\AppData\Local\Temp\graphify-tasks\B --out-dir C:\Users\regiz\AppData\Local\Temp\graphify-results\B --runner opencode --project C:\Users\regiz\AppData\Local\Temp\graphify-exp-B

## 2. Merge results for scoring

score.py expects one folder with `<arm>__<qid>__<n>.json`:

    mkdir C:\Users\regiz\AppData\Local\Temp\graphify-results\all
    copy /Y C:\Users\regiz\AppData\Local\Temp\graphify-results\A\*.json C:\Users\regiz\AppData\Local\Temp\graphify-results\all\
    copy /Y C:\Users\regiz\AppData\Local\Temp\graphify-results\B\*.json C:\Users\regiz\AppData\Local\Temp\graphify-results\all\

## 3. Score

    python docs/experiments/graphify/score.py --questions docs/experiments/graphify/questions.json --results C:\Users\regiz\AppData\Local\Temp\graphify-results\all --repo C:\Users\regiz\AppData\Local\Temp\graphify-exp-A --out C:\Users\regiz\AppData\Local\Temp\graphify-results\report.json

Scoring is per answer key against the pinned worktree; use `--repo` of the arm whose citations you check (both worktrees are at 890c3ef, so either works).
