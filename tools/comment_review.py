"""Review the explanatory comments of a Python file with a cheap model that sees the whole file.

The loop walks the file in chunks (bottom-up so line numbers stay valid), asks the model to
delete or correct comments that are wrong or that only restate the code, and applies the answer
only when the code fingerprint is unchanged, ruff finds nothing new and the tests pass. Only
edits of pure comment blocks are accepted: code, docstrings and trailing comments are never
touched. Accepted edits are appended to a JSON-lines log.

Usage (from the repository root)::

    PYTHONPATH=<agentkit dir> python tools/comment_review.py \
        --tests "python -m pytest sim -q" --log review.jsonl FILE...
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from comment_loop import code_unchanged, ruff_problem_count
from refactor_loop import run

MAX_CHUNK_LINES = 220
MAX_COMMENT_CHARACTERS = 95
ANSWER_FILE_PATTERN = re.compile(r"^file: (?P<path>\S+)", re.MULTILINE)
JSON_BLOCK_PATTERN = re.compile(r"```json\n(?P<json>.*?)```", re.DOTALL)

PROMPT_RULES = (
    "You review explanatory comments written by a model that saw only one function. "
    "You see the whole file. For each comment block in the lines to review:\n"
    "(a) verify every claim against the code, the docstrings and the module docstring: units, "
    "formulas, the direction of signs, what a variable means, which test or invariant is "
    "mentioned;\n"
    "(b) DELETE it if it is wrong and you cannot fix it with certainty, or if it only restates "
    "the code line below it, or if it is vague filler;\n"
    "(c) REPLACE it with a corrected comment if the idea is useful but a detail is wrong;\n"
    "(d) leave correct comments that teach the model, formula, unit or data structure untouched.\n"
    "When unsure whether a domain claim is true, delete it: a missing comment is better than a "
    "false one. Never touch code lines, docstrings or trailing comments. Keep comments at most "
    f"{MAX_COMMENT_CHARACTERS} characters per line. Return only edits; an empty array [] is a "
    "valid answer. Each edit must cover one WHOLE comment block, from its first to its last "
    "comment line (never part of a block). Answer with ONE ```json block.\n\n"
)


@dataclass(frozen=True)
class Edit:
    """One comment edit: the line range to change and what to do with it."""

    first: int
    last: int
    action: str
    text: str
    reason: str


@dataclass(frozen=True)
class ReviewChecks:
    """What must hold for a candidate file to be kept: tests command and ruff baseline."""

    tests: str
    ruff_before: int
    escalate: bool = False


def ask_model_text(prompt: str, files: list[Path], escalate: bool = False) -> str | None:
    """Run the delegating model with the given files as context; return its answer text or None."""
    command = [
        sys.executable,
        "-m",
        "agentkit.cli",
        "delegate",
        prompt,
        "--kind",
        "bulk_code",
        "--max-output-tokens",
        "3500",
        "--files",
        *map(str, files),
    ]
    result = run(command + (["--escalate"] if escalate else []))
    answer_file = ANSWER_FILE_PATTERN.search(result.stdout)
    if answer_file is None:
        return None
    blocks = JSON_BLOCK_PATTERN.findall(Path(answer_file["path"]).read_text(encoding="utf8"))
    return blocks[0] if blocks else None


def node_span(node: ast.stmt) -> tuple[int, int]:
    """(first, last) lines of a top-level node, decorators included."""
    decorators = getattr(node, "decorator_list", ())
    decorator_lines = [decorator.lineno for decorator in decorators]
    first = min([node.lineno, *decorator_lines])
    return first, node.end_lineno or node.lineno


def top_level_spans(source: str) -> list[tuple[int, int]]:
    """Line spans of the top-level definitions of a module, in file order."""
    tree = ast.parse(source)
    return [
        node_span(node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


def class_method_spans(source: str, class_span: tuple[int, int]) -> list[tuple[int, int]]:
    """Line spans of the methods inside a class, in file order."""
    tree = ast.parse(source)
    for node in tree.body:
        first, last = node_span(node)
        if isinstance(node, ast.ClassDef) and (first, last) == class_span:
            return [
                node_span(child)
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
    return []


def split_span(source: str, span: tuple[int, int], max_lines: int) -> list[tuple[int, int]]:
    """Split a long class at its method boundaries so that no part exceeds ``max_lines``."""
    if span[1] - span[0] + 1 <= max_lines:
        return [span]
    methods = class_method_spans(source, span)
    if not methods:
        return [span]
    parts = []
    part_first = span[0]
    for first, last in methods:
        if last - part_first + 1 > max_lines and part_first < first:
            parts.append((part_first, first - 1))
            part_first = first
    parts.append((part_first, span[1]))
    return parts


def merge_spans(spans: list[tuple[int, int]], max_lines: int) -> list[tuple[int, int]]:
    """Merge consecutive spans greedily so that no merged chunk exceeds ``max_lines``."""
    parts: list[tuple[int, int]] = []
    first = 1
    last = 0
    for start, end in spans:
        if last == 0:
            last = end
        if end - first + 1 > max_lines and last > 0:
            parts.append((first, last))
            first = start
            last = end
        else:
            last = end
    if last >= first:
        parts.append((first, last))
    return parts


def chunks(source: str, max_lines: int = MAX_CHUNK_LINES) -> list[tuple[int, int]]:
    """Split the file into chunks that start at a definition and stay within ``max_lines``."""
    spans = [
        part
        for span in top_level_spans(source)
        for part in split_span(source, span, max_lines)
    ]
    return merge_spans(spans, max_lines)


def number_lines(lines: list[str], first: int, last: int) -> str:
    """The lines ``first..last`` as "N| text", so the model can quote line numbers."""
    numbered = (f"{number}| {lines[number - 1]}" for number in range(first, last + 1))
    return "\n".join(numbered)


def build_prompt(path: Path, lines: list[str], chunk: tuple[int, int]) -> str:
    """The review instruction for one chunk, with the numbered lines to review."""
    first, last = chunk
    return (
        f"{PROMPT_RULES}"
        f"File: {path}\n"
        f"Lines to review: {first} to {last}.\n"
        f"{number_lines(lines, first, last)}\n\n"
        "Answer with a JSON array of edits: "
        '[{"first": int, "last": int, "action": "delete" | "replace", '
        '"text": str, "reason": str}]. For "replace", text holds the new comment lines WITHOUT '
        "indentation, separated by \\n.\n"
    )


def parse_edits(answer: str) -> list[Edit]:
    """The well-formed edits of a JSON answer; malformed items are ignored."""
    try:
        items = json.loads(answer)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    return [edit for edit in map(parse_edit, items) if edit is not None]


def parse_edit(item: object) -> Edit | None:
    """One edit from a JSON object, or None when the object is malformed."""
    if not isinstance(item, dict):
        return None
    try:
        return Edit(
            first=int(item["first"]),
            last=int(item["last"]),
            action=str(item["action"]),
            text=str(item.get("text", "")),
            reason=str(item.get("reason", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def is_inside(edit: Edit, chunk: tuple[int, int]) -> bool:
    """True when the edit's whole range lies inside the chunk."""
    return chunk[0] <= edit.first <= edit.last <= chunk[1]


