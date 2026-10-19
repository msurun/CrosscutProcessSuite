"""Add explanatory comments to Python functions with a cheap model, changing no code.

For every function of a file (longest first is not needed: the file is processed bottom-up so line
numbers stay valid) the loop asks ``foremankit delegate`` to add comments that teach the reader the
model, the formula or the data structure behind the code. A result is kept only if

* the syntax tree without docstrings is identical to the original (so no code changed),
* ``ruff`` finds nothing new in the file (line length!) and
* the test command passes.

Usage (from the repository root)::

    PYTHONPATH=<ForemanKit dir> python tools/comment_loop.py \
        --tests "python -m pytest sim -q" FILE...
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

from refactor_loop import ask_model, run

MIN_BODY_LINES = 6  # shorter functions are readable without a lecture
INSTRUCTION = (
    "Add explanatory comments to this Python function. DO NOT change any code: not a name, not a "
    "number, not the order of statements, not the formatting of code lines.\n"
    "Write comments that TEACH a reader who knows Python but not the domain: what the model or "
    "algorithm is, what each non-obvious variable means with its UNIT, where a formula comes from "
    "(one line of derivation or the name of the method), how a data structure works and which "
    "invariant it keeps. Put a comment above the block it explains. Do not comment lines that "
    "are obvious. You may extend the docstring. Keep every line at most 100 characters.\n"
    "Keep the exact original indentation. Answer with ONE ```python code block containing the "
    "complete function and nothing else.\n\n```python\n"
)


def function_spans(source: str) -> list[tuple[int, int]]:
    """(first, last) lines of every top-level function and method with a long enough body."""
    spans = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            first = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
            last = node.end_lineno or node.lineno
            if last - node.lineno >= MIN_BODY_LINES:
                spans.append((first, last))
    return sorted(spans, reverse=True)  # bottom-up: edits do not move the spans still to do


def code_fingerprint(source: str) -> str:
    """The syntax tree without docstrings: equal fingerprints mean the code is unchanged."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        has_docstring = (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        )
        if has_docstring:
            node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree)


def ruff_problem_count(path: Path) -> int:
    """Number of ruff findings in one file."""
    result = run([sys.executable, "-m", "ruff", "check", str(path), "--output-format", "concise"])
    findings = [line for line in result.stdout.splitlines() if ":" in line]
    return sum(1 for line in findings if "error" not in line.lower())


def try_comment(path: Path, span: tuple[int, int], tests: str) -> bool:
    """Ask for comments on one function; keep the result only when every check passes."""
    original = path.read_text(encoding="utf8")
    lines = original.splitlines(keepends=True)
    function_source = "".join(lines[span[0] - 1 : span[1]])
    replacement = ask_model(INSTRUCTION + function_source + "```\n", escalate=False)
    if replacement is None or replacement == function_source:
        return False
    candidate = "".join(lines[: span[0] - 1]) + replacement + "".join(lines[span[1] :])
    if not code_unchanged(original, candidate):
        return False
    before = ruff_problem_count(path)
    path.write_text(candidate, encoding="utf8", newline="")
    if ruff_problem_count(path) <= before and run(tests, shell=True).returncode == 0:
        return True
    path.write_text(original, encoding="utf8", newline="")
    return False


def code_unchanged(original: str, candidate: str) -> bool:
    """True when the candidate parses and has the same code as the original."""
    try:
        return code_fingerprint(candidate) == code_fingerprint(original)
    except SyntaxError:
        return False


def comment_file(path: Path, tests: str) -> tuple[int, int]:
    """Comment every long function of one file; returns (changed, unchanged)."""
    changed = unchanged = 0
    for span in function_spans(path.read_text(encoding="utf8")):
        if try_comment(path, span, tests):
            changed += 1
        else:
            unchanged += 1
    return changed, unchanged


def main() -> int:
    """Entry point: comment every given file and print one line per file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--tests", required=True, help="command that must pass after every change")
    arguments = parser.parse_args()
    for path in arguments.files:
        changed, unchanged = comment_file(path, arguments.tests)
        print(f"{path}: commented {changed}, left as is {unchanged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
