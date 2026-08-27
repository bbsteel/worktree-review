"""Platform-independent product semantics. Adapters must not reinterpret these types."""

from worktree_review.core.errors import (
    BudgetExhaustedError,
    ContextGatherError,
    GitRequiredError,
    InvalidInvocationError,
    MergeConflictError,
    MergeConstructionError,
    PolicyValidationError,
    ProviderError,
    ReviewWorktreeError,
    UnimplementedStageError,
    WorktreeReviewError,
)
from worktree_review.core.findings import EvidenceBand, Finding, Severity
from worktree_review.core.gate import (
    GateEvaluationInput,
    evaluate_gate,
    finding_blocks_under_policy,
)
from worktree_review.core.identity import (
    MergeCandidateIdentity,
    PolicyVersionIdentity,
    ResolvedCommitPair,
    ReviewIdentity,
    ReviewRequestKey,
)
from worktree_review.core.pipeline import ReviewRequest, run_review_pipeline
from worktree_review.core.policy import ComputePolicy, ReviewPolicy
from worktree_review.core.report import (
    CoverageRecord,
    ExecutionRecord,
    GateState,
    ReviewReport,
    StageName,
    StageOutcome,
    StageStatus,
)

__all__ = [
    "BudgetExhaustedError",
    "ComputePolicy",
    "ContextGatherError",
    "CoverageRecord",
    "EvidenceBand",
    "ExecutionRecord",
    "Finding",
    "GateEvaluationInput",
    "GateState",
    "GitRequiredError",
    "InvalidInvocationError",
    "MergeCandidateIdentity",
    "MergeConflictError",
    "MergeConstructionError",
    "PolicyValidationError",
    "PolicyVersionIdentity",
    "ProviderError",
    "ResolvedCommitPair",
    "ReviewIdentity",
    "ReviewPolicy",
    "ReviewReport",
    "ReviewRequest",
    "ReviewRequestKey",
    "ReviewWorktreeError",
    "Severity",
    "StageName",
    "StageOutcome",
    "StageStatus",
    "UnimplementedStageError",
    "WorktreeReviewError",
    "evaluate_gate",
    "finding_blocks_under_policy",
    "run_review_pipeline",
]