def is_comment_line(line: str) -> bool:
    """True when the line holds only a comment (never a trailing one)."""
    return line.strip().startswith("#")


def is_whole_block(lines: list[str], edit: Edit) -> bool:
    """True when the edit starts and ends at the borders of one comment block.

    A partial edit would leave the rest of the block behind and duplicate the new text.
    """
    before = lines[edit.first - 2] if edit.first >= 2 else ""
    after = lines[edit.last] if edit.last < len(lines) else ""
    indent = line_indent(lines[edit.first - 1])
    same_block = [line for line in (before, after) if is_comment_line(line)]
    return all(line_indent(line) != indent for line in same_block)


def overlaps_any(edit: Edit, accepted: list[Edit]) -> bool:
    """True when the edit's line range shares a line with an already accepted edit."""
    edited = range(edit.first, edit.last + 1)
    return any(set(edited) & set(range(other.first, other.last + 1)) for other in accepted)


def validate_edits(lines: list[str], edits: list[Edit], chunk: tuple[int, int]) -> list[Edit]:
    """The edits inside the chunk that touch comment-only lines and do not overlap."""
    accepted: list[Edit] = []
    for edit in edits:
        if not is_inside(edit, chunk) or edit.action not in ("delete", "replace"):
            continue
        edited = range(edit.first, edit.last + 1)
        if not all(is_comment_line(lines[line_number - 1]) for line_number in edited):
            continue
        if overlaps_any(edit, accepted) or not is_whole_block(lines, edit):
            continue
        accepted.append(edit)
    return accepted


