"""Score graphify-experiment runs against the answer keys in questions.json.

Usage:
    python score.py --questions questions.json --results DIR --repo PATH
                    [--overhead N] [--out report.json]

Run files are named <arm>__<qid>__<n>.json (arm A or B). Citations are
file:line pairs. Key files match by trailing path components; mandatory and
forbidden file items match by name suffix. The accept_if text in
questions.json is informational only and is not evaluated. Net tokens
subtract the overhead: the median of the E-task runs (E1..E5) when present,
else --overhead, else 0.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
from pathlib import Path
from typing import Any

CITE_RE = re.compile(r"([\w./\\-]+\.(?:py|md|ts|tsx|json)):(\d+)")
FILE_RE = re.compile(r"^([\w./\\-]+\.(?:py|md|ts|tsx|json))(?=[ :]|$)")
STMT_FILE_RE = re.compile(r"[\w./\\-]+\.(?:py|md|ts|tsx|json)(?::[\d,/ \-]+)?")
QUOTE_RE = re.compile(r"['\"]([^'\"]+)['\"]")
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__"}
LINE_TOL = 5
HALLUC_COST = 0.5
FORBIDDEN_COST = 0.25
DECISION_RATIO = 0.8


def norm(path: str) -> str:
    """Return a path with forward slashes."""
    return path.replace("\\", "/")


def same_file(a: str, b: str) -> bool:
    """Key-file match: one-component paths must be equal, else >=2 trailing components agree."""
    pa, pb = norm(a).split("/"), norm(b).split("/")
    if min(len(pa), len(pb)) == 1:
        return pa == pb
    common = 0
    for x, y in zip(reversed(pa), reversed(pb), strict=False):
        if x != y:
            break
        common += 1
    return common >= 2


def suffix_match(cited: str, name: str) -> bool:
    """Name match for mandatory and forbidden items: cited path equals or ends with name."""
    c = norm(cited)
    return c == name or c.endswith("/" + name)


def parse_cites(answer: str) -> set[tuple[str, int]]:
    """Return the distinct (path, line) citations in an answer."""
    return {(norm(p), int(n)) for p, n in CITE_RE.findall(answer)}


def build_index(repo: Path) -> dict[str, list[str]]:
    """Map each file basename under repo to its relative posix paths."""
    index: dict[str, list[str]] = {}
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            rel = Path(root, name).relative_to(repo).as_posix()
            index.setdefault(name, []).append(rel)
    return index


def locate(index: dict[str, list[str]], repo: Path, cited: str) -> list[Path]:
    """Return the repo files that a cited path refers to."""
    name = norm(cited).split("/")[-1]
    return [repo / rel for rel in index.get(name, []) if suffix_match(rel, norm(cited))]


def is_hallucinated(index: dict[str, list[str]], repo: Path, path: str, line: int) -> bool:
    """True when the cited file is missing under repo or the line is past its end."""
    found = locate(index, repo, path)
    if not found:
        return True
    longest = max(len(p.read_text(encoding="utf-8", errors="replace").splitlines()) for p in found)
    return line > longest


def split_item(item: str) -> tuple[str | None, list[int], str | None]:
    """Return (file, line numbers, symbol word) for a file-style key item, else (None, [], None)."""
    m = FILE_RE.match(item)
    if not m:
        return None, [], None
    loc, _, tail = item[m.end():].partition(" ")
    sym = re.search(r"[A-Za-z_]\w*", tail)
    lines = [int(n) for n in re.findall(r"\d+", loc)]
    return m.group(1), lines, sym.group(0) if sym else None


def statement_found(item: str, answer: str) -> bool:
    """Statement item: the first two words appear in the answer, case-insensitive."""
    text = STMT_FILE_RE.sub(" ", item)
    words = re.findall(r"[A-Za-z]+", text)[:2]
    if not words:
        return False
    phrase = r"\s+".join(map(re.escape, words))
    return re.search(r"\b" + phrase + r"\b", answer, re.IGNORECASE) is not None


def file_item_found(
    parts: tuple[str, list[int], str | None], cites: set[tuple[str, int]], answer: str
) -> bool:
    """File item: file cited within LINE_TOL of a listed line, or its symbol word in the answer."""
    file, lines, sym = parts
    hits = [n for p, n in cites if suffix_match(p, file)]
    if lines:
        file_ok = any(abs(n - ln) <= LINE_TOL for n in hits for ln in lines)
    else:
        file_ok = bool(hits)
    sym_ok = bool(sym) and re.search(r"\b" + re.escape(sym) + r"\b", answer) is not None
    return file_ok or sym_ok


def item_found(item: str, cites: set[tuple[str, int]], answer: str) -> bool:
    """Return True when a mandatory key item is satisfied by the answer."""
    parts = split_item(item)
    if parts[0] is None:
        return statement_found(item, answer)
    return file_item_found((parts[0], parts[1], parts[2]), cites, answer)


def forbidden_hit(item: str, cites: set[tuple[str, int]], answer: str) -> bool:
    """Return True when the answer cites a forbidden file/line or quotes a forbidden phrase."""
    file, lines, _ = split_item(item)
    if file is None:
        wanted = {q.lower() for q in QUOTE_RE.findall(item)}
        given = {q.lower() for q in QUOTE_RE.findall(answer)}
        return bool(wanted & given)
    hits = [n for p, n in cites if suffix_match(p, file)]
    if not lines:
        return bool(hits)
    return any(abs(n - ln) <= LINE_TOL for n in hits for ln in lines)


def score_run(
    answer: str, key: dict[str, Any], index: dict[str, list[str]], repo: Path
) -> dict[str, Any]:
    """Score one answer against its answer_key."""
    cites = parse_cites(answer)
    files = key.get("files", [])
    cited_keys = [f for f in files if any(same_file(p, f) for p, _ in cites)]
    recall = len(cited_keys) / len(files) if files else 1.0
    halluc = sum(is_hallucinated(index, repo, p, n) for p, n in cites)
    penalty = HALLUC_COST * halluc / max(len(cites), 1)
    mand_ok = all(item_found(i, cites, answer) for i in key.get("mandatory", []))
    forb = sum(forbidden_hit(i, cites, answer) for i in key.get("forbidden", []))
    score = min(1.0, max(0.0, recall - penalty - FORBIDDEN_COST * forb))
    return {
        "passed": mand_ok and forb == 0,
        "score": score,
        "recall": recall,
        "hallucinated": halluc,
        "forbidden_hits": forb,
    }


def load_questions(path: Path) -> dict[str, dict[str, Any]]:
    """Return questions keyed by id."""
    return {q["id"]: q for q in json.loads(path.read_text(encoding="utf-8"))}


def load_runs(results: Path) -> list[dict[str, Any]]:
    """Load every <arm>__<qid>__<n>.json run file in results."""
    runs = []
    for path in sorted(results.glob("*.json")):
        parts = path.stem.split("__")
        if len(parts) != 3 or parts[0] not in ("A", "B"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        runs.append({"arm": parts[0], "qid": parts[1], "data": data})
    return runs


def tokens_of(data: dict[str, Any]) -> float | None:
    """Return tokens_in + tokens_out, or None when both are missing."""
    tin, tout = data.get("tokens_in"), data.get("tokens_out")
    if tin is None and tout is None:
        return None
    return (tin or 0) + (tout or 0)


def overhead_of(runs: list[dict[str, Any]], fallback: float | None) -> float:
    """Median tokens of the E-task runs, else the fallback, else 0."""
    vals = []
    for run in runs:
        tok = tokens_of(run["data"]) if run["qid"].startswith("E") else None
        if tok is not None:
            vals.append(tok)
    if vals:
        return statistics.median(vals)
    return fallback or 0.0


def score_record(run: dict[str, Any], questions: dict[str, Any], index: dict[str, list[str]],
                 repo: Path, overhead: float) -> dict[str, Any] | None:
    """Return the scored record for a run, or None when its qid is not in questions."""
    q = questions.get(run["qid"])
    if q is None:
        return None
    data = run["data"]
    res = score_run(str(data.get("answer") or ""), q.get("answer_key", {}), index, repo)
    tok = tokens_of(data)
    return {
        "arm": run["arm"],
        "type": q["type"],
        "passed": res["passed"],
        "score": res["score"],
        "net": None if tok is None else tok - overhead,
        "tool_calls": data.get("tool_calls"),
        "seconds": data.get("seconds"),
    }


def mean_of(values: Any) -> float | None:
    """Mean of the non-None values, rounded, or None."""
    vals = [v for v in values if v is not None]
    return round(statistics.fmean(vals), 3) if vals else None


def aggregate(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise records. net_tokens_per_pass = total net tokens of all runs / passed runs."""
    passes = sum(1 for r in recs if r["passed"])
    nets = [r["net"] for r in recs if r["net"] is not None]
    return {
        "runs": len(recs),
        "passes": passes,
        "pass_rate": round(passes / len(recs), 3) if recs else None,
        "mean_score": mean_of(r["score"] for r in recs),
        "mean_net_tokens": mean_of(r["net"] for r in recs),
        "net_tokens_per_pass": round(sum(nets) / passes, 1) if passes and nets else None,
        "mean_tool_calls": mean_of(r["tool_calls"] for r in recs),
        "mean_seconds": mean_of(r["seconds"] for r in recs),
    }


