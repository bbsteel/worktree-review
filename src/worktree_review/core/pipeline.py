"""Shared 9-stage review pipeline (PRD §21.1; TECH-DESIGN D3).

A fatal stage failure short-circuits remaining analysis stages to
``not-started``, then still records completeness, gate, and publish so a
failure cannot be hidden by later output.
"""

import uuid
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from worktree_review.core.candidate import construct_merge_candidate
from worktree_review.core.config import ProviderConfiguration
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
    ComputePolicyDisclosure,
    CoverageRecord,
    DimensionOutcome,
    ExecutionRecord,
    GateState,
    ReviewCallPlan,
    ReviewReport,
    StageName,
    StageOutcome,
    StageStatus,
)
from worktree_review.core.review_worktree import (
    ReviewWorktree,
    cleanup_review_worktree,
    materialize_review_worktree,
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
    provider_configuration: ProviderConfiguration | None = None


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
    call_plan: ReviewCallPlan | None = None,
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
        compute_policy_disclosure=ComputePolicyDisclosure(
            provider=request.compute_policy.provider,
            model=request.compute_policy.model,
            data_destination=request.compute_policy.data_destination,
            known_retention=request.compute_policy.known_retention,
        ),
        execution=execution,
        findings=findings,
        draft_findings=draft_findings,
        coverage=resolved_coverage,
        dimension_outcomes=resolved_outcomes,
        usage=usage,
        call_plan=call_plan,
        summary=summary,
        error_detail=error_detail,
    )


async def run_review_pipeline(
    request: ReviewRequest,
    *,
    provider: ProviderClient | None = None,
    on_call_plan_ready: Callable[[ReviewCallPlan], None] | None = None,
) -> ReviewReport:
    """Run the shared pipeline through verification, gate evaluation, and publication."""

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
    review_worktree: ReviewWorktree | None = None
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
            review_worktree = await materialize_review_worktree(
                candidate,
                owner_note=owner_note,
            )
            execution = execution.with_outcome(
                StageOutcome(stage=StageName.PREPARE_REVIEW_WORKTREE, status=StageStatus.COMPLETED)
            )
        except WorktreeReviewError as exc:
            execution = execution.with_outcome(
                StageOutcome(
                    stage=StageName.PREPARE_REVIEW_WORKTREE,
                    status=StageStatus.FAILED,
                    detail=str(exc),
                )
            )
            execution = _fill_unrecorded_stages(
                execution, reason="short-circuited after prepare-review-worktree failure"
            )
            return _complete_report(
                request,
                execution,
                attempt_id=attempt_id,
                request_key=request_key,
                merge_tree_oid=candidate.merge_tree_oid,
                review_identity=review_identity,
                summary="Review did not complete: Review Worktree preparation failed.",
                error_detail=str(exc),
            )

        try:
            gathered = await gather_context(review_worktree, candidate, request.review_policy)
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
        call_plan: ReviewCallPlan | None = None
        try:
            selected_provider = (
                provider
                if provider is not None
                else build_provider(request.compute_policy, request.provider_configuration)
            )
            estimated = estimate_all_dimension_calls(
                context=gathered,
                review_policy=request.review_policy,
                provider=selected_provider,
                compute_policy=request.compute_policy,
            )
            call_plan = ReviewCallPlan(
                call_count=len(request.review_policy.required_dimensions),
                estimated_input_tokens=estimated.input_tokens,
                max_output_tokens_per_call=request.compute_policy.max_output_tokens_per_call,
            )
            if preflight_budget(request.compute_policy, estimated) is BudgetDecision.REFUSE:
                raise refuse_preflight(request.compute_policy, estimated)
            if on_call_plan_ready is not None:
                on_call_plan_ready(call_plan)
            dimension_runs = await run_required_dimensions(
                review_worktree,
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
                call_plan=call_plan,
            )

        dimension_outcomes = tuple(run.outcome for run in dimension_runs)
        draft_findings = tuple(finding for run in dimension_runs for finding in run.findings)
        usage_records = tuple(
            record
            for record in (estimated, *(run.usage for run in dimension_runs))
            if record is not None
        )
        dimensions_complete = all(
            outcome.status is StageStatus.COMPLETED for outcome in dimension_outcomes
        )
        if not dimensions_complete:
            execution = execution.with_outcome(
                StageOutcome(
                    stage=StageName.RUN_DIMENSIONS,
                    status=StageStatus.FAILED,
                    detail="one or more required dimensions did not complete",
                )
            )
        else:
            execution = execution.with_outcome(
                StageOutcome(stage=StageName.RUN_DIMENSIONS, status=StageStatus.COMPLETED)
            )
        try:
            validated_findings = verify_and_deduplicate(
                draft_findings,
                review_worktree=review_worktree,
                gathered_context=gathered,
            )
        except WorktreeReviewError as exc:
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
                summary="Review did not complete: finding verification failed.",
                error_detail=str(exc),
                coverage=gathered.coverage,
                draft_findings=draft_findings,
                dimension_outcomes=dimension_outcomes,
                usage=usage_records,
                call_plan=call_plan,
            )
        execution = execution.with_outcome(
            StageOutcome(
                stage=StageName.VERIFY_DEDUP,
                status=StageStatus.COMPLETED,
                detail=f"validated and deduplicated {len(validated_findings)} findings",
            )
        )
        if not dimensions_complete:
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
                findings=validated_findings,
                dimension_outcomes=dimension_outcomes,
                usage=usage_records,
                call_plan=call_plan,
                allow_passing_gate=True,
            )
        return _complete_report(
            request,
            execution,
            attempt_id=attempt_id,
            request_key=request_key,
            merge_tree_oid=candidate.merge_tree_oid,
            review_identity=review_identity,
            summary="Review completed.",
            error_detail=None,
            coverage=gathered.coverage,
            findings=validated_findings,
            dimension_outcomes=dimension_outcomes,
            usage=usage_records,
            call_plan=call_plan,
            allow_passing_gate=True,
        )
    finally:
        if review_worktree is not None:
            await cleanup_review_worktree(review_worktree)
