"""Local CLI adapter: terminal report, JSON result, process exit codes (PRD §21.3, D10)."""

from mergegate.platform.cli.exit_codes import CliExitCode, exit_code_for_gate_state

__all__ = ["CliExitCode", "exit_code_for_gate_state"]
