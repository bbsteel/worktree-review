"""Shared 9-stage review pipeline (PRD §21.1; TECH-DESIGN D3).

A fatal stage failure short-circuits remaining analysis stages to
``not-started``, then still records completeness, gate, and publish so a
failure cannot be hidden by later output.
"""

from pydantic import BaseModel, ConfigDict

from mergegate.core.candidate import construct_merge_candidate
from mergegate.core.errors import UnimplementedStageError
from mergegate.core.gate import GateEvaluationInput, evaluate_gate
from mergegate.core.identity import PolicyVersionIdentity, ResolvedCommitPair
from mergegate.core.policy import ComputePolicy, ReviewPolicy
from mergegate.core.report import (
    CoverageRecord,
    DimensionOutcome,
    ExecutionRecord,
    ReviewReport,
    StageName,
    StageOutcome,
    StageStatus,
)


class ReviewRequest(BaseModel):
    """Inputs the invoking surface resolved before the shared pipeline starts."""

    model_config = ConfigDict(frozen=True)

    resolved: ResolvedCommitPair
    review_policy: ReviewPolicy
    review_policy_version: PolicyVersionIdentity
    compute_policy: ComputePolicy
    compute_policy_version: PolicyVersionIdentity
    surface: str


_ANALYSIS_STAGES: tuple[StageName, ...] = (
    StageName.PREPARE_WORKSPACE,
    StageName.GATHER_CONTEXT,
    StageName.RUN_DIMENSIONS,
    StageName.VERIFY_DEDUP,
)


def _not_started(stage: StageName, detail: str | None = None) -> StageOutcome:
    return StageOutcome(stage=stage, status=StageStatus.NOT_STARTED, detail=detail)


async def run_review_pipeline(request: ReviewRequest) -> ReviewReport:
    """Run the shared pipeline. Skeleton: identity completes; merge construction fails closed."""

    execution = ExecutionRecord().with_outcome(
        StageOutcome(stage=StageName.DERIVE_IDENTITY, status=StageStatus.COMPLETED)
    )

    merge_tree_oid: str | None = None
    merge_detail = "git merge-tree --write-tree construction is not implemented"
    try:
        candidate = await construct_merge_candidate(request.resolved)
        merge_tree_oid = candidate.merge_tree_oid
        execution = execution.with_outcome(
            StageOutcome(stage=StageName.CONSTRUCT_MERGE, status=StageStatus.COMPLETED)
        )
    except UnimplementedStageError as exc:
        merge_detail = str(exc)
        execution = execution.with_outcome(
            StageOutcome(
                stage=StageName.CONSTRUCT_MERGE,
                status=StageStatus.FAILED,
                detail=merge_detail,
            )
        )

    for stage in _ANALYSIS_STAGES:
        execution = execution.with_outcome(
            _not_started(stage, "short-circuited after construct-merge failure")
        )

    dimension_outcomes = tuple(
        DimensionOutcome(dimension_id=dimension_id, status=StageStatus.NOT_STARTED)
        for dimension_id in request.review_policy.required_dimensions
    )
    coverage = CoverageRecord(required_coverage_complete=False)
    execution = execution.with_outcome(
        StageOutcome(
            stage=StageName.CHECK_COMPLETENESS,
            status=StageStatus.COMPLETED,
            detail="required dimensions and coverage did not complete",
        )
    )

    gate_state = evaluate_gate(
        GateEvaluationInput(
            dimension_outcomes=dimension_outcomes,
            coverage=coverage,
            findings=(),
            review_policy=request.review_policy,
        )
    )
    execution = execution.with_outcome(
        StageOutcome(stage=StageName.EVALUATE_GATE, status=StageStatus.COMPLETED)
    )
    execution = execution.with_outcome(
        StageOutcome(stage=StageName.PUBLISH, status=StageStatus.COMPLETED)
    )

    return ReviewReport(
        gate_state=gate_state,
        resolved=request.resolved,
        merge_tree_oid=merge_tree_oid,
        review_policy_version=request.review_policy_version,
        compute_policy_version=request.compute_policy_version,
        execution=execution,
        findings=(),
        coverage=coverage,
        dimension_outcomes=dimension_outcomes,
        summary=(
            "Review did not complete: merge-candidate construction is not "
            "implemented in this skeleton."
        ),
        error_detail=merge_detail,
    )
