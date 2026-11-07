"""Pytest checks for score.py: pass, hallucination and forbidden-hit cases on a fake repo."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import score  # noqa: E402


def make_repo(root: Path) -> Path:
    """Create a fake repo with one 20-line Python file."""
    src = root / "src"
    src.mkdir()
    (src / "a.py").write_text("\n".join(f"x = {i}" for i in range(20)), encoding="utf-8")
    return root


def key(**extra: object) -> dict[str, object]:
    """Answer key for the fake repo, with optional overrides."""
    base: dict[str, object] = {
        "files": ["src/a.py"], "mandatory": [], "optional": [], "forbidden": []
    }
    base.update(extra)
    return base


def test_pass_case(tmp_path: Path) -> None:
    """A correct citation to a real file and line passes with full score."""
    repo = make_repo(tmp_path)
    index = score.build_index(repo)
    res = score.score_run("The logic is in src/a.py:3.", key(), index, repo)
    assert res["passed"] is True
    assert res["score"] == 1.0
    assert res["hallucinated"] == 0


def test_hallucination_case(tmp_path: Path) -> None:
    """A citation to a missing file is counted and penalised."""
    repo = make_repo(tmp_path)
    index = score.build_index(repo)
    answer = "See src/missing.py:4 and src/a.py:2."
    res = score.score_run(answer, key(), index, repo)
    assert res["hallucinated"] == 1
    assert res["score"] == 0.75


def test_forbidden_hit_case(tmp_path: Path) -> None:
    """Citing a forbidden file and line fails the run and lowers the score."""
    repo = make_repo(tmp_path)
    index = score.build_index(repo)
    res = score.score_run("Look at src/a.py:10.", key(forbidden=["src/a.py:10"]), index, repo)
    assert res["forbidden_hits"] == 1
    assert res["passed"] is False
    assert res["score"] == 0.75