def decide(a: dict[str, Any], b: dict[str, Any]) -> str:
    """Return 'graph helps' when A is at least 20% cheaper per pass and no less accurate."""
    if a["net_tokens_per_pass"] is None or b["net_tokens_per_pass"] is None:
        return "no benefit"
    cheaper = a["net_tokens_per_pass"] <= DECISION_RATIO * b["net_tokens_per_pass"]
    if cheaper and a["pass_rate"] >= b["pass_rate"]:
        return "graph helps"
    return "no benefit"


def build_report(runs: list[dict[str, Any]], questions: dict[str, Any], index: dict[str, list[str]],
                 repo: Path, overhead_arg: float | None) -> dict[str, Any]:
    """Score all runs and build the per-arm, per-type report with decisions."""
    overhead = overhead_of(runs, overhead_arg)
    recs = [rec for rec in (score_record(r, questions, index, repo, overhead) for r in runs) if rec]
    types = sorted({q["type"] for q in questions.values()})
    arms: dict[str, Any] = {}
    for arm in ("A", "B"):
        mine = [r for r in recs if r["arm"] == arm]
        arms[arm] = {
            "overall": aggregate(mine),
            "by_type": {str(t): aggregate([r for r in mine if r["type"] == t]) for t in types},
        }
    decision = {
        str(t): decide(arms["A"]["by_type"][str(t)], arms["B"]["by_type"][str(t)]) for t in types
    }
    return {"overhead": overhead, "arms": arms, "decision_by_type": decision}


