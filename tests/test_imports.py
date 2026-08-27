from __future__ import annotations

import subprocess
import sys

from worktree_review.core import GateState, StageName


def test_core_does_not_import_server_or_github_adapters() -> None:
    script = """
import sys
import worktree_review.core  # noqa: F401

forbidden = (
    "fastapi",
    "githubkit",
    "asyncpg",
    "pgqueuer",
    "alembic",
    "worktree_review.server",
    "worktree_review.cli",
    "worktree_review.platform.github",
)
loaded = [name for name in forbidden if name in sys.modules]
assert loaded == [], loaded
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_pipeline_stage_count_matches_prd() -> None:
    assert len(StageName) == 9


def test_gate_state_labels_match_prd() -> None:
    assert GateState.AWAITING_REVIEW == "Awaiting review"
    assert GateState.IN_PROGRESS == "In progress"
    assert GateState.PASSED == "Passed"
    assert GateState.PASSED_WITH_BYPASS == "Passed with bypass"
    assert GateState.BLOCKED == "Blocked"
    assert GateState.ERROR == "Error"
