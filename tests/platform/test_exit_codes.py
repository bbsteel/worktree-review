from __future__ import annotations

import pytest

from worktree_review.core.report import GateState
from worktree_review.platform.cli.exit_codes import CliExitCode, exit_code_for_gate_state


def test_terminal_cli_mapping() -> None:
    assert exit_code_for_gate_state(GateState.PASSED) is CliExitCode.PASSED
    assert exit_code_for_gate_state(GateState.BLOCKED) is CliExitCode.BLOCKED
    assert exit_code_for_gate_state(GateState.ERROR) is CliExitCode.ERROR


def test_cli_never_emits_passed_with_bypass() -> None:
    with pytest.raises(ValueError, match="never emit Passed with bypass"):
        exit_code_for_gate_state(GateState.PASSED_WITH_BYPASS)


def test_non_terminal_states_are_rejected() -> None:
    with pytest.raises(ValueError):
        exit_code_for_gate_state(GateState.AWAITING_REVIEW)
    with pytest.raises(ValueError):
        exit_code_for_gate_state(GateState.IN_PROGRESS)
