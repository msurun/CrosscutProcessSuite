# Blind-review pack for the loop worklist

Purpose: HANDOFF step 3 asks for a blind review of the prioritised worklist by an independent control engineer
(Kendall tau >= 0.5 against the automatic `priority_rank`, >= 80 % agreement on the next action). This pack makes
that review cheap: 20 simulated loops with known faults, a self-contained review sheet, and a comparison script.
Everything is synthetic. The simulated faults and the author's key are one person's opinion; the reviewer's list is
the independent part.

## Build (writes `out/`, which is not committed)

```
$env:PYTHONPATH="loops/src;sim/src"
.venv\Scripts\python experiments/review_pack/make_pack.py
```

## Give the reviewer ONLY

- `out/review_sheet.html` (open in a browser, fill in, press "Export answers CSV"),
- `out/reviewer_instructions.md`, and optionally `out/answers_template.csv`.

Keep to yourself: `out/answer_key.csv` (injected cause and the author's expected action) and `out/loops_meta.csv`.
The reviewer must not see any output of the automatic analysis.

## Compare

```
.venv\Scripts\python experiments/review_pack/compare.py <reviewer_answers.csv>
```

Prints Kendall tau-b between the reviewer's rank and `priority_rank`, and a table (reviewer category, automatic
`next_action` code, author's key action). The script gives no pass/fail verdict.

## Known limits

- The HTML sheet (inline JavaScript for the form and CSV export, SVG plots) was generated but not opened in a
  browser in the session that built it; open it once yourself before sending it.
- Loops are built with no per-loop knowledge configured, so the automatic worklist answers `configure_knowledge`
  for many healthy and sluggish loops. That is the product's honest behaviour, not a defect of the pack. For a fairer
  test, add OUT ranges and delays to the loop tags in `compare.py` and run it a second time.
- The 20th loop (spec gap) is a fifth healthy flow loop.
- Do not adjust the worklist rules after looking at the comparison and then call the same review a validation.
