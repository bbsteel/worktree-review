"""Fail-closed error types. Review-time failures map to gate state Error."""


class WorktreeReviewError(Exception):
    """Base error for Worktree Review. Fail closed: never convert into a passing gate."""


class InvalidInvocationError(WorktreeReviewError):
    """The invoking surface cannot start a review. CLI maps this to exit code 3."""


class PolicyValidationError(InvalidInvocationError):
    """A Review Policy or Compute Policy document failed schema or semantic checks."""


class GitRequiredError(InvalidInvocationError):
    """System git is missing or older than the required 2.38."""


class UnimplementedStageError(WorktreeReviewError):
    """A pipeline stage has a contract but no implementation yet."""


class MergeConstructionError(WorktreeReviewError):
    """The merge candidate could not be constructed. Fail closed to gate Error."""


class MergeConflictError(MergeConstructionError):
    """Proposed and target heads conflict. No review of a conflicted tree (PRD §8.1)."""

    def __init__(self, message: str, conflicted_paths: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.conflicted_paths = conflicted_paths


class ReviewWorktreeError(WorktreeReviewError):
    """The read-only Review Worktree could not be prepared."""


class ContextGatherError(WorktreeReviewError):
    """Context gathering could not produce a reliable coverage record."""


class BudgetExhaustedError(WorktreeReviewError):
    """The review cannot start or continue within Compute Policy's budget."""


class ProviderError(WorktreeReviewError):
    """The configured model provider could not complete a required call."""

    def __init__(self, message: str, usage: object | None = None) -> None:
        super().__init__(message)
        self.usage = usage
