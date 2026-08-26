"""Platform-independent product semantics. Adapters must not reinterpret these types."""

from mergegate.core.errors import (
    GitRequiredError,
    InvalidInvocationError,
    MergeGateError,
    PolicyValidationError,
    UnimplementedStageError,
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
    "ComputePolicy",
    "CoverageRecord",
    "EvidenceBand",
    "ExecutionRecord",
    "Finding",
    "GateEvaluationInput",
    "GateState",
    "GitRequiredError",
    "InvalidInvocationError",
    "MergeCandidateIdentity",
    "MergeGateError",
    "PolicyValidationError",
    "PolicyVersionIdentity",
    "ResolvedCommitPair",
    "ReviewIdentity",
    "ReviewPolicy",
    "ReviewReport",
    "ReviewRequest",
    "Severity",
    "StageName",
    "StageOutcome",
    "StageStatus",
    "UnimplementedStageError",
    "evaluate_gate",
    "finding_blocks_under_policy",
    "run_review_pipeline",
]
