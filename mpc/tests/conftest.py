"""Resolve this worktree's reference package during isolated test runs.

The repository gate discovers src packages, while direct pytest also needs this path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
