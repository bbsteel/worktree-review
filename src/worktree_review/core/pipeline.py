"""Shared 9-stage review pipeline (PRD §21.1; TECH-DESIGN D3).

A fatal stage failure short-circuits remaining analysis stages to
``not-started``, then still records completeness, gate, and publish so a
failure cannot be hidden by later output.
"""

import uuid

from pydantic import BaseModel, ConfigDict

from worktree_review.core.candidate import construct_merge_candidate
from worktree_review.core.context import gather_context
from worktree_review.core.dimension import estimate_all_dimension_calls, run_required_dimensions
from worktree_review.core.errors import UnimplementedStageError, WorktreeReviewError
from worktree_review.core.findings import Finding, verify_and_deduplicate
from worktree_review.core.gate import GateEvaluationInput, evaluate_gate
from worktree_review.core.identity import (
    MergeCandidateIdentity,
    PolicyVersionIdentity,
    ResolvedCommitPair,
    ReviewIdentity,
    ReviewRequestKey,
)
from worktree_review.core.policy import ComputePolicy, ReviewPolicy
from worktree_review.core.provider import (
    BudgetDecision,
    ProviderClient,
    UsageRecord,
    build_provider,
    preflight_budget,
    refuse_preflight,
)
from worktree_review.core.report import (
    PIPELINE_STAGE_ORDER,
    CoverageRecord,
    DimensionOutcome,
    ExecutionRecord,
    GateState,
    ReviewReport,
    StageName,
    StageOutcome,
    StageStatus,
)
from worktree_review.core.workspace import (
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


def _fill_unrecorded_stages(execution: ExecutionRecord, *, reason: str) -> ExecutionRecord:
    recorded = {outcome.stage for outcome in execution.outcomes}
    for stage in PIPELINE_STAGE_ORDER:
        if stage in recorded or stage in _POST_FAILURE_STAGES:
            continue
        execution = execution.with_outcome(_not_started(stage, reason))
    return execution


def _coverage_error_detail(coverage: CoverageRecord) -> str:
    parts: list[str] = []
    if coverage.mandatory_missing:
        parts.append("mandatory context missing: " + ", ".join(coverage.mandatory_missing))
    if coverage.unreviewable:
        parts.append("unreviewable in-scope content: " + ", ".join(coverage.unreviewable))
    return "; ".join(parts) or "required coverage is incomplete"


def _complete_report(
    request: ReviewRequest,
    execution: ExecutionRecord,
    *,
    attempt_id: str,
    request_key: ReviewRequestKey,
    merge_tree_oid: str | None,
    review_identity: ReviewIdentity | None,
    summary: str,
    error_detail: str | None,
    coverage: CoverageRecord | None = None,
    findings: tuple[Finding, ...] = (),
    draft_findings: tuple[Finding, ...] = (),
    dimension_outcomes: tuple[DimensionOutcome, ...] | None = None,
    usage: tuple[UsageRecord, ...] = (),
    allow_passing_gate: bool = False,
) -> ReviewReport:
    resolved_coverage = coverage or CoverageRecord(required_coverage_complete=False)
    resolved_outcomes = dimension_outcomes or tuple(
        DimensionOutcome(dimension_id=dimension_id, status=StageStatus.NOT_STARTED)
        for dimension_id in request.review_policy.required_dimensions
    )
    dimensions_complete = bool(resolved_outcomes) and all(
        outcome.status is StageStatus.COMPLETED for outcome in resolved_outcomes
    )
    execution = execution.with_outcome(
        StageOutcome(
            stage=StageName.CHECK_COMPLETENESS,
            status=StageStatus.COMPLETED,
            detail=(
                "required coverage and dimensions completed"
                if resolved_coverage.required_coverage_complete and dimensions_complete
                else "required dimensions and coverage did not complete"
            ),
        )
    )
    gate_state = evaluate_gate(
        GateEvaluationInput(
            dimension_outcomes=resolved_outcomes,
            coverage=resolved_coverage,
            findings=findings,
            review_policy=request.review_policy,
        )
    )
    if not allow_passing_gate and gate_state is not GateState.ERROR:
        # Unverified findings must not Block or Pass (PRD §8.5, §13).
        gate_state = GateState.ERROR
        error_detail = error_detail or (
            "review cannot produce a standing decision until finding verification completes"
        )
    execution = execution.with_outcome(
        StageOutcome(stage=StageName.EVALUATE_GATE, status=StageStatus.COMPLETED)
    )
    execution = execution.with_outcome(
        StageOutcome(stage=StageName.PUBLISH, status=StageStatus.COMPLETED)
    )
    return ReviewReport(
        gate_state=gate_state,
        attempt_id=attempt_id,
        request_key=request_key,
        resolved=request.resolved,
        merge_tree_oid=merge_tree_oid,
        review_identity=review_identity,
        review_policy_version=request.review_policy_version,
        compute_policy_version=request.compute_policy_version,
        execution=execution,
        findings=findings,
        draft_findings=draft_findings,
        coverage=resolved_coverage,
        dimension_outcomes=resolved_outcomes,
        usage=usage,
        summary=summary,
        error_detail=error_detail,
    )


async def run_review_pipeline(
    request: ReviewRequest,
    *,
    provider: ProviderClient | None = None,
) -> ReviewReport:
    """Run the shared pipeline through required dimensions. Verification is not implemented."""

    request_key = ReviewRequestKey(
        source_repository=request.resolved.source_repository,
        target_ref=request.resolved.target_ref,
        target_head_oid=request.resolved.target_head_oid,
        proposed_head_oid=request.resolved.proposed_head_oid,
        review_policy_version=request.review_policy_version,
    )
    attempt_id = str(uuid.uuid4())
    execution = ExecutionRecord().with_outcome(
        StageOutcome(
            stage=StageName.DERIVE_IDENTITY,
            status=StageStatus.COMPLETED,
            detail=f"attempt {attempt_id}",
        )
    )
    candidate: MergeCandidateIdentity | None = None
    review_identity: ReviewIdentity | None = None
    workspace: ReviewWorkspace | None = None
    owner_note = "invoking user" if request.surface == "cli" else "unprivileged runtime user"

    try:
        try:
            candidate = await construct_merge_candidate(request.resolved)
            review_identity = ReviewIdentity(
                candidate=candidate,
                review_policy_version=request.review_policy_version,
            )
            execution = execution.with_outcome(
                StageOutcome(stage=StageName.CONSTRUCT_MERGE, status=StageStatus.COMPLETED)
            )
        except WorktreeReviewError as exc:
            execution = execution.with_outcome(
                StageOutcome(
                    stage=StageName.CONSTRUCT_MERGE,
                    status=StageStatus.FAILED,
                    detail=str(exc),
                )
            )
            execution = _fill_unrecorded_stages(
                execution, reason="short-circuited after construct-merge failure"
            )
            return _complete_report(
                request,
                execution,
                attempt_id=attempt_id,
                request_key=request_key,
                merge_tree_oid=None,
                review_identity=None,
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
        except WorktreeReviewError as exc:
            execution = execution.with_outcome(
                StageOutcome(
                    stage=StageName.PREPARE_WORKSPACE,
                    status=StageStatus.FAILED,
                    detail=str(exc),
                )
            )
            execution = _fill_unrecorded_stages(
                execution, reason="short-circuited after prepare-workspace failure"
            )
            return _complete_report(
                request,
                execution,
                attempt_id=attempt_id,
                request_key=request_key,
                merge_tree_oid=candidate.merge_tree_oid,
                review_identity=review_identity,
                summary="Review did not complete: workspace preparation failed.",
                error_detail=str(exc),
            )

        try:
            gathered = await gather_context(workspace, candidate, request.review_policy)
        except (WorktreeReviewError, UnimplementedStageError) as exc:
            execution = execution.with_outcome(
                StageOutcome(
                    stage=StageName.GATHER_CONTEXT,
                    status=StageStatus.FAILED,
                    detail=str(exc),
                )
            )
            execution = _fill_unrecorded_stages(
                execution, reason="short-circuited after gather-context failure"
            )
            return _complete_report(
                request,
                execution,
                attempt_id=attempt_id,
                request_key=request_key,
                merge_tree_oid=candidate.merge_tree_oid,
                review_identity=review_identity,
                summary="Review did not complete: context gathering failed.",
                error_detail=str(exc),
            )

        execution = execution.with_outcome(
            StageOutcome(stage=StageName.GATHER_CONTEXT, status=StageStatus.COMPLETED)
        )
        if not gathered.coverage.required_coverage_complete:
            execution = _fill_unrecorded_stages(
                execution, reason="short-circuited: required coverage is incomplete"
            )
            return _complete_report(
                request,
                execution,
                attempt_id=attempt_id,
                request_key=request_key,
                merge_tree_oid=candidate.merge_tree_oid,
                review_identity=review_identity,
                summary="Review did not complete: required context coverage is incomplete.",
                error_detail=_coverage_error_detail(gathered.coverage),
                coverage=gathered.coverage,
            )

        estimated: UsageRecord | None = None
        try:
            selected_provider = (
                provider if provider is not None else build_provider(request.compute_policy)
            )
            estimated = estimate_all_dimension_calls(
                context=gathered,
                review_policy=request.review_policy,
                provider=selected_provider,
                compute_policy=request.compute_policy,
            )
            if preflight_budget(request.compute_policy, estimated) is BudgetDecision.REFUSE:
                raise refuse_preflight(request.compute_policy, estimated)
            dimension_runs = await run_required_dimensions(
                workspace,
                gathered,
                request.review_policy,
                selected_provider,
                request.compute_policy,
            )
        except WorktreeReviewError as exc:
            execution = execution.with_outcome(
                StageOutcome(
                    stage=StageName.RUN_DIMENSIONS,
                    status=StageStatus.FAILED,
                    detail=str(exc),
                )
            )
            execution = _fill_unrecorded_stages(
                execution, reason="short-circuited after run-dimensions failure"
            )
            return _complete_report(
                request,
                execution,
                attempt_id=attempt_id,
                request_key=request_key,
                merge_tree_oid=candidate.merge_tree_oid,
                review_identity=review_identity,
                summary="Review did not complete: required review dimensions failed.",
                error_detail=str(exc),
                coverage=gathered.coverage,
                usage=() if estimated is None else (estimated,),
            )

        dimension_outcomes = tuple(run.outcome for run in dimension_runs)
        draft_findings = tuple(finding for run in dimension_runs for finding in run.findings)
        usage_records = tuple(
            record
            for record in (estimated, *(run.usage for run in dimension_runs))
            if record is not None
        )
        if any(outcome.status is not StageStatus.COMPLETED for outcome in dimension_outcomes):
            execution = execution.with_outcome(
                StageOutcome(
                    stage=StageName.RUN_DIMENSIONS,
                    status=StageStatus.FAILED,
                    detail="one or more required dimensions did not complete",
                )
            )
            execution = _fill_unrecorded_stages(
                execution, reason="short-circuited after run-dimensions failure"
            )
            return _complete_report(
                request,
                execution,
                attempt_id=attempt_id,
                request_key=request_key,
                merge_tree_oid=candidate.merge_tree_oid,
                review_identity=review_identity,
                summary="Review did not complete: a required dimension failed.",
                error_detail="one or more required dimensions did not complete",
                coverage=gathered.coverage,
                draft_findings=draft_findings,
                dimension_outcomes=dimension_outcomes,
                usage=usage_records,
            )

        execution = execution.with_outcome(
            StageOutcome(stage=StageName.RUN_DIMENSIONS, status=StageStatus.COMPLETED)
        )
        try:
            verified = verify_and_deduplicate(draft_findings)
        except UnimplementedStageError as exc:
            execution = execution.with_outcome(
                StageOutcome(
                    stage=StageName.VERIFY_DEDUP,
                    status=StageStatus.FAILED,
                    detail=str(exc),
                )
            )
            execution = _fill_unrecorded_stages(
                execution, reason="short-circuited after verify-dedup failure"
            )
            return _complete_report(
                request,
                execution,
                attempt_id=attempt_id,
                request_key=request_key,
                merge_tree_oid=candidate.merge_tree_oid,
                review_identity=review_identity,
                summary="Review did not complete: finding verification is not implemented.",
                error_detail=str(exc),
                coverage=gathered.coverage,
                draft_findings=draft_findings,
                dimension_outcomes=dimension_outcomes,
                usage=usage_records,
            )
        del verified
        raise UnimplementedStageError("pipeline stages after verification are not implemented")
    finally:
        if workspace is not None:
            await cleanup_review_workspace(workspace)
