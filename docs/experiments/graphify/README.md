# Graph-vs-grep experiment

Question: does answering codebase questions with the graphify graph use fewer
net tokens per correct answer than grep/read search?

## Files

- `questions.json`: 30 questions (Q01-Q30) with `answer_key` (files, mandatory,
  optional, forbidden). `accept_if` is informational only.
- `score.py`: stdlib scorer (recall, penalties, net tokens, decision rule).
- `test_score.py`: pytest cases on a fake repo.

## Arms

- **A (graph)**: agent may query `graphify-out/` first.
- **B (grep)**: agent uses only grep/glob/read. Same model and budget.

## Prompt template

    Repo: <worktree path>
    Question <Qid>: <question text>
    Arm A only: you may query graphify-out/ first.
    Answer with file:line citations for every claim.

E1-E5 are overhead runs (no code question) used to estimate fixed per-run
tokens. Their prompt text is in the experiment spec, not repeated here.

## Reproducibility

    git worktree add ../graphify-exp-890c3ef 890c3ef

Run every arm against this pinned commit, not main. Q20 describes a weakness
that main is fixing, so its key assumes 890c3ef.

## Results and scoring

Results: `results/<arm>__<qid>__<n>.json` with `answer`, `tokens_in`,
`tokens_out`, `tool_calls`, `seconds`.

    python score.py --questions questions.json --results results \
                    --repo <worktree> [--overhead N] [--out report.json]

- Citations are `path.ext:line`; a line matches within 5 of a key line.
- Recall: share of key files cited.
- Hallucination: cited file missing or line past EOF; penalty 0.5 x share.
- Forbidden hit: 0.25 each, and any hit fails the run.
- Net tokens: tokens_in + tokens_out minus overhead (median of E1-E5, else
  `--overhead`, else 0).

## Decision rule

Per type: "graph helps" if arm A net tokens per pass is at most 80% of arm B
and arm A pass rate is not lower. Otherwise "no benefit".

## Caveats

- Small sample per type: per-type verdicts are directional.
- Answer keys are hand-written; check the key before blaming the arm.
- Token counts depend on the client; compare only within one client.
- Mandatory items use keyword and file matching, not semantic grading.

## Empty-task overhead prompts (E1..E5)

Run each in both arms, same tool set, and take the median as the fixed overhead:

1. `Reply with the single word OK`
2. `Reply with the single word OK. Do not use any tools.`
3. `This is a calibration run. Reply with the single word OK`
4. `Do not look at the repository. Reply with the single word OK`
5. `Reply with the single word OK and nothing else`