def line_indent(line: str) -> str:
    """The leading whitespace of a line, used to re-indent a replacement comment."""
    return line[: len(line) - len(line.lstrip())]


def reindent(line: str, indent: str) -> str:
    """One replacement comment line with the indentation of the comment it replaces."""
    stripped = line.strip()
    if stripped.startswith("#"):
        return indent + stripped + "\n"
    return f"{indent}# {stripped}\n" if stripped else indent + "#\n"


def apply_edits(lines: list[str], edits: list[Edit]) -> list[str]:
    """Apply the edits bottom-up so that earlier line numbers stay valid."""
    result = list(lines)
    for edit in sorted(edits, key=lambda edit: edit.first, reverse=True):
        indent = line_indent(result[edit.first - 1])
        if edit.action == "delete":
            del result[edit.first - 1 : edit.last]
        else:
            result[edit.first - 1 : edit.last] = [
                reindent(line, indent) for line in edit.text.split("\n")
            ]
    return result


def old_comment_text(lines: list[str], edit: Edit) -> str:
    """The comment text an edit replaces or deletes, for the log."""
    return " / ".join(line.strip() for line in lines[edit.first - 1 : edit.last])


def log_edit(log_path: Path, path: Path, lines: list[str], edit: Edit) -> None:
    """Append one accepted edit to the JSON-lines log."""
    record = {
        "file": str(path),
        "first": edit.first,
        "last": edit.last,
        "action": edit.action,
        "old": old_comment_text(lines, edit),
        "new": edit.text,
        "reason": edit.reason,
    }
    with log_path.open("a", encoding="utf8") as log_file:
        log_file.write(json.dumps(record) + "\n")


def is_acceptable(path: Path, original: str, candidate: str, checks: ReviewChecks) -> bool:
    """True when the candidate keeps the code, adds no ruff problem and passes the tests."""
    if not code_unchanged(original, candidate):
        return False
    path.write_text(candidate, encoding="utf8", newline="")
    ruff_after = ruff_problem_count(path)
    return ruff_after <= checks.ruff_before and run(checks.tests, shell=True).returncode == 0


def review_chunk(
    path: Path, chunk: tuple[int, int], log_path: Path, checks: ReviewChecks
) -> tuple[int, int]:
    """Review one chunk; returns (kept, rejected) and writes the accepted edits to the log."""
    original = path.read_text(encoding="utf8")
    lines = original.splitlines(keepends=True)
    answer = ask_model_text(build_prompt(path, lines, chunk), [path], checks.escalate)
    edits = parse_edits(answer) if answer is not None else []
    accepted = validate_edits(lines, edits, chunk)
    if not accepted:
        return 0, len(edits)
    candidate = "".join(apply_edits(lines, accepted))
    if is_acceptable(path, original, candidate, checks):
        for edit in accepted:
            log_edit(log_path, path, lines, edit)
        return len(accepted), len(edits) - len(accepted)
    path.write_text(original, encoding="utf8", newline="")
    return 0, len(edits)


def review_file(path: Path, checks_template: ReviewChecks, log_path: Path) -> tuple[int, int]:
    """Review every chunk of one file bottom-up; returns (edits_kept, edits_rejected)."""
    source = path.read_text(encoding="utf8")
    kept = rejected = 0
    checks = replace(checks_template, ruff_before=ruff_problem_count(path))
    for chunk in reversed(chunks(source)):
        chunk_kept, chunk_rejected = review_chunk(path, chunk, log_path, checks)
        kept += chunk_kept
        rejected += chunk_rejected
    return kept, rejected


def main() -> int:
    """Entry point: review every given file and print one summary line per file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--tests", required=True, help="command that must pass after every chunk")
    parser.add_argument("--escalate", action="store_true", help="use the stronger model")
    parser.add_argument("--log", required=True, type=Path, help="JSON-lines log of accepted edits")
    arguments = parser.parse_args()
    for path in arguments.files:
        template = ReviewChecks(arguments.tests, 0, arguments.escalate)
        kept, rejected = review_file(path, template, arguments.log)
        print(f"{path}: kept {kept}, rejected {rejected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
