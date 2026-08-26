from __future__ import annotations

import subprocess
import sys

from mergegate.core import GateState, StageName


def test_core_does_not_import_server_or_github_adapters() -> None:
    script = """
import sys
import mergegate.core  # noqa: F401

forbidden = (
    "fastapi",
    "githubkit",
    "asyncpg",
    "pgqueuer",
    "alembic",
    "mergegate.server",
    "mergegate.cli",
    "mergegate.platform.github",
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