def cell(value: Any) -> str:
    """Render a table cell, with '-' for missing values."""
    return "-" if value is None else str(value)


def print_table(report: dict[str, Any]) -> None:
    """Print a compact table of overall and per-type metrics plus the decisions."""
    print(f"overhead={report['overhead']}")
    print(f"{'arm':<5}{'type':<6}{'runs':>5}{'pass':>7}{'score':>8}{'net/pass':>10}{'tools':>7}{'sec':>7}")
    for arm, block in report["arms"].items():
        rows = [("all", block["overall"])] + list(block["by_type"].items())
        for label, agg in rows:
            print(f"{arm:<5}{label:<6}{cell(agg['runs']):>5}{cell(agg['pass_rate']):>7}"
                  f"{cell(agg['mean_score']):>8}{cell(agg['net_tokens_per_pass']):>10}"
                  f"{cell(agg['mean_tool_calls']):>7}{cell(agg['mean_seconds']):>7}")
    for t, verdict in report["decision_by_type"].items():
        print(f"type {t}: {verdict}")


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description="Score graphify experiment runs.")
    ap.add_argument("--questions", required=True, type=Path)
    ap.add_argument("--results", required=True, type=Path)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--overhead", type=float, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    questions = load_questions(args.questions)
    index = build_index(args.repo)
    report = build_report(load_runs(args.results), questions, index, args.repo, args.overhead)
    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_table(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
