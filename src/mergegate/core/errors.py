"""Fail-closed error types. Review-time failures map to gate state Error."""


class MergeGateError(Exception):
    """Base error for MergeGate. Fail closed: never convert into a passing gate."""


class InvalidInvocationError(MergeGateError):
    """The invoking surface cannot start a review. CLI maps this to exit code 3."""


class PolicyValidationError(InvalidInvocationError):
    """A Review Policy or Compute Policy document failed schema or semantic checks."""


class GitRequiredError(InvalidInvocationError):
    """System git is missing or older than the required 2.38."""


class UnimplementedStageError(MergeGateError):
    """A pipeline stage has a contract but no implementation yet."""


class MergeConstructionError(MergeGateError):
    """The merge candidate could not be constructed. Fail closed to gate Error."""


class MergeConflictError(MergeConstructionError):
    """Proposed and target heads conflict. No review of a conflicted tree (PRD §8.1)."""

    def __init__(self, message: str, conflicted_paths: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.conflicted_paths = conflicted_paths


class WorkspaceError(MergeGateError):
    """The read-only merge-candidate workspace could not be prepared."""
