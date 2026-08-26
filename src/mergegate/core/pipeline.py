"""Shared 9-stage review pipeline (PRD §21.1; TECH-DESIGN D3).

A fatal stage failure short-circuits remaining analysis stages to
``not-started``, then still records completeness, gate, and publish so a
failure cannot be hidden by later output.
"""

from pydantic import BaseModel, ConfigDict

from mergegate.core.candidate import construct_merge_candidate
from mergegate.core.context import gather_context
from mergegate.core.errors import MergeGateError, UnimplementedStageError
from mergegate.core.gate import GateEvaluationInput, evaluate_gate
from mergegate.core.identity import (
    MergeCandidateIdentity,
    PolicyVersionIdentity,
    ResolvedCommitPair,
)
from mergegate.core.policy import ComputePolicy, ReviewPolicy
from mergegate.core.report import (
    PIPELINE_STAGE_ORDER,
    CoverageRecord,
    DimensionOutcome,
    ExecutionRecord,
    ReviewReport,
    StageName,
    StageOutcome,
    StageStatus,
)
from mergegate.core.workspace import (
    ReviewWorkspace,
    cleanup_review_workspace,
    materialize_read_only_workspace,
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


_POST_FAILURE_STAGES: frozenset[StageName] = frozenset(
    {
        StageName.CHECK_COMPLETENESS,
        StageName.EVALUATE_GATE,
        StageName.PUBLISH,
    }
)


def _not_started(stage: StageName, detail: str | None = None) -> StageOutcome:
    return StageOutcome(stage=stage, status=StageStatus.NOT_STARTED, detail=detail)


def _fill_unrecorded_stages(
    execution: ExecutionRecord,
    *,
    failed_stage: StageName,
) -> ExecutionRecord:
    recorded = {outcome.stage for outcome in execution.outcomes}
    detail = f"short-circuited after {failed_stage.value} failure"
    for stage in PIPELINE_STAGE_ORDER:
        if stage in recorded or stage in _POST_FAILURE_STAGES:
            continue
        execution = execution.with_outcome(_not_started(stage, detail))
    return execution


def _complete_report(
    request: ReviewRequest,
    execution: ExecutionRecord,
    *,
    merge_tree_oid: str | None,
    summary: str,
    error_detail: str | None,
) -> ReviewReport:
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
        summary=summary,
        error_detail=error_detail,
    )


async def run_review_pipeline(request: ReviewRequest) -> ReviewReport:
    """Run the shared pipeline through merge construction and workspace materialization."""

    execution = ExecutionRecord().with_outcome(
        StageOutcome(stage=StageName.DERIVE_IDENTITY, status=StageStatus.COMPLETED)
    )
    candidate: MergeCandidateIdentity | None = None
    workspace: ReviewWorkspace | None = None
    owner_note = "invoking user" if request.surface == "cli" else "unprivileged runtime user"

    try:
        try:
            candidate = await construct_merge_candidate(request.resolved)
            execution = execution.with_outcome(
                StageOutcome(stage=StageName.CONSTRUCT_MERGE, status=StageStatus.COMPLETED)
            )
        except MergeGateError as exc:
            execution = execution.with_outcome(
                StageOutcome(
                    stage=StageName.CONSTRUCT_MERGE,
                    status=StageStatus.FAILED,
                    detail=str(exc),
                )
            )
            execution = _fill_unrecorded_stages(execution, failed_stage=StageName.CONSTRUCT_MERGE)
            return _complete_report(
                request,
                execution,
                merge_tree_oid=None,
                summary="Review did not complete: merge-candidate construction failed.",
                error_detail=str(exc),
            )

        try:
            workspace = await materialize_read_only_workspace(
                candidate,
                owner_note=owner_note,
            )
            execution = execution.with_outcome(
                StageOutcome(stage=StageName.PREPARE_WORKSPACE, status=StageStatus.COMPLETED)
            )
        except MergeGateError as exc:
            execution = execution.with_outcome(
                StageOutcome(
                    stage=StageName.PREPARE_WORKSPACE,
                    status=StageStatus.FAILED,
                    detail=str(exc),
                )
            )
            execution = _fill_unrecorded_stages(execution, failed_stage=StageName.PREPARE_WORKSPACE)
            return _complete_report(
                request,
                execution,
                merge_tree_oid=candidate.merge_tree_oid,
                summary="Review did not complete: workspace preparation failed.",
                error_detail=str(exc),
            )

        try:
            await gather_context(workspace, request.review_policy)
        except UnimplementedStageError as exc:
            execution = execution.with_outcome(
                StageOutcome(
                    stage=StageName.GATHER_CONTEXT,
                    status=StageStatus.FAILED,
                    detail=str(exc),
                )
            )
            execution = _fill_unrecorded_stages(execution, failed_stage=StageName.GATHER_CONTEXT)
            return _complete_report(
                request,
                execution,
                merge_tree_oid=candidate.merge_tree_oid,
                summary="Review did not complete: context gathering is not implemented.",
                error_detail=str(exc),
            )
        raise UnimplementedStageError("pipeline stages after context gathering are not implemented")
    finally:
        if workspace is not None:
            await cleanup_review_workspace(workspace)
