"""Generate graph-vs-grep task files for the graphify A/B experiment.

Reads questions.json next to this file and writes one markdown task per
question and arm, plus the E1-E5 overhead prompts, into per-arm folders.
Output is deterministic: re-running overwrites files with identical text.
Stdlib only.
"""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = Path(r"C:\Users\regiz\AppData\Local\Temp\graphify-tasks")
TOOLS_A = (
    "You work in a code repository (current folder). Allowed tools: "
    "grep/glob/read, and the `graphify` CLI ONLY as: "
    '`graphify affected "<symbol>" --depth 2`, `graphify path "<A>" "<B>"`, '
    '`graphify explain "<symbol>"`, `graphify query "<symbol>" --context call` '
    "(or --context import); if graphify output is truncated or mostly test_* "
    "nodes switch to grep. When a bare symbol name is ambiguous (exists in "
    "several files, error), write it as `<repo-relative path>::<symbol>`, e.g. "
    "`gateway/src/crosscut_gateway/actor.py::normalize_actor`; if you do not "
    "know the file, find it with grep first."
)
TOOLS_B = (
    "You work in a code repository (current folder). Allowed tools: "
    "grep/glob/read ONLY. Do NOT run graphify and do not read any "
    "graphify-out folder."
)
E_PROMPTS = [
    "Reply with the single word OK",
    "Reply with the single word OK. Do not use any tools.",
    "This is a calibration run. Reply with the single word OK",
    "Do not look at the repository. Reply with the single word OK",
    "Reply with the single word OK and nothing else",
]
E_TOOL_RULE_B = (
    "Use only grep/glob/read and do not run graphify."
)


def load_questions(path: Path) -> list[dict]:
    """Return the question records from questions.json."""
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def build_files() -> dict[str, dict[str, str]]:
    """Map arm -> {filename: text} for all 35 tasks per arm."""
    questions = load_questions(HERE / "questions.json")
    files: dict[str, dict[str, str]] = {"A": {}, "B": {}}
    for item in questions:
        qid = item["id"]
        text = item["question"]
        files["A"][f"A__{qid}__1.md"] = f"{TOOLS_A}\n\nQuestion: {text}\n"
        files["B"][f"B__{qid}__1.md"] = f"{TOOLS_B}\n\nQuestion: {text}\n"
    for index, prompt in enumerate(E_PROMPTS, start=1):
        files["A"][f"A__E{index}__1.md"] = f"{prompt}\n"
        files["B"][f"B__E{index}__1.md"] = f"{E_TOOL_RULE_B} {prompt}\n"
    return files


def write_arm(out_dir: Path, arm_files: dict[str, str]) -> int:
    """Write the arm's files into out_dir; return the count written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in sorted(arm_files.items()):
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
    return len(arm_files)


def main() -> None:
    """Write A and B task folders under --out."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    files = build_files()
    for arm in ("A", "B"):
        count = write_arm(args.out / arm, files[arm])
        print(f"arm {arm}: {count} files in {args.out / arm}")


if __name__ == "__main__":
    main()
