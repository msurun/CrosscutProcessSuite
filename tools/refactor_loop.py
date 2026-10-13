"""Fix style-gate findings one function at a time with a cheap model, keeping only verified results.

For every finding reported by ``agentkit check`` the loop sends ONE function (not the file) to
``agentkit delegate``, splices the answer into the file, and accepts it only if the file still
parses, the number of findings in it drops and the test command passes. Otherwise the file is
restored and the finding is skipped after ``MAX_ATTEMPTS`` tries.

Usage (from the repository root)::

    PYTHONPATH=<agentkit dir> python tools/refactor_loop.py \
        --tests "python -m pytest sim -q" FILE...
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_ATTEMPTS = 2
MAX_OUTPUT_TOKENS = 3500
FINDING_PATTERN = re.compile(r"^(?P<path>.+?):(?P<line>\d+): (?P<code>[\w-]+): (?P<message>.*)$")
ANSWER_FILE_PATTERN = re.compile(r"^file: (?P<path>\S+)", re.MULTILINE)
CODE_BLOCK_PATTERN = re.compile(r"```(?:python)?\n(?P<code>.*?)```", re.DOTALL)

INSTRUCTIONS = {
    "function-too-long": "Split it into small private helpers (at most 20 lines each) "
    "with intention-revealing names.",
    "too-many-parameters": "Reduce it to at most 4 parameters by grouping related ones into a "
    "small frozen dataclass defined above the function, keeping the public behaviour.",
    "too-deep-nesting": "Reduce nesting to at most 3 levels with early returns or a helper.",
    "short-name": "Rename the meaningless one-letter names to names that reveal intent.",
    "missing-docstring": "Add a one-sentence docstring that says what it does, not how.",
    "line-too-long": "Wrap lines longer than 100 characters (split expressions, keep the names).",
    "type-error": "Fix the type problem (add missing annotations; remove duplicate definitions).",
}
RUFF_PATTERN = re.compile(r"^(?P<path>.+?):(?P<line>\d+):\d+: E501 (?P<message>.*)$")
MYPY_PATTERN = re.compile(r"^(?P<path>.+?):(?P<line>\d+): error: (?P<message>.*)$")


@dataclass(frozen=True)
class Finding:
    """One style-gate finding: where it is and what is wrong."""

    path: Path
    line: int
    code: str
    message: str


@dataclass(frozen=True)
class Span:
    """First and last line (1-based, inclusive) of a function including its decorators."""

    first: int
    last: int


def run(command: list[str] | str, shell: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a command and capture its text output without raising on a non-zero exit."""
    return subprocess.run(
        command, shell=shell, capture_output=True, text=True, encoding="utf8", check=False
    )


def read_findings(path: Path) -> list[Finding]:
    """The style-gate findings of one file."""
    output = run([sys.executable, "-m", "agentkit.cli", "check", str(path)]).stdout
    matches = (FINDING_PATTERN.match(line) for line in output.splitlines())
    style = [
        Finding(path, int(match["line"]), match["code"], match["message"])
        for match in matches
        if match and match["code"] in INSTRUCTIONS
    ]
    return style + read_lint_findings(path)


def read_lint_findings(path: Path) -> list[Finding]:
    """Long lines (ruff) and type errors (mypy) of one file, as findings."""
    ruff = run(
        [sys.executable, "-m", "ruff", "check", str(path), "--output-format", "concise"]
    ).stdout
    mypy = run([sys.executable, "-m", "mypy", str(path)]).stdout
    found = [
        Finding(path, int(match["line"]), "line-too-long", match["message"])
        for match in map(RUFF_PATTERN.match, ruff.splitlines())
        if match
    ]
    found += [
        Finding(path, int(match["line"]), "type-error", match["message"])
        for match in map(MYPY_PATTERN.match, mypy.splitlines())
        if match
    ]
    return found


