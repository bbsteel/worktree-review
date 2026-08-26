"""CLI process exit codes (TECH-DESIGN D10). ``Passed with bypass`` is never produced."""

from enum import IntEnum

from mergegate.core.report import GateState


class CliExitCode(IntEnum):
    PASSED = 0
    BLOCKED = 1
    ERROR = 2
    INVALID_INVOCATION = 3


def exit_code_for_gate_state(gate_state: GateState) -> CliExitCode:
    if gate_state is GateState.PASSED:
        return CliExitCode.PASSED
    if gate_state is GateState.BLOCKED:
        return CliExitCode.BLOCKED
    if gate_state is GateState.ERROR:
        return CliExitCode.ERROR
    if gate_state is GateState.PASSED_WITH_BYPASS:
        raise ValueError(
            "the CLI must never emit Passed with bypass (PRD §4, §11; TECH-DESIGN D10)"
        )
    raise ValueError(f"gate state {gate_state} is not a CLI terminal state")
