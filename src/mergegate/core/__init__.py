"""Platform-independent product semantics. Adapters must not reinterpret these types."""

from mergegate.core.errors import (
    BudgetExhaustedError,
    ContextGatherError,
    GitRequiredError,
    InvalidInvocationError,
    MergeConflictError,
    MergeConstructionError,
    MergeGateError,
    PolicyValidationError,
    ProviderError,
    UnimplementedStageError,
    WorkspaceError,
)
from mergegate.core.findings import EvidenceBand, Finding, Severity
from mergegate.core.gate import (
    GateEvaluationInput,
    evaluate_gate,
    finding_blocks_under_policy,
)
from mergegate.core.identity import (
    MergeCandidateIdentity,
    PolicyVersionIdentity,
    ResolvedCommitPair,
    ReviewIdentity,
    ReviewRequestKey,
)
from mergegate.core.pipeline import ReviewRequest, run_review_pipeline
from mergegate.core.policy import ComputePolicy, ReviewPolicy
from mergegate.core.report import (
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
    "MergeGateError",
    "PolicyValidationError",
    "PolicyVersionIdentity",
    "ProviderError",
    "ResolvedCommitPair",
    "ReviewIdentity",
    "ReviewPolicy",
    "ReviewReport",
    "ReviewRequest",
    "ReviewRequestKey",
    "Severity",
    "StageName",
    "StageOutcome",
    "StageStatus",
    "UnimplementedStageError",
    "WorkspaceError",
    "evaluate_gate",
    "finding_blocks_under_policy",
    "run_review_pipeline",
]