def enclosing_function(source: str, line: int) -> Span | None:
    """The innermost function whose body contains ``line`` (or whose definition starts there)."""
    best: Span | None = None
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            first = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
            if first <= line <= (node.end_lineno or node.lineno) and (
                best is None or first >= best.first
            ):
                best = Span(first, node.end_lineno or node.lineno)
    return best


def build_prompt(finding: Finding, function_source: str) -> str:
    """The instruction sent to the model for one function."""
    return (
        "Refactor this Python function without changing its behaviour. "
        f"Problem: {finding.message}\n"
        f"{INSTRUCTIONS[finding.code]}\n"
        "Rules: keep every formula and the order of floating point operations identical; "
        "keep the exact "
        "original indentation of the function (it may be a method); new helpers go right "
        "after the function "
        "at the same indentation; docstring on every function; comments explain WHY only.\n"
        "Answer with ONE ```python code block containing the replacement code (the function "
        "plus its new "
        "helpers) and nothing else.\n\n```python\n" + function_source + "```\n"
    )


def ask_model(prompt: str, escalate: bool) -> str | None:
    """The code block of the model's answer, or None when the call or the parsing fails."""
    command = [
        sys.executable,
        "-m",
        "agentkit.cli",
        "delegate",
        prompt,
        "--kind",
        "bulk_code",
        "--max-output-tokens",
        str(MAX_OUTPUT_TOKENS),
    ]
    result = run(command + (["--escalate"] if escalate else []))
    answer_file = ANSWER_FILE_PATTERN.search(result.stdout)
    if answer_file is None:
        return None
    blocks = CODE_BLOCK_PATTERN.findall(Path(answer_file["path"]).read_text(encoding="utf8"))
    return blocks[0] if blocks else None


def try_fix(finding: Finding, tests: str, escalate: bool) -> bool:
    """Apply the model's fix for one finding; keep it only when the checks pass."""
    original = finding.path.read_text(encoding="utf8")
    span = enclosing_function(original, finding.line)
    if span is None:
        return False
    lines = original.splitlines(keepends=True)
    replacement = ask_model(
        build_prompt(finding, "".join(lines[span.first - 1 : span.last])), escalate
    )
    if replacement is None:
        return False
    candidate = "".join(lines[: span.first - 1]) + replacement + "".join(lines[span.last :])
    finding.path.write_text(candidate, encoding="utf8", newline="")
    if is_improvement(finding, original, candidate, tests):
        return True
    finding.path.write_text(original, encoding="utf8", newline="")
    return False


def is_improvement(finding: Finding, original: str, candidate: str, tests: str) -> bool:
    """True when the candidate parses, has fewer findings than the original and passes the tests."""
    try:
        ast.parse(candidate)
    except SyntaxError:
        return False
    finding.path.write_text(original, encoding="utf8", newline="")
    before = len(read_findings(finding.path))
    finding.path.write_text(candidate, encoding="utf8", newline="")
    after = len(read_findings(finding.path))
    return after < before and run(tests, shell=True).returncode == 0


def clean_file(path: Path, tests: str) -> tuple[int, int]:
    """Work through the findings of one file; returns (fixed, skipped)."""
    fixed, skipped = 0, set()
    while True:
        open_findings = [
            finding
            for finding in read_findings(path)
            if (finding.code, finding.message) not in skipped
        ]
        if not open_findings:
            return fixed, len(skipped)
        finding = open_findings[0]
        if any(try_fix(finding, tests, escalate=attempt > 0) for attempt in range(MAX_ATTEMPTS)):
            fixed += 1
        else:
            skipped.add((finding.code, finding.message))
            print(f"  skipped: {finding.path}:{finding.line} {finding.code}")


def main() -> int:
    """Entry point: clean every given file and print a one-line summary per file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument(
        "--tests", required=True, help="command that must pass after every accepted fix"
    )
    arguments = parser.parse_args()
    for path in arguments.files:
        fixed, skipped = clean_file(path, arguments.tests)
        print(f"{path}: fixed {fixed}, skipped {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
